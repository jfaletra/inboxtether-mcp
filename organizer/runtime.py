"""Administrator-owned, bounded configuration loading."""
import os,stat,json
from pathlib import Path
from .model import require

def load_protected_json(path):
    path = Path(path)
    require(path.is_absolute(), 'Absolute protected configuration path required.')
    for ancestor in (path.parent, *path.parents):
        info = ancestor.lstat()
        require(not ancestor.is_symlink() and info.st_uid == 0 and not info.st_mode & 0o022,
                'Configuration ancestry must be administrator-controlled.')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o644,
                'Configuration must be administrator-owned mode 644; contains references, not secrets.')
        raw = os.read(fd, 131073)
        require(len(raw) <= 131072, 'Configuration exceeds limit.')
        values = json.loads(raw)
    finally:
        os.close(fd)
    return values

