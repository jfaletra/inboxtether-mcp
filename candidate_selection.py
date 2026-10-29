"""Bounded saved selections in the existing journal; no new authority or worker."""
import copy,math,re,secrets
from collections import Counter
from journal import digest,require
from organization_errors import OrganizationError,translate
from candidate_discovery import Eligibility

TTL=7200
MAX_RECORDS=64
HEX=re.compile(r'^[0-9a-f]{64}$')
STATES=('selected','validating','preparing','blocked','ready','superseded','cancelled')

def snapshot(service,value):
    # Creating/viewing another selection does not invalidate saved mail evidence.
    state={k:v for k,v in value.items() if k!='candidate_selections'}
    return digest({'state':state,'binding':service.binding,'policy':service.policy.fingerprint})

def validate_records(value,identity):
    records=value.get('candidate_selections',{})
    require(type(records) is dict and len(records)<=MAX_RECORDS,'Invalid selection history')
    for key,r in records.items():
        require(type(key) is str and HEX.fullmatch(key) and type(r) is dict and set(r)=={'plan','fingerprint','state','entries'},'Invalid selection record')
        p=r['plan']
        require(type(p) is dict and set(p)=={'identity','scope','decision_hashes','snapshot','destination_pins','destination_paths','baseline','review_binding','workflow_binding','run_id','run_fingerprint','created','expires'},'Invalid selection plan')
        require(p['identity']==identity and digest(p)==r['fingerprint'] and type(p['snapshot']) is str and HEX.fullmatch(p['snapshot']),'Selection binding differs')
        scope=p['scope'];require(type(scope) is list and 1<=len(scope)<=200 and all(type(x) is list and len(x)==2 and type(x[0]) is int and 0<x[0]<=4294967295 and x[1] in ('Industry','Marketing','Orders','Review','Suppliers') for x in scope),'Invalid selection scope')
        require(type(p['destination_pins']) is dict and set(p['destination_pins'])=={c for u,c in scope} and all(type(v) is int and 0<v<=4294967295 for v in p['destination_pins'].values()),'Invalid selected destination pins')
        require(type(p['destination_paths']) is dict and set(p['destination_paths'])==set(p['destination_pins']) and all(type(v) is str and v for v in p['destination_paths'].values()),'Invalid selected destination paths')
        require(len({u for u,c in scope})==len(scope) and set(p['decision_hashes'])=={str(u) for u,c in scope} and all(type(h) is str and HEX.fullmatch(h) for h in p['decision_hashes'].values()),'Invalid selection decisions')
        require(type(p['created']) in (int,float) and type(p['expires']) in (int,float) and math.isfinite(p['created']) and math.isfinite(p['expires']) and p['expires']-p['created']==TTL,'Invalid selection lifetime')
        require(r['state'] in STATES and type(r['entries']) is list and len(r['entries'])<=len(scope),'Invalid selection progress')
        for e,(u,c) in zip(r['entries'],scope):
            require(e['uid']==u and e['category']==c and e['source_path']==identity['source_path'] and e['source_uidvalidity']==identity['source_uidvalidity'] and e['decision_sha256']==p['decision_hashes'][str(u)],'Selection validation differs')
        if r['state']=='ready':
            b=value['batches'].get(key)
            require(not r['entries'] and b and [(e['uid'],e['category']) for e in b['manifest']['moves']]==[(u,c) for u,c in scope],'Published selection differs')
        else:require(key not in value['batches'] and key not in value.get('bulk_preparations',{}),'Unfinished selection is executable')

def record(service,value,key):
    if type(key) is not str or not HEX.fullmatch(key):raise OrganizationError('selection_invalid','selection')
    r=value.get('candidate_selections',{}).get(key)
    if not r:raise OrganizationError('selection_invalid','selection')
    return r

def current(service,value,key,r):
    p=r['plan']
    if service.clock()>=p['expires']:raise OrganizationError('selection_expired','selection',preparation_id=key)
    if p['snapshot']!=snapshot(service,value):raise OrganizationError('selection_stale','selection',preparation_id=key)
    if p['workflow_binding']!=service.binding or p['baseline']!=service.baseline or p['review_binding']!=service.review_binding():raise OrganizationError('selection_stale','selection',preparation_id=key)
    if p['destination_pins']!={c:service.pins[c] for u,c in p['scope']} or p['destination_paths']!={c:service.paths[c] for u,c in p['scope']}:raise OrganizationError('selection_stale','selection',preparation_id=key)
    index=Eligibility(service,value)
    for u,c in p['scope']:
        index.check(u)
        d=value['workflow']['decisions'][str(u)]
        if digest(d)!=p['decision_hashes'][str(u)] or d['category']!=c:raise OrganizationError('selection_stale','selection',uid=u,preparation_id=key)

def issue(service,value,scope):
    records=value.setdefault('candidate_selections',{})
    if len(records)>=MAX_RECORDS:raise OrganizationError('selection_capacity','selection')
    if not scope:raise OrganizationError('selection_empty','selection')
    key=secrets.token_hex(32)
    require(key not in records and key not in value['batches'] and key not in value.get('bulk_preparations',{}),'Selection ID collision')
    now=service.clock();plan={'identity':copy.deepcopy(service.registry.identity),'scope':copy.deepcopy(scope),'decision_hashes':{str(u):digest(value['workflow']['decisions'][str(u)]) for u,c in scope},'snapshot':snapshot(service,value),'destination_pins':{c:service.pins[c] for u,c in scope},'destination_paths':{c:service.paths[c] for u,c in scope},'baseline':copy.deepcopy(service.baseline),'review_binding':service.review_binding(),'workflow_binding':service.binding,'run_id':service.seed['run_id'],'run_fingerprint':service.seed['fingerprint'],'created':now,'expires':now+TTL}
    records[key]={'plan':plan,'fingerprint':digest(plan),'state':'selected','entries':[]}
    validate_records(value,service.registry.identity);service.save(value)
    return compact(service,key)

def select(service,payload):
    if type(payload) is not dict or set(payload)!={'select_count'} or type(payload['select_count']) is not int or not 1<=payload['select_count']<=200:raise OrganizationError('invalid_payload','selection')
    value=service.load();index=Eligibility(service,value)
    uids=[u for u in sorted(index.inventory) if index.reason(u) is None][:payload['select_count']]
    return issue(service,value,[[u,value['workflow']['decisions'][str(u)]['category']] for u in uids])

def compact(service,key):
    value=service.load();r=record(service,value,key);p=r['plan'];b=value['batches'].get(key)
    result={'selection_ref':key,'preparation_id':key,'selection_fingerprint':r['fingerprint'],'state':r['state'],'selected_messages':len(p['scope']),'prepared_messages':len(b['manifest']['moves']) if b else len(r['entries']),'selection_expires':p['expires'],'summary_by_destination':dict(sorted(Counter(c for u,c in p['scope']).items())),'approval_allowed':bool(b and b['state']=='prepared' and service.clock()<b['manifest']['expires']),'reserved_messages':len(p['scope']) if b else 0,'next_action':'prepare_selection' if r['state']=='selected' else ('continue_acknowledged_prepare' if r['state']=='preparing' else 'inspect_saved_state')}
    if r['state']=='preparing':result['batch_id']=key
    if b:
        result.update(batch_id=key,state=b['state'],fingerprint=b['fingerprint'],review_url=service.origin+service.review_path_prefix+'/review/'+key,approval_start_deadline=b['manifest']['expires'],execution_deadline=b['manifest']['execution_deadline'],preference_revision=b['manifest']['review_binding']['preference_revision'])
    return result

def details(service,payload):
    if set(payload)-{'selection_ref','offset','limit'}:raise OrganizationError('invalid_payload','selection')
    start=payload.get('offset',0);limit=payload.get('limit',10)
    if type(start) is not int or not 0<=start<=200 or type(limit) is not int or not 1<=limit<=25:raise OrganizationError('invalid_payload','selection')
    value=service.load();key=payload['selection_ref'];r=record(service,value,key);p=r['plan']
    if r['state']=='selected':current(service,value,key,r)
    result=compact(service,key);rows=[]
    if start>len(p['scope']):raise OrganizationError('invalid_payload','selection')
    batch=value['batches'].get(key);entries={e['uid']:e for e in batch['manifest']['moves']} if batch else {}
    for u,c in p['scope'][start:start+limit]:
        d=value['workflow']['decisions'].get(str(u),{});preview=entries[u].get('preview',{}) if u in entries else d.get('review_preview',{})
        if type(preview) is not dict:preview={}
        row={'uid':u,'category':c,'decision_sha256':p['decision_hashes'][str(u)],'preview':{k:str(preview.get(k,''))[:160] for k in ('sender','subject')}}
        if u in entries:
            e=entries[u];row.update({k:copy.deepcopy(e[k]) for k in ('source_path','source_uidvalidity','destination_path','destination_uidvalidity','evidence','raw_sha256')})
        rows.append(row)
    result.update(messages=rows,offset=start,has_more=start+len(rows)<len(p['scope']),next_offset=start+len(rows) if start+len(rows)<len(p['scope']) else None,untrusted_previews=True)
    return result

def exclude(service,payload):
    if set(payload)!={'selection_ref','exclude_uids'}:raise OrganizationError('invalid_payload','selection')
    value=service.load();key=payload['selection_ref'];r=record(service,value,key)
    if r['state']!='selected':raise OrganizationError('selection_consumed','selection',preparation_id=key)
    current(service,value,key,r);omit=payload['exclude_uids'];selected={u for u,c in r['plan']['scope']}
    if type(omit) is not list or not omit or len(omit)>200 or any(type(u) is not int or u not in selected for u in omit) or len(set(omit))!=len(omit):raise OrganizationError('invalid_payload','selection')
    scope=[[u,c] for u,c in r['plan']['scope'] if u not in omit]
    if not scope:raise OrganizationError('selection_empty','selection')
    r['state']='superseded'
    # Same exact subset, no top-up; original record stays as audit evidence.
    result=issue(service,value,scope);result['excluded_uids']=omit;result['superseded_selection_ref']=key
    return result

def prepare(service,key,*,continuation=False):
    try:return _prepare(service,key,continuation=continuation)
    except Exception as exc:raise translate(exc,'preparation',preparation_id=key) from None

def _prepare(service,key,*,continuation=False):
    value=service.load();r=record(service,value,key)
    expected='preparing' if continuation else 'selected'
    if r['state']!=expected:raise OrganizationError('selection_consumed' if r['state'] in ('ready','superseded','cancelled','preparing') else 'selection_blocked','selection',preparation_id=key)
    current(service,value,key,r);p=r['plan'];scope=p['scope'];start=len(r['entries'])
    op=service.operation(key,[(u,c) for u,c in scope])
    # A crash while reading leaves an explicit no-retry marker, no reservations.
    r['state']='validating';service.save(value)
    try:
        entries=[]
        for u,c in scope[start:start+10]:entries.append(op.snapshot(u,c))
        if service.clock()>=p['expires']:raise OrganizationError('selection_expired','selection',preparation_id=key)
        # The account lock spans dispatch; selections themselves are excluded from snapshot.
        current(service,value,key,r)
    except BaseException as exc:
        r['state']='blocked';service.save(value)
        if isinstance(exc,Exception):raise translate(exc,'source_validation',uid=u,preparation_id=key) from None
        raise
    r['entries'].extend(entries);r['state']='preparing'
    if len(r['entries'])<len(scope):service.save(value);return compact(service,key)
    # All sources have passed non-marking validation before any reservation is made.
    from bulk_moves import publish
    plan={k:copy.deepcopy(v) for k,v in p.items() if k not in ('snapshot','destination_pins','destination_paths')}
    value.setdefault('bulk_preparations',{})[key]={'plan':plan,'fingerprint':digest(plan),'state':'preparing','entries':r['entries']}
    r['state']='ready';r['entries']=[]
    publish(service,value,key,value['bulk_preparations'][key])
    return compact(service,key)

def cancel(service,key,fp):
    service.chat_enabled();value=service.load();r=record(service,value,key)
    if r['fingerprint']!=fp or r['state'] not in ('selected','preparing','blocked','validating') or key in value['batches']:raise OrganizationError('selection_consumed','selection',preparation_id=key)
    r['state']='cancelled';service.save(value)
    return compact(service,key)
