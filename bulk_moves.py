"""Bulk manifests on the existing journal/tool; no worker, database or approval bypass."""
import copy,math,secrets
from journal import require,digest,canonical,Refused
from organization_errors import OrganizationError,translate
from candidate_discovery import Eligibility
from batch_moves import BatchOperation,CATEGORIES,EXECUTION_SECONDS_PER_MESSAGE,EXECUTION_FINAL_MARGIN_SECONDS
MAX_BULK=200
CHUNK_SIZE=10
PREPARATION_SECONDS=7200
REVIEW_SECONDS=86400
VALID_REVIEW_SECONDS=(1800,REVIEW_SECONDS)
EXECUTION_SECONDS=21600
SCHEMA='inboxtether-owner-bulk-1'

def is_bulk(manifest):return manifest.get('schema')==SCHEMA

def summary(manifest):
    groups={}
    for e in manifest['moves']:
        g=groups.setdefault(e['category'],{'count':0,'uids':[]});g['count']+=1;g['uids'].append(e['uid'])
    return groups

def validate_preparations(value,identity):
    records=value.get('bulk_preparations',{})
    require(type(records) is dict and len(records)<=500,'Bulk preparation capacity/shape invalid')
    active=0
    for key,r in records.items():
        require(type(key) is str and len(key)==64 and all(x in '0123456789abcdef' for x in key),'Invalid preparation ID')
        require(type(r) is dict and set(r)=={'plan','fingerprint','state','entries'},'Invalid preparation record')
        p=r['plan'];require(type(p) is dict and set(p)=={'identity','scope','decision_hashes','baseline','review_binding','workflow_binding','run_id','run_fingerprint','created','expires'},'Invalid preparation plan')
        require(r['fingerprint']==digest(p) and p['identity']==identity,'Preparation binding differs')
        scope=p['scope'];require(type(scope) is list and 1<=len(scope)<=MAX_BULK and all(type(x) is list and len(x)==2 and type(x[0]) is int and 0<x[0]<=4294967295 and x[1] in CATEGORIES for x in scope),'Invalid bulk scope')
        require(len({u for u,c in scope})==len(scope) and set(p['decision_hashes'])=={str(u) for u,c in scope},'Duplicate/missing bulk decision')
        require(all(type(p[k]) in (int,float) and math.isfinite(p[k]) for k in ('created','expires')) and p['expires']-p['created']==PREPARATION_SECONDS,'Invalid preparation lifetime')
        require(r['state'] in ('preparing','blocked','ready','cancelled') and type(r['entries']) is list and len(r['entries'])<=len(scope),'Invalid preparation progress')
        if r['state'] in ('preparing','blocked'):active+=1
        for e,(u,c) in zip(r['entries'],scope):
            require(e['uid']==u and e['category']==c and e['source_path']==identity['source_path'] and e['source_uidvalidity']==identity['source_uidvalidity'] and e['decision_sha256']==p['decision_hashes'][str(u)],'Preparation entry/source differs')
        if r['state']=='ready':
            b=value['batches'].get(key);require(len(r['entries'])==len(scope) and b and is_bulk(b['manifest']) and b['manifest']['moves']==r['entries'] and digest(b['manifest'])==b['fingerprint'],'Ready preparation manifest differs')
        else:require(key not in value['batches'],'Unready preparation has executable batch')
    require(active<=1,'Another bulk preparation is active')

def preparation_reserved(value,uid,batch_id):
    return any(key!=batch_id and r['state'] in ('preparing','blocked') and any(u==uid for u,c in r['plan']['scope']) for key,r in value.get('bulk_preparations',{}).items())

def preparation_status(service,key):
    v=service.load();r=v.get('bulk_preparations',{}).get(key);require(r is not None,'Unknown bulk preparation')
    return {'batch_id':key,'state':r['state'],'preparation_fingerprint':r['fingerprint'],'prepared_messages':len(r['entries']),'total_messages':len(r['plan']['scope']),'approval_allowed':False,'expires':r['plan']['expires'],'next_action':'prepare with batch_id only' if r['state']=='preparing' else 'stop; no automatic retry'}

def begin(service,uids):
    require(type(uids) is list and 1<=len(uids)<=MAX_BULK and all(type(u) is int and 0<u<=4294967295 for u in uids) and len(set(uids))==len(uids),'Exact 1..200 distinct UIDs required')
    value=service.load();initial=Eligibility(service,value)
    for u in uids:initial.check(u,allow_expired=True)
    value=service.registry.retire_expired(service.clock())
    for existing,p in value.get('bulk_preparations',{}).items():
        if p['state'] in ('preparing','blocked'):raise OrganizationError('preparation_conflict','preparation',preparation_id=existing)
    value=service.load();index=Eligibility(service,value);scope=[];hashes={};key=secrets.token_hex(32)
    for u in uids:
        index.check(u)
        d=value['workflow']['decisions'].get(str(u),{})
        require(d.get('category') in service.pins and d.get('customer') is False and d.get('move_eligible') is True and d.get('classification_origin')=='client','Customer/Keep/unclassified source cannot enter bulk manifest')
        service.registry.available(u,key);scope.append([u,d['category']]);hashes[str(u)]=digest(d)
    require(key not in value['batches'] and key not in value.get('bulk_preparations',{}),'Preparation ID collision; stop')
    now=service.clock();plan={'identity':copy.deepcopy(service.registry.identity),'scope':scope,'decision_hashes':hashes,'baseline':copy.deepcopy(service.baseline),'review_binding':service.review_binding(),'workflow_binding':service.binding,'run_id':service.seed['run_id'],'run_fingerprint':service.seed['fingerprint'],'created':now,'expires':now+PREPARATION_SECONDS}
    value=service.load();records=value.setdefault('bulk_preparations',{});require(len(records)<500,'Preparation history full; stop without pruning');records[key]={'plan':plan,'fingerprint':digest(plan),'state':'preparing','entries':[]}
    validate_preparations(value,service.registry.identity);service.save(value)
    return advance(service,key)

def advance(service,key):
    value=service.load();r=value.get('bulk_preparations',{}).get(key)
    if not r or r['state']!='preparing':raise OrganizationError('preparation_unknown','preparation',preparation_id=key)
    p=r['plan']
    if service.clock()>=p['expires']:raise OrganizationError('preparation_expired','preparation',preparation_id=key)
    if p['baseline']!=service.baseline or p['workflow_binding']!=service.binding:raise OrganizationError('baseline_changed','preparation',preparation_id=key)
    if p['review_binding']!=service.review_binding():raise OrganizationError('preference_changed','preparation',preparation_id=key)
    index=Eligibility(service,value)
    for u,c in p['scope']:
        if digest(value['workflow']['decisions'].get(str(u)))!=p['decision_hashes'][str(u)]:raise OrganizationError('classification_changed','preparation',uid=u,preparation_id=key)
        index.check(u,own_preparation=key)
    op=service.operation(key,[(u,c) for u,c in p['scope']]);start=len(r['entries']);chunk=p['scope'][start:start+CHUNK_SIZE]
    entries=[]
    for u,c in chunk:
        try:entries.append(op.snapshot(u,c))
        except Exception as exc:
            r['state']='blocked';service.save(value)
            raise translate(exc,'source_validation',uid=u,preparation_id=key) from None
        except BaseException:
            r['state']='blocked';service.save(value);raise
    r['entries'].extend(entries)
    if len(r['entries'])<len(p['scope']):
        validate_preparations(value,service.registry.identity);service.save(value);return preparation_status(service,key)
    return publish(service,value,key,r)

def publish(service,value,key,r):
    p=r['plan']
    now=service.clock();manifest={'schema':SCHEMA,'run_id':p['run_id'],'run_fingerprint':p['run_fingerprint'],'baseline':p['baseline'],'review_binding':p['review_binding'],'moves':r['entries'],'created':now,'expires':now+REVIEW_SECONDS,'execution_deadline':now+REVIEW_SECONDS+EXECUTION_SECONDS,'chunk_size':CHUNK_SIZE}
    require(len(canonical(manifest))<=700000,'Bulk manifest exceeds existing IPC budget; cancel preparation')
    batch={'manifest':manifest,'fingerprint':digest(manifest),'state':'prepared','approval':None,'attempts':[]}
    # One atomic write publishes both the finished preparation and approvable batch.
    r['state']='ready';value['batches'][key]=batch;validate_preparations(value,service.registry.identity);service.save(value)
    return service.status(key)

def cancel_preparation(service,key,fp):
    service.chat_enabled();value=service.load();r=value.get('bulk_preparations',{}).get(key)
    require(r and r['state'] in ('preparing','blocked') and r['fingerprint']==fp and key not in value['batches'],'Exact unused preparation required')
    r['state']='cancelled';service.save(value);return {'batch_id':key,'state':'cancelled','moves':0}

def validate_progress(value):
    m=value['manifest'];require(is_bulk(m) and 1<=len(m['moves'])<=MAX_BULK and m['chunk_size']==CHUNK_SIZE and m['expires']-m['created'] in VALID_REVIEW_SECONDS and m['execution_deadline']-m['expires']==EXECUTION_SECONDS,'Invalid fixed bulk deadlines/scope')
    attempts=value['attempts'];require(len(attempts)<=len(m['moves']),'Excess bulk attempts')
    for a,e in zip(attempts,m['moves']):
        require(a['uid']==e['uid'],'Bulk attempt order differs')
        if a['state']=='verified':require(a['mapping']['category']==e['category'] and a['mapping']['uidvalidity']==e['destination_uidvalidity'] and a['raw_sha256']==e['raw_sha256'] and a['flags']==e['evidence']['flags'],'Verified bulk receipt differs')
    run=value.get('bulk_execution')
    if run is not None:
        require(set(run)=={'started','deadline'} and m['created']<=run['started']<m['expires'] and run['deadline']==m['execution_deadline'],'Bulk execution window changed')
    if value['state'] in ('paused','completed'):require(run is not None and all(a['state']=='verified' for a in attempts),'Uncertain prefix cannot continue')
    if value['state']=='paused':require(0<len(attempts)<len(m['moves']) and len(attempts)%CHUNK_SIZE==0,'Unverified/incomplete chunk cannot continue')
    if value['state']=='completed':require(len(attempts)==len(m['moves']),'Incomplete bulk completion')

def enrich(value):
    m=value['manifest'];validate_progress(value);verified=sum(a['state']=='verified' for a in value['attempts'])
    return {'summary_by_destination':summary(m),'total_messages':len(m['moves']),'verified_messages':verified,'remaining_messages':len(m['moves'])-verified,'chunk_size':CHUNK_SIZE,'approval_start_deadline':m['expires'],'execution_deadline':m['execution_deadline'],'can_continue':value['state']=='paused'}

class BulkOperation(BatchOperation):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs,scope_limit=MAX_BULK)
    def execute_consented(self,owner,approval_method):
        require(approval_method in ('browser-password-session','browser-oidc-session','client-session-consent'),'Unsupported bulk consent method')
        value=self.journal.read();require(value is not None,'Unknown bulk manifest');m=value['manifest'];a=value['approval'];validate_progress(value)
        require(value['state'] in ('approved','paused') and (not value['attempts'] if value['state']=='approved' else all(x['state']=='verified' for x in value['attempts'])),'Consumed/uncertain batch; never retry')
        require(a is not None and a=={'method':approval_method,'principal':owner,'fingerprint':value['fingerprint'],'at':a.get('at')},'Exact bulk consent required')
        require(digest(m)==value['fingerprint'] and m['run_id']==self.run_id and m['run_fingerprint']==self.run_fingerprint and m['baseline']==self.baseline,'Bulk manifest binding changed')
        require([(e['uid'],e['category']) for e in m['moves']]==list(self.scope),'Bulk source scope differs')
        require(m['created']<=a['at']<m['expires'],'Bulk consent expired')
        initial=value['state']=='approved';start=len(value['attempts']);deadline=m['execution_deadline'];remaining=len(m['moves'])-start
        if initial:require(self.clock()<m['expires'] and 'bulk_execution' not in value,'Approval start deadline expired')
        else:require(value['bulk_execution']['deadline']==deadline,'Execution window differs')
        budget={'expires':deadline};self.require_execution_window(budget,remaining)
        chunk=m['moves'][start:start+CHUNK_SIZE]
        # Validate only this bounded chunk; each actual MOVE is checked again.
        require([self.snapshot(e['uid'],e['category']) for e in chunk]==chunk,'Bulk chunk changed; no moves authorized')
        self.require_execution_window(budget,remaining)
        if initial:
            require(self.clock()<m['expires'],'Approval expired during initial chunk validation')
            value['bulk_execution']={'started':self.clock(),'deadline':deadline}
        for index,entry in enumerate(chunk,start):
            uid,cat=entry['uid'],entry['category'];remaining=len(m['moves'])-index
            try:
                self.require_execution_window(budget,remaining)
                require(self.snapshot(uid,cat)==entry,'Bulk source changed before move')
                self.require_execution_window(budget,remaining)
            except Exception:
                value['state']='blocked';self.journal.write(value);raise Refused('Bulk pre-move check failed; stop without retry') from None
            attempt={'uid':uid,'state':'claimed','at':self.clock()};value['attempts'].append(attempt);value['state']='executing';self.journal.write(value)
            try:
                def prepared(raw):
                    require(raw==entry['raw_sha256'],'Bulk raw source changed at MOVE boundary');self.require_execution_window(budget,remaining);self.unchanged()
                uv,dest=self.mailbox.move(self.uv,uid,cat,self.pins[cat],evidence=self.decisions[uid],expires_at=deadline,on_prepared=prepared)
                require(type(dest) is int and 0<dest<=4294967295 and uv==self.pins[cat],'Invalid bulk destination mapping')
                attempt['mapping']={'category':cat,'uidvalidity':uv,'uid':dest};self.journal.write(value)
                after=self.mailbox.fetch(cat,uv,dest)
                require(after is not None and after.evidence()=={**entry['evidence'],'uid':dest},'Bulk destination content/flags/date mismatch')
                require(self.mailbox.raw_digest(cat,uv,dest,entry['evidence']['size'])==entry['raw_sha256'],'Bulk destination bytes mismatch')
                require(self.mailbox.fetch('INBOX',self.uv,uid) is None,'Bulk source still present')
                self.identities();self.unchanged();attempt.update(state='verified',raw_sha256=entry['raw_sha256'],flags=entry['evidence']['flags'],verified_at=self.clock());self.journal.write(value)
            except BaseException:
                attempt['state']='uncertain';value['state']='uncertain';self.journal.write(value);raise Refused('Uncertain bulk MOVE; stop, no retry or continuation') from None
        value['state']='completed' if len(value['attempts'])==len(m['moves']) else 'paused';self.journal.write(value);self.unchanged();return value
