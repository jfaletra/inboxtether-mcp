"""Root systemd post-start helper: ACLs only on two fixed new approval sockets."""
import os,stat,subprocess,time,pwd,errno
import socket as unix_socket
from pathlib import Path
from organizer.runtime import load_protected_json
from journal import require

TARGETS={'broker':('/run/inboxtether-approval-broker','inboxtether-organizer','moves.sock',('reader_uid','web_uid')),
         'web':('/run/inboxtether-approval-web','inboxtether-web','web.sock',('proxy_uid',))}
def socket_ready(path):
    with unix_socket.socket(unix_socket.AF_UNIX,unix_socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        try:probe.connect(str(path))
        except OSError as error:
            require(error.errno in (errno.ENOENT,errno.ECONNREFUSED),'Socket readiness probe failed')
            return False
    return True

def grant(role,settings,*,runner=subprocess.run,clock=time.monotonic,sleep=time.sleep,base=None):
    require(role in TARGETS,'Unknown socket role');directory,owner,name,fields=TARGETS[role]
    owner=pwd.getpwnam(owner).pw_uid
    uids=[settings[field] for field in fields]
    require(len(set(uids))==len(uids) and all(type(uid) is int and 0<uid<2**31 and uid!=owner for uid in uids),'Distinct explicit client UIDs required')
    if role=='broker':require(settings['web_uid']==pwd.getpwnam('inboxtether-web').pw_uid,'Configured web identity mismatch')
    directory=Path(directory) if base is None else Path(base);socket=directory/name
    deadline=clock()+20
    while True:
        if socket.exists() or socket.is_symlink():
            try:
                a=directory.lstat();b=socket.lstat()
                require(not directory.is_symlink() and stat.S_ISDIR(a.st_mode) and a.st_uid==owner and stat.S_IMODE(a.st_mode)==0o750,'Unexpected runtime directory')
                require(not socket.is_symlink() and stat.S_ISSOCK(b.st_mode) and b.st_uid==owner and stat.S_IMODE(b.st_mode)==0o660,'Unexpected socket')
                if socket_ready(socket):
                    current=socket.lstat()
                    if (current.st_dev,current.st_ino)==(b.st_dev,b.st_ino):break
            except FileNotFoundError:
                pass
        require(clock()<deadline,'Socket did not become ready')
        sleep(.05)
    for uid in uids:
        runner(['/usr/bin/setfacl','-m',f'u:{uid}:--x',str(directory)],check=True)
        runner(['/usr/bin/setfacl','-m',f'u:{uid}:rw-',str(socket)],check=True)

def main():
    require(os.geteuid()==0,'Root-only post-start operation')
    values=load_protected_json('/etc/inboxtether-approval/socket-access.json')
    require(set(values)=={'reader_uid','web_uid','proxy_uid'},'Exact socket clients required')
    grant(__import__('sys').argv[1],values)
if __name__=='__main__':main()
