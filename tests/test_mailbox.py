import copy
import journal as u
class Message:
    def __init__(self,uid,flags=None):self.uid=uid;self.flags=['\\Seen'] if flags is None else flags
    def evidence(self):return {'uid':self.uid,'sha256':u.digest(('synthetic-'+str(self.uid)).encode()),'size':80,'flags':self.flags,'internaldate':'01-Jan-2026 00:00:00 +0000','identity_kind':'raw-v1'}
class Policy:
    veto=False
    def revalidate(self,message,evidence):return {**evidence,'customer':self.veto,'move_eligible':not self.veto}
class Mailbox:
    def __init__(self):
        self.source={};self.dest={};self.moves=[];self.failure=None;self.uv=123;self.pins={};self.journal=None;self.events=[]
    def inbox_identity(self):return self.uv,1000
    def folder(self,name):return self.pins[name]
    def fetch(self,name,uv,uid):
        self.events.append(('fetch',name,uid))
        return self.source.get(uid) if name=='INBOX' else self.dest.get((name,uid))
    def raw_digest(self,name,uv,uid,size):return u.digest(('raw-'+str(uid if name=='INBOX' else uid-1000)).encode()) if self.failure!='raw-destination' or name=='INBOX' else '0'*64
    def move(self,uv,uid,category,dest_uv,*,evidence,expires_at,on_prepared):
        self.events.append(('move',uid));self.moves.append(uid)
        assert self.journal.read()['attempts'][-1]['state']=='claimed'
        on_prepared(self.raw_digest('INBOX',uv,uid,80))
        if self.failure=='before-ack':raise OSError('synthetic disconnect')
        if self.failure=='interrupt':raise KeyboardInterrupt()
        dest=Message(uid+1000)
        # Stable content evidence, only UID changes across MOVE.
        e={**self.source[uid].evidence(),'uid':uid+1000}
        if self.failure=='dest-flags':e['flags']=[]
        dest.evidence=lambda:copy.deepcopy(e)
        self.dest[category,uid+1000]=dest
        if self.failure!='source-remains':del self.source[uid]
        return (0 if self.failure=='mapping' else dest_uv),uid+1000

