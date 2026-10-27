"""Owner-operated, hidden-input enrollment. Never reads Mailcow credentials."""
import argparse,getpass,hmac,json,os,re,secrets,stat,sys
from pathlib import Path
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from journal import require,canonical

def make_record(owner_id,username,password):
    require(re.fullmatch('[0-9a-f]{32}',owner_id) and re.fullmatch('[A-Za-z0-9_.@+-]{1,80}',username),'Invalid owner identity')
    require(type(password) is str and len(password)>=16 and len(password.encode('utf-8'))<=1024,'Use a unique passphrase of at least16 characters')
    encoded=Argon2id(salt=os.urandom(16),length=32,iterations=2,lanes=1,memory_cost=19456).derive_phc_encoded(password.encode('utf-8'))
    return {'owner_id':owner_id,'username':username,'password_hash':encoded}

def write_record(path,record,uid,replace=False):
    path=Path(path);require(path.is_absolute(),'Absolute owner file path required')
    for p in path.parents:
        s=p.lstat();require(not p.is_symlink() and s.st_uid in (0,os.geteuid()) and not s.st_mode&0o022,'Unsafe enrollment directory')
    if path.exists() or path.is_symlink():
        require(replace and not path.is_symlink(),'Owner already enrolled; explicit replacement required')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            s=os.fstat(fd);require(stat.S_ISREG(s.st_mode) and s.st_uid==uid and stat.S_IMODE(s.st_mode)==0o600 and s.st_nlink==1 and s.st_size<=8192,'Unsafe existing owner file')
            old=json.loads(os.read(fd,8193));require(old['owner_id']==record['owner_id'],'Cannot replace the enrolled owner identity')
        finally:os.close(fd)
    temporary=path.with_name('.owner-'+secrets.token_hex(16))
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(canonical(record));stream.flush();os.fchmod(stream.fileno(),0o600)
            if uid!=os.geteuid():os.fchown(stream.fileno(),uid,-1)
            os.fsync(stream.fileno())
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary.exists():temporary.unlink()

def main():
    parser=argparse.ArgumentParser(description='One-time dedicated owner password enrollment; password is hidden')
    parser.add_argument('--file',required=True);parser.add_argument('--owner-id',required=True);parser.add_argument('--username',required=True);parser.add_argument('--web-uid',required=True,type=int);parser.add_argument('--replace',action='store_true')
    args=parser.parse_args()
    require(sys.stdin.isatty() and sys.stdout.isatty(),'Owner terminal required for one-time enrollment only')
    password=getpass.getpass('New dedicated InboxTether owner password (hidden): ')
    confirmation=getpass.getpass('Confirm password (hidden): ')
    require(hmac.compare_digest(password.encode('utf-8'),confirmation.encode('utf-8')),'Passwords do not match')
    write_record(args.file,make_record(args.owner_id,args.username,password),args.web_uid,args.replace)
    print('Dedicated owner hash stored privately. No Mailcow credentials accessed; no services started.')
if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Enrollment refused. No password or hash displayed.') from None
