"""Bounded local preparation/status protocol. No approval or SMTP authority here."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import stat
import struct

MAX_FRAME = 2_097_152


class SendError(Exception):
    """Only fixed, non-sensitive errors cross the MCP boundary."""


def require(condition, message='Send request rejected.'):
    if not condition:
        raise SendError(message)


def peer_uid(connection):
    # Production support is deliberately Linux-only; no unauthenticated fallback.
    require(hasattr(socket, 'SO_PEERCRED'), 'Send IPC requires Linux peer credentials.')
    return struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]


def receive(connection):
    def exact(length):
        result = bytearray()
        while len(result) < length:
            block = connection.recv(min(65536, length - len(result)))
            require(bool(block), 'Incomplete send IPC frame.')
            result.extend(block)
        return bytes(result)
    length = struct.unpack('!I', exact(4))[0]
    require(0 < length <= MAX_FRAME, 'Send IPC size limit exceeded.')
    try:
        value = json.loads(exact(length))
    except (ValueError, UnicodeError):
        raise SendError('Invalid send IPC frame.') from None
    require(isinstance(value, dict), 'Invalid send IPC frame.')
    return value


def transmit(connection, value):
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
    require(0 < len(raw) <= MAX_FRAME, 'Send IPC size limit exceeded.')
    connection.sendall(struct.pack('!I', len(raw)) + raw)


@dataclass(frozen=True)
class ClientConfig:
    path: Path
    sender_uid: int

    @classmethod
    def load(cls):
        switch = os.environ.get('INBOXTETHER_SEND_ASSISTANT', '0')
        require(switch in ('0', '1'), 'Invalid Send Assistant setting.')
        if switch == '0':
            return None
        require(os.environ.get('INBOXTETHER_SEND_MODE', 'secure') == 'secure', 'Only Secure Send Mode exists.')
        path = Path(os.environ.get('INBOXTETHER_SEND_SOCKET', ''))
        uid = os.environ.get('INBOXTETHER_SEND_UID', '')
        require(path.is_absolute() and uid.isdecimal(), 'Configure the trusted sender socket and UID.')
        require(int(uid) > 0 and int(uid) != os.geteuid(), 'Sender and MCP must use distinct non-root identities.')
        return cls(path, int(uid))


def request(operation, arguments, config=None):
    config = config or ClientConfig.load()
    require(config is not None, 'Send Assistant is disabled.')
    require(operation in ('prepare', 'status'), 'Operation is not exposed to MCP.')
    try:
        info = config.path.lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == config.sender_uid
                and stat.S_IMODE(info.st_mode) == 0o660, 'Unsafe sender socket.')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(10)
            connection.connect(str(config.path))
            require(peer_uid(connection) == config.sender_uid, 'Unexpected sender identity.')
            transmit(connection, {'operation': operation, 'arguments': arguments})
            response = receive(connection)
        require(response.get('ok') is True, 'Trusted sender rejected the request.')
        require(isinstance(response.get('result'), dict), 'Invalid sender response.')
        return response['result']
    except SendError:
        raise
    except Exception:
        raise SendError('Trusted sender unavailable; no automatic request retry.') from None
