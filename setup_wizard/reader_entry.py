"""Fixed, isolated stdio launcher; no client arguments or password environment."""
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path('/opt/inboxtether')
path = Path('/etc/inboxtether/reader.json')
for parent in path.parents:
    s = parent.lstat()
    if parent.is_symlink() or s.st_uid != 0 or s.st_mode & 0o022:
        raise SystemExit('Reader configuration ancestry is unsafe.')
s = path.lstat()
if path.is_symlink() or s.st_uid != 0 or stat.S_IMODE(s.st_mode) != 0o644:
    raise SystemExit('Reader configuration is unsafe.')
values = json.loads(path.read_text())
allowed = {'INBOXTETHER_IMAP_HOST', 'INBOXTETHER_IMAP_PORT', 'INBOXTETHER_ACCOUNT',
           'INBOXTETHER_LOGIN_ACCOUNT', 'INBOXTETHER_PASSWORD_FILE', 'INBOXTETHER_DRAFT_ASSISTANT',
           'INBOXTETHER_DRAFT_MODE', 'INBOXTETHER_BASIC_ACK', 'INBOXTETHER_DRAFTS_FOLDER',
           'INBOXTETHER_DRAFT_STATE_DIR', 'INBOXTETHER_MOVES', 'INBOXTETHER_MOVE_SOCKET'}
if not set(values) <= allowed or not all(type(v) is str and '\x00' not in v for v in values.values()):
    raise SystemExit('Reader configuration fields are unsafe.')
os.chdir(ROOT)
os.environ.clear()
os.environ.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', HOME='/nonexistent', **values)
sys.path.insert(0, str(ROOT))
from server import create_server
create_server().run(transport='stdio')
