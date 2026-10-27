"""Private atomic journal and canonical fingerprint utilities."""
import hashlib,json,os,stat
from pathlib import Path

class Refused(Exception):pass
def require(value,reason):
    if not value:raise Refused(reason)
def canonical(v):return json.dumps(v,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(v if isinstance(v,bytes) else canonical(v)).hexdigest()

class Journal:
    """Single protected operation file; atomic replacement + file/directory fsync."""
    def __init__(self,directory):
        self.directory=Path(directory)
        s=self.directory.lstat()
        require(stat.S_ISDIR(s.st_mode) and not self.directory.is_symlink() and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o700,'Unsafe journal directory')
        self.path=self.directory/'operation.json'
    def read(self):
        require(not (self.directory/'operation.next').exists() and not (self.directory/'operation.next').is_symlink(),'Interrupted journal write; quarantine, never reset')
        if not self.path.exists():
            require(not self.path.is_symlink(),'Journal symlink');return None
        fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd);require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 and s.st_size<1000000,'Unsafe journal file')
            return json.loads(os.read(fd,1000000))
        finally:os.close(fd)
    def write(self,value):
        temporary=self.directory/'operation.next'
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            data=canonical(value);written=0
            while written<len(data):
                count=os.write(fd,data[written:]);require(count>0,'Journal write made no progress');written+=count
            os.fsync(fd)
        finally:os.close(fd)
        os.replace(temporary,self.path)
        fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

