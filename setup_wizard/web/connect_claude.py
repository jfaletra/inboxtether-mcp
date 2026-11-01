"""One-time owner-run client connection. No mailbox credentials or authentication."""
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

ENTRY_JSON = "__INBOXTETHER_ENTRY_JSON__"


def config_path():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Claude/claude_desktop_config.json'
    if sys.platform == 'win32':
        return Path(os.environ['APPDATA']) / 'Claude/claude_desktop_config.json'
    return Path.home() / '.config/Claude/claude_desktop_config.json'


def validate(value):
    if type(value) is not dict or set(value) != {'mcpServers'} or set(value['mcpServers']) != {'inboxtether'}:
        raise ValueError('This connector contains an unexpected configuration.')
    server = value['mcpServers']['inboxtether']
    if type(server) is not dict or set(server) != {'command', 'args'}:
        raise ValueError('This connector must contain only a fixed stdio command and arguments.')
    if server == {'command': '/usr/local/bin/inboxtether', 'args': []}:
        return server
    args = server['args']
    if (server['command'] != 'ssh' or type(args) is not list or len(args) != 5
            or args[:3] != ['-T', '-o', 'BatchMode=yes'] or args[-1] != '/usr/local/bin/inboxtether'
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@+-]{0,254}', args[3])):
        raise ValueError('The SSH connection does not match the supported fixed launch command.')
    return server


def merge(path, server):
    """Owner-confirmed caller only. Preserve other keys and refuse conflicting entries."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError('The client configuration is a symlink. Nothing was changed.')
    old = None
    if path.exists():
        s = path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_size > 1048576 or (hasattr(os, 'getuid') and s.st_uid != os.getuid()):
            raise ValueError('The existing client configuration is not a safe owner file.')
        old = path.read_bytes()
        value = json.loads(old)
    else:
        value = {}
    if type(value) is not dict or type(value.get('mcpServers', {})) is not dict:
        raise ValueError('The existing client configuration needs owner review. Nothing was changed.')
    current = value.get('mcpServers', {}).get('inboxtether')
    if current is not None and current != server:
        raise ValueError('An InboxTether connection already exists with different settings. It was not overwritten.')
    if current == server:
        return 'The exact InboxTether connection already exists; nothing changed.'
    value.setdefault('mcpServers', {})['inboxtether'] = server
    path.parent.mkdir(parents=True, exist_ok=True)
    if old is not None:
        backup = path.with_name(path.name+'.before-inboxtether-'+str(time.time_ns()))
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(old); f.flush(); os.fsync(f.fileno())
    temporary = path.with_name('.inboxtether-client-'+str(time.time_ns()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        # Do not overwrite a concurrent change made by the client or another tool.
        if (path.is_symlink() or (old is None and path.exists())
                or (old is not None and (not path.exists() or path.read_bytes() != old))):
            raise ValueError('The client configuration changed during confirmation. Nothing was overwritten.')
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return 'InboxTether was added. Other client settings were preserved. Restart Claude Desktop.'


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Run this connector yourself in a desktop Terminal. No automatic client registration is performed.')
    server = validate(json.loads(ENTRY_JSON))
    print('This adds one InboxTether stdio connection to Claude Desktop. No mailbox password is included.')
    print('Command:', server['command']); print('Arguments:', json.dumps(server['args']))
    print('Existing different InboxTether entries are never replaced. Other connections stay unchanged.')
    if input('Type ADD-INBOXTETHER to confirm: ') != 'ADD-INBOXTETHER':
        raise ValueError('Connection not confirmed; nothing changed.')
    print(merge(config_path(), server))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not print exception text from JSON decoding of an existing client file.
        if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            raise SystemExit(str(error)) from None
        raise SystemExit('The connector stopped without displaying any existing client configuration.') from None
