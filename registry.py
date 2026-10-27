"""Private file journal, one account lock; no new database or daemon.
Every prepared/claimed/uncertain/completed source remains reserved across batches.
Never erase a claim or infer failure from lack of an acknowledgement.
"""
import copy,fcntl,os,stat,json,re,math
from journal import Journal,require,digest

class RegistryFile(Journal):
    # Bounded durable account journal.
    # Keep an explicit 16 MB ceiling, atomic replacement and fsync implementation.
    def read(self):
        require(not (self.directory/'operation.next').exists() and not (self.directory/'operation.next').is_symlink(), 'Interrupted journal write; quarantine')
        if not self.path.exists():
            require(not self.path.is_symlink(), 'Journal symlink');return None
        fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd)
            require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600 and s.st_size<16*1024*1024, 'Unsafe registry file')
            with os.fdopen(fd,'rb',closefd=False) as stream:return json.load(stream)
        finally:os.close(fd)
    def write(self,value):
        from journal import canonical
        require(len(canonical(value))<16*1024*1024, 'Registry capacity exceeded; stop without mailbox action')
        super().write(value)

class Registry:
    def __init__(self,directory,identity):
        require(set(identity)=={'host','account','source_path','source_uidvalidity'}, 'Exact account/mailbox binding required')
        self.identity=copy.deepcopy(identity)
        self.journal=RegistryFile(directory)
        self.fd=None
    def __enter__(self):
        require(self.fd is None, 'Registry already locked')
        fd=os.open(self.journal.directory/'account.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            s=os.fstat(fd)
            require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o600, 'Unsafe registry lock')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.fd=fd
            self.read()
        except BaseException:
            self.fd=None;os.close(fd);raise
        return self
    def __exit__(self,*_):
        os.close(self.fd);self.fd=None
    def read(self):
        require(self.fd is not None, 'Account lock required')
        value=self.journal.read()
        if value is None:
            return {'schema':'inboxtether-public-batches-1','identity':self.identity,'batches':{},'external_claims':{}}
        require(value.get('schema')=='inboxtether-public-batches-1' and value.get('identity')==self.identity, 'Registry identity mismatch')
        require(isinstance(value.get('batches'),dict) and isinstance(value.get('external_claims'),dict), 'Invalid registry')
        require(not value.get('source_reconciliations') and not value['external_claims'], 'Legacy state cannot be imported into a fresh installation')
        return value
    def reserved(self,value,batch_id,uid):
        batch=value['batches'][batch_id]
        if all(e['uid']!=uid for e in batch['manifest']['moves']):return False
        # Any actual attempt always wins, regardless of an audit release.
        if any(a['uid']==uid for a in batch['attempts']):return True
        if batch['state'] in ('expired','rejected') and not batch['attempts']:return False
        return True
    def available(self,uid,batch_id):
        value=self.read()
        require(str(uid) not in value['external_claims'], 'Externally completed source')
        for key,batch in value['batches'].items():
            require(key==batch_id or not self.reserved(value,key,uid), 'Source reserved in another batch')
        batch=value['batches'].get(batch_id)
        require(batch is None or all(a['uid']!=uid for a in batch['attempts']), 'Source already claimed; reconcile, never retry')
    def batch(self,batch_id):
        require(isinstance(batch_id,str) and len(batch_id)==64 and all(c in '0123456789abcdef' for c in batch_id), 'Invalid batch ID')
        return BatchJournal(self,batch_id)

class BatchJournal:
    def __init__(self,registry,batch_id):self.registry,self.batch_id=registry,batch_id
    def read(self):return copy.deepcopy(self.registry.read()['batches'].get(self.batch_id))
    def write(self,batch):
        require(digest(batch['manifest'])==batch['fingerprint'], 'Batch fingerprint mismatch')
        value=self.registry.read()
        previous=value['batches'].get(self.batch_id)
        if previous is not None:
            require(previous['manifest']==batch['manifest'] and previous['fingerprint']==batch['fingerprint'], 'Immutable manifest changed')
            require(previous['state'] not in ('completed','uncertain','blocked','expired','rejected'), 'Consumed journal cannot be rewritten')
            require(previous['approval'] is None or previous['approval']==batch['approval'], 'Approval changed')
            require(len(batch['attempts'])>=len(previous['attempts']), 'Attempts removed')
            for before,after in zip(previous['attempts'],batch['attempts']):
                require(before['uid']==after['uid'] and before['at']==after['at'], 'Claim identity changed')
                require(before['state']!='verified' or before==after, 'Verified receipt changed')
                require(all(after.get(k)==v for k,v in before.items() if k!='state'), 'Receipt fields changed')
        for entry in batch['manifest']['moves']:
            require(entry['source_path']==self.registry.identity['source_path'] and entry['source_uidvalidity']==self.registry.identity['source_uidvalidity'], 'Batch registry source mismatch')
            require(str(entry['uid']) not in value['external_claims'], 'Externally completed source')
            for key,other in value['batches'].items():
                require(key==self.batch_id or not self.registry.reserved(value,key,entry['uid']), 'Duplicate source across batches')
        value['batches'][self.batch_id]=copy.deepcopy(batch)
        self.registry.journal.write(value)
