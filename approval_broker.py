"""Local approval IPC. No MCP transport, HTTP listener, IMAP login or sending.

The web process has a distinct UID; only that UID may submit OIDC decisions.
The broker owns the existing private store. Terminal approval remains an admin path.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
from pathlib import Path
import pwd
import socket
import socketserver
import stat
import struct
import sys

from draft_assistant import Config, DraftError, ID, Store, canonical, require

MAX_FRAME = 1_048_576
REVIEW_ERRORS = frozenset(('missing_batch', 'expired', 'authorization', 'broker_timeout', 'broker_error'))

class ReviewError(Exception):
    def __init__(self, code):
        self.code = code if code in REVIEW_ERRORS else 'broker_error'
        super().__init__(self.code)


def peer_uid(connection):
    if hasattr(socket, 'SO_PEERCRED'):
        return struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    # macOS/BSD, fail closed on unsupported platforms.
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    fn = ctypes.CDLL(None, use_errno=True).getpeereid
    require(fn(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0, 'IPC peer unavailable.')
    return uid.value


def receive(connection):
    def exact(size):
        parts = bytearray()
        while len(parts) < size:
            chunk = connection.recv(size-len(parts))
            require(bool(chunk), 'Incomplete IPC frame.')
            parts.extend(chunk)
        return bytes(parts)
    size = struct.unpack('!I', exact(4))[0]
    require(0 < size <= MAX_FRAME, 'IPC frame limit exceeded.')
    return json.loads(exact(size))


def send(connection, data):
    raw = canonical(data)
    require(len(raw) <= MAX_FRAME, 'IPC response limit exceeded.')
    connection.sendall(struct.pack('!I', len(raw))+raw)


class Broker:
    def __init__(self, config, web_uid):
        require(config is not None and config.approval_owner is not None and config.review_origin,
                'Browser approval must be explicitly configured.')
        self.config, self.web_uid, self.store = config, web_uid, Store(config)

    def dispatch(self, request, uid):
        require(uid == self.web_uid, 'Untrusted IPC peer.')
        require(isinstance(request, dict) and set(request) <= {'operation', 'draft_id', 'principal', 'fingerprint', 'decision'})
        principal = request.get('principal')
        require(principal == dict(zip(('issuer', 'subject'), self.config.approval_owner)), 'Approval owner mismatch.')
        key = request.get('draft_id')
        require(isinstance(key, str) and ID.fullmatch(key))
        item = self.store.get(key)  # Verifies owner/scope, expiry, manifest and exact MIME.
        operation = request.get('operation')
        if operation == 'review':
            return {'draft_id': key, 'manifest': item['manifest'], 'fingerprint': item['fingerprint'],
                    'state': item['state'], 'expires': item['expires']}
        require(operation == 'decide' and request.get('decision') in ('approved', 'rejected'))
        self.store.decide(key, request.get('fingerprint'), request['decision'],
                          {'method': 'browser-oidc-session', **principal})
        return {'state': request['decision']}

    def server(self, path):
        parent = path.parent.lstat()
        require(stat.S_ISDIR(parent.st_mode) and not path.parent.is_symlink()
                and parent.st_uid == os.geteuid() and stat.S_IMODE(parent.st_mode) == 0o750,
                'Broker runtime directory must be service-owned mode 750.')
        require(not path.exists() and not path.is_symlink(), 'Broker socket already exists; reconcile privately.')
        broker = self
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                try:
                    # Authenticate before reading any request or touching private state.
                    uid = peer_uid(self.request)
                    require(uid in getattr(broker, 'allowed_uids', (broker.web_uid,)), 'Untrusted IPC peer.')
                    data = receive(self.request)
                    require(len(canonical(data)) <= (32768 if hasattr(broker, 'allowed_uids') else 4096), 'IPC request limit exceeded.')
                    result = {'ok': True, 'result': broker.dispatch(data, uid)}
                except ReviewError as exc:
                    result = {'ok': False, 'error_code': exc.code}
                    logging.getLogger('inboxtether.review').warning('review_broker code=%s', exc.code)
                except Exception:
                    result = {'ok': False}  # Never include content, identity, token or exception text.
                try:
                    send(self.request, result)
                except Exception:
                    pass
        class Server(socketserver.UnixStreamServer):
            def handle_error(self, request, client_address):
                pass  # No request/exception logging.
        previous = os.umask(0o117)  # socket 660 from birth, parent not world-accessible.
        try:
            server = Server(str(path), Handler)
        finally:
            os.umask(previous)
        return server


class BrokerClient:
    def __init__(self, path):
        self.path = str(path)

    def call(self, operation, key, principal, **fields):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                # Remain below nginx's existing 30-second response timeout.
                connection.settimeout(25)
                connection.connect(self.path)
                send(connection, {'operation': operation, 'draft_id': key, 'principal': principal, **fields})
                response = receive(connection)
        except TimeoutError:
            raise ReviewError('broker_timeout') from None
        except Exception:
            raise ReviewError('broker_error') from None
        if not isinstance(response, dict) or response.get('ok') is not True:
            raise ReviewError(response.get('error_code', 'broker_error') if isinstance(response, dict) else 'broker_error')
        return response['result']


def main():
    try:
        config = Config.load()
        user = os.environ.get('INBOXTETHER_APPROVAL_WEB_USER', 'inboxtether-web')
        uid = pwd.getpwnam(user).pw_uid
        require(uid != os.geteuid(), 'Web and broker accounts must have distinct UIDs.')
        path = Path(os.environ.get('INBOXTETHER_APPROVAL_SOCKET', ''))
        require(path.is_absolute())
        with Broker(config, uid).server(path) as server:
            try:
                server.serve_forever()
            finally:
                path.unlink(missing_ok=True)
    except Exception:
        print('Approval broker unavailable. Check protected configuration and runtime permissions.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
