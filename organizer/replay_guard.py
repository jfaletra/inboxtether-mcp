"""Independent rollback witness. Never restore it together with an older state snapshot."""
from contextlib import contextmanager
import fcntl,hashlib,json,os,secrets,stat
from pathlib import Path
from .model import canonical,require

class ReplayGuard:
 def __init__(self,directory,state,identity):
  self.directory=Path(directory);self.state=Path(state);self.identity=hashlib.sha256(identity.encode()).hexdigest()
  require(self.directory.resolve()==self.directory and self.state.resolve()==self.state, 'Canonical independent state paths required.')
  require(self.directory.is_absolute() and self.directory!=self.state and self.state not in self.directory.parents and self.directory not in self.state.parents,'Independent witness directory required.')
  self.check_directory()
 def check_directory(self):
  s=self.directory.lstat()
  require(not self.directory.is_symlink() and stat.S_ISDIR(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o700,'Private witness directory required.')
 def read(self):
  p=self.directory/'witness.json'
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  try:
   s=os.fstat(fd);require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 and s.st_nlink==1,'Unsafe rollback witness.')
   raw=os.read(fd,4097);require(len(raw)<=4096,'Witness too large.');v=json.loads(raw)
   require(set(v)=={'version','identity','token'} and v['version']==1 and v['identity']==self.identity and type(v['token']) is str and len(v['token'])==64 and all(c in '0123456789abcdef' for c in v['token']),'Invalid rollback witness.')
   return v['token']
  finally:os.close(fd)
 def publish(self,token):
  name=self.directory/('.pending-'+secrets.token_hex(16))
  fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  try:
   with os.fdopen(fd,'w') as f:
    f.write(canonical({'version':1,'identity':self.identity,'token':token}));f.flush();os.fsync(f.fileno())
   os.replace(name,self.directory/'witness.json')
   fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(fd)
   finally:os.close(fd)
  finally:
   if name.exists():name.unlink()
 @contextmanager
 def lock(self,path):
  self.check_directory()
  fd=os.open(self.directory/'witness.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
  try:
   s=os.fstat(fd);require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 and s.st_nlink==1,'Unsafe witness lock.')
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:require(False,'State/witness session busy.')
   has_db=path.exists();has_witness=(self.directory/'witness.json').exists()
   require(has_db==has_witness,'Missing state or independent witness; owner recovery required.')
   # A leftover pending write indicates an interrupted checkpoint, never auto-heal.
   require(not list(self.directory.glob('.pending-*')),'Interrupted witness update; owner recovery required.')
   yield self.read() if has_witness else None
  finally:os.close(fd)
 def verify(self,db,token):
  if token is None:
   require(not db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone(),'Existing ledger cannot enroll a new witness.')
   db.execute('CREATE TABLE replay_guard (id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL)')
  else:
   row=db.execute('SELECT token FROM replay_guard WHERE id=1').fetchone()
   require(row is not None and row[0]==token,'Stale or split state restoration; execution quarantined.')
 def checkpoint(self,db):
  token=secrets.token_hex(32)
  # Witness first: a crash before ledger commit causes a mismatch, never old-state acceptance.
  self.publish(token)
  db.execute('INSERT INTO replay_guard VALUES(1,?) ON CONFLICT(id) DO UPDATE SET token=excluded.token',(token,))
  db.commit()

def snapshot(store,destination):
 """Offline/operator snapshot only. It never copies or rewinds the independent witness."""
 import sqlite3
 destination=Path(destination)
 require(store.guard is not None,'Independent replay witness required.')
 require(destination.is_absolute() and destination.parent.is_dir() and not destination.exists(),'New snapshot path required.')
 with store.lock(),store.db() as db:
  fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
  target=sqlite3.connect(destination)
  try:
   db.backup(target)
   require(target.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Snapshot integrity failure.')
  finally:target.close()
  fd=os.open(destination,os.O_RDONLY|os.O_NOFOLLOW)
  try:os.fsync(fd)
  finally:os.close(fd)
  fd=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
 # Store exit advances witness: snapshots are diagnostic/quarantined, never auto-resumable.
 return {'file':destination.name,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'restore_mode':'quarantine-only','approvals_reusable':False,'witness_included':False}
