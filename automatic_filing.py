"""Explicit owner-configured authority, distinct from per-manifest human consent."""
import copy,re
from journal import require,digest
FOLDERS=('Industry','Marketing','Orders','Suppliers')
HEX=re.compile(r'^[0-9a-f]{64}$')

def policy(spec,identity,pins,paths):
    raw=spec.get('automatic_filing_policy')
    if raw is None:return {'enabled':False,'folders':list(FOLDERS),'fingerprint':None}
    require(type(raw) is dict and set(raw)=={'enabled','revision','folders'} and type(raw['enabled']) is bool,'Invalid automatic policy')
    require(raw['folders']==list(FOLDERS) and type(raw['revision']) is str and HEX.fullmatch(raw['revision']),'Invalid automatic scope/revision')
    bound={'owner':spec['owner'],'source':identity,'destinations':{c:{'path':paths[c],'uidvalidity':pins[c]} for c in FOLDERS},'revision':raw['revision'],'enabled':raw['enabled'],'folders':raw['folders']}
    return {'enabled':raw['enabled'],'folders':list(FOLDERS),'revision':raw['revision'],'fingerprint':digest(bound)}

def inspect(service):
    checker=getattr(service,'automatic_policy',None)
    value=checker() if checker else {'enabled':False,'folders':list(FOLDERS),'fingerprint':None}
    return {**value,'authorization_method':'owner-enabled-automatic-policy','independent_per_batch_human_approval':False,'requires_owner_request':True,'Review':'keep_in_inbox_and_report','new_install_default':'disabled','activation_via_MCP':False}

def enabled(service,binding=None):
    p=inspect(service);require(p['enabled'] is True and p.get('execution_enabled',False) is True,'Automatic filing or execution is disabled')
    if binding is not None:require(binding=={'method':'owner-enabled-automatic-policy','policy_fingerprint':p['fingerprint']},'Automatic policy changed or revoked')
    return {'method':'owner-enabled-automatic-policy','policy_fingerprint':p['fingerprint']}

def clear_customer_risk(decision):
    # Saved client bindings keep the validated reply inside classification.reply.
    binding=decision.get('classification') if type(decision) is dict else None
    reply=binding.get('reply') if type(binding) is dict else None
    return type(reply) is dict and reply.get('customer_risk')=='clear'

def authorize(service,batch):
    m=batch['manifest'];binding=m.get('automatic_policy_binding');require(type(binding) is dict,'Automatic manifest binding required')
    enabled(service,binding)
    require('correction_of' not in m and all(e['category'] in FOLDERS for e in m['moves']),'Automatic policy excludes Review, Inbox and corrections')
    require(m.get('review_binding')==service.review_binding(),'Review preference revision changed; prepare fresh')
    v=service.load()
    from candidate_discovery import Eligibility
    index=Eligibility(service,v)
    for e in m['moves']:
        u=e['uid'];d=v['workflow']['decisions'].get(str(u),{})
        # Existing batch owns its reservation; every claim/receipt still blocks replay.
        code=index.reason(u,own_preparation=batch['batch_id'])
        # Already verified prefix is inspected by the unchanged execution engine.
        if any(a['uid']==u for a in batch['attempts']):continue
        require(code is None and d.get('customer') is False and d.get('move_eligible') is True and d.get('classification_origin')=='client' and clear_customer_risk(d) and digest(d)==e['decision_sha256'],'Automatic source no longer eligible')
    return binding

def execute(service,key):
    batch=service.status(key);require(batch.get('approval') is None,'Automatic execution never consumes chat/browser approval')
    authorize(service,batch)
    operation=service.operation(key,[(e['uid'],e['category']) for e in batch['manifest']['moves']])
    operation.automatic_check=lambda:authorize(service,service.status(key))
    return operation.execute_automatic()
