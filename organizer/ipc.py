"""Peer-authenticated local IPC. Client has no approval, state or IMAP access."""
import ctypes
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import time

from .model import MAX_PAGE, OrganizerError, canonical, integer, require

MAX_FRAME = 2_097_152
MAX_REQUEST = 16_384


def peer_uid(connection):
    if hasattr(socket, 'SO_PEERCRED'):
        return struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    getpeer = ctypes.CDLL(None, use_errno=True).getpeereid
    require(getpeer(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0, 'Peer authentication failed.')
    return uid.value


def receive(connection, maximum, deadline):
    def exact(size):
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'IPC deadline exceeded.')
            connection.settimeout(remaining)
            data = connection.recv(size - len(result))
            require(bool(data), 'Incomplete IPC frame.')
            result.extend(data)
        return bytes(result)
    length = struct.unpack('!I', exact(4))[0]
    require(0 < length <= maximum, 'IPC frame exceeds limit.')
    # Reject duplicate keys and non-finite numbers rather than interpreting ambiguous requests.
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'Duplicate IPC field.')
            result[key] = value
        return result
    return json.loads(exact(length), object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False, 'Non-finite IPC number.'))


def send(connection, data, deadline):
    raw = canonical(data).encode()
    require(len(raw) <= MAX_FRAME, 'IPC response exceeds limit.')
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'IPC deadline exceeded.')
    connection.settimeout(remaining)
    connection.sendall(struct.pack('!I', len(raw)) + raw)


class Broker:
    def __init__(self, organizer, client_uid):
        integer(client_uid, 1)
        require(client_uid != os.geteuid() and os.geteuid() != 0, 'Organizer and MCP must use distinct non-root identities.')
        self.organizer, self.client_uid = organizer, client_uid

    def dispatch(self, request, uid):
        require(uid == self.client_uid, 'Untrusted Organizer peer.')
        require(isinstance(request, dict) and set(request) == {'operation', 'arguments'}, 'Invalid IPC request.')
        op, args = request['operation'], request['arguments']
        require(isinstance(args, dict), 'Invalid IPC arguments.')
        fields = {
            'start_organization': (set(), self.organizer.start_run),
            'classify_organization_page': ({'run_id', 'limit', 'proposal'}, self.organizer.classify_page),
            'organization_page': ({'run_id', 'offset', 'limit'}, self.organizer.run_page),
            'prepare_organization_batch': ({'run_id', 'keep_uids'}, self.organizer.prepare_batch),
            'execute_organization_batch': ({'batch_id', 'uid'}, self.organizer.execute),
            'organization_status': ({'batch_id'}, self.organizer.batch_status),
        }
        require(op in fields, 'Organizer operation prohibited.')
        allowed, fn = fields[op]
        require(set(args) <= allowed, 'Unsupported Organizer arguments.')
        # Explicit short chunks keep request execution below tunnel deadlines in normal operation.
        if op == 'classify_organization_page':
            integer(args.get('limit', 1), 1, 1)
            args = {**args, 'limit': 1}
        return fn(**args)

    def server(self, socket_path):
        path = Path(socket_path)
        info = path.parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not path.parent.is_symlink()
                and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o750,
                'Unsafe Organizer socket directory.')
        require(not path.exists() and not path.is_symlink(), 'Existing Organizer socket requires owner reconciliation.')
        broker = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                deadline = time.monotonic() + 90
                try:
                    # Reject wrong UID BEFORE reading a request or opening private state.
                    uid = peer_uid(self.request)
                    require(uid == broker.client_uid, 'Untrusted Organizer peer.')
                    request = receive(self.request, MAX_REQUEST, min(deadline, time.monotonic() + 3))
                    response = {'ok': True, 'result': broker.dispatch(request, uid)}
                except Exception:
                    response = {'ok': False, 'error': 'Organizer request refused. Inspect protected status; never blindly retry moves.'}
                try:
                    send(self.request, response, deadline)
                except Exception:
                    pass  # Never print raw frames, mail, tokens or exceptions.

        class Server(socketserver.UnixStreamServer):
            def handle_error(self, request, client_address):
                pass
        previous = os.umask(0o117)
        try:
            return Server(str(path), Handler)
        finally:
            os.umask(previous)


class Client:
    def __init__(self, socket_path, backend_uid):
        self.path, self.backend_uid = Path(socket_path), integer(backend_uid, 1)
        require(backend_uid != os.geteuid(), 'Organizer backend must have a distinct identity.')

    def call(self, operation, **arguments):
        try:
            info, parent = self.path.lstat(), self.path.parent.lstat()
            require(stat.S_ISSOCK(info.st_mode) and info.st_uid == self.backend_uid
                    and stat.S_IMODE(info.st_mode) == 0o660 and not self.path.is_symlink(), 'Unsafe Organizer socket.')
            require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == self.backend_uid
                    and stat.S_IMODE(parent.st_mode) == 0o750 and not self.path.parent.is_symlink(), 'Unsafe socket parent.')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                deadline = time.monotonic() + 95
                connection.settimeout(3)
                connection.connect(str(self.path))
                require(peer_uid(connection) == self.backend_uid, 'Wrong Organizer backend identity.')
                send(connection, {'operation': operation, 'arguments': arguments}, deadline)
                response = receive(connection, MAX_FRAME, deadline)
            require(isinstance(response, dict) and response.get('ok') is True, 'Organizer request refused; inspect status before retry.')
            return response['result']
        except Exception:
            raise OrganizerError('Organizer unavailable or request refused. Check status before retrying a move.') from None
