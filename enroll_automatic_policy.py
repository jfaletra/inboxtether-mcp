"""One-time owner-operated configuration change; never called through MCP."""
import argparse,json,os,secrets,stat,sys
from pathlib import Path
from automatic_filing import FOLDERS
from journal import digest,require
from organizer.runtime import load_protected_json

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--enable',action='store_true');g.add_argument('--disable',action='store_true');args=parser.parse_args()
    require(os.geteuid()==0 and sys.stdin.isatty() and sys.stdout.isatty(),'Owner-operated administrator Terminal required')
    path=Path(args.config);before=path.read_bytes();s=path.lstat();require(not path.is_symlink() and stat.S_ISREG(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,'Protected root configuration required')
    spec=load_protected_json(str(path));proposed={'enabled':args.enable,'revision':secrets.token_hex(32),'folders':list(FOLDERS)}
    fingerprint=digest({'owner':spec['owner'],'host':spec['host'],'account':spec['account'],'mailboxes':spec['mailboxes'],'automatic_filing_policy':proposed})
    print(json.dumps({'enabled':args.enable,'folders':list(FOLDERS),'Review':'keep in Inbox and report','customer_and_uncertainty':'keep in Inbox','authorization':'persistent owner policy, not per-batch human approval','execution_enabled_unchanged':spec['execution_enabled'],'fingerprint':fingerprint},indent=2))
    action='ENABLE-AUTOMATIC-FILING' if args.enable else 'REVOKE-AUTOMATIC-FILING'
    require(input('Type '+action+' '+fingerprint+'\n')==action+' '+fingerprint,'Owner confirmation did not match')
    require(path.read_bytes()==before,'Configuration changed during enrollment')
    backup=path.with_name(path.name+'.before-automatic-'+proposed['revision']);fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(before);f.flush();os.fsync(f.fileno())
    spec['automatic_filing_policy']=proposed;temp=path.with_name('.'+path.name+'.automatic-new');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,stat.S_IMODE(s.st_mode))
    with os.fdopen(fd,'w') as f:json.dump(spec,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.chown(temp,s.st_uid,s.st_gid);os.replace(temp,path);fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    print('Owner policy stored. No services started, mailbox access, consent or moves performed.')
if __name__=='__main__':main()
