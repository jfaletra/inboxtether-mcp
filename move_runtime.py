"""Clean-install organization using the existing broker, adapter and private journal."""
import contextlib
import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from journal import require,digest
from registry import Registry
from client_native import NativeMoveService
from organizer.runtime import load_protected_json
from organizer.identity import MailboxNamespace
from organizer.model import CATEGORIES,Policy,integer
from organizer.classifier import ClientPolicy,ContextualSender
from organizer.imap_adapter import IMAPMailbox

FIELDS={'schema','host','account','login_account','password_file','journal','socket',
        'reader_uid','web_uid','owner','review_origin','review_path_prefix','approval_method',
        'mailboxes','execution_enabled','client_session_consent','policy','senders'}
GATES={'execution_enabled','client_session_consent'}

def validate(v):
    require(type(v) is dict and set(v)-{'automatic_filing_policy','port'}==FIELDS and v['schema']==1,'Exact organization configuration required')
    require(type(v.get('port',993)) is int and 1 <= v.get('port',993) <= 65535,'Invalid secure IMAP port')
    require(all(type(v[n]) is bool for n in GATES),'Explicit boolean gates required')
    require(v['approval_method']=='browser-password-session' and v['review_path_prefix']=='/inboxtether','Local browser approval required')
    require(type(v['owner']) is dict and set(v['owner'])=={'kind','id'} and v['owner']['kind']=='local-owner'
            and type(v['owner']['id']) is str and re.fullmatch('[0-9a-f]{32}',v['owner']['id']),'Enrolled owner required')
    require(all(type(v[n]) is str and re.fullmatch(r'[A-Za-z0-9_.+@-]{1,320}',v[n]) for n in ('host','account','login_account')),'Fixed IMAP identities required')
    require(v['login_account'].casefold()!=v['account'].casefold(),'Dedicated organization principal required')
    for n in ('password_file','journal','socket'):
        require(type(v[n]) is str and Path(v[n]).is_absolute(),'Absolute protected paths required')
    origin=urlsplit(v['review_origin'])
    require(origin.scheme=='https' and origin.netloc and origin.hostname and not origin.username and not origin.password
            and not origin.path and not origin.query and not origin.fragment,'Exact HTTPS review origin required')
    require(type(v['reader_uid']) is int and type(v['web_uid']) is int and min(v['reader_uid'],v['web_uid'])>0
            and len({v['reader_uid'],v['web_uid'],os.geteuid()})==3,'Distinct executor, Reader and web identities required')
    boxes=v['mailboxes'];require(type(boxes) is dict and set(boxes)=={'INBOX',*CATEGORIES},'Six pinned folders required')
    entries=[]
    for name in ('INBOX',*CATEGORIES):
        box=boxes[name];require(type(box) is dict and set(box)=={'path','uidvalidity'},'Exact folder pin required')
        path=box['path']
        require(type(path) is str and 0<len(path)<=512 and re.fullmatch(r'[A-Za-z0-9_@.+/-]+',path)
                and all(s not in ('','.','..') for s in path.split('/')),'Unsupported literal folder path')
        entries.append((name,path,integer(box['uidvalidity'])))
    require(len({p.casefold() for _,p,_ in entries})==6,'Aliased folders refused')
    allowed={'customer_addresses','customer_domains','protected_thread_ids','customer_terms','owner_keep_rules'}
    require(type(v['policy']) is dict and set(v['policy'])<=allowed,'Only explicit protection configuration allowed')
    policy_fields={k:tuple(tuple(x) if k=='owner_keep_rules' else x for x in values) for k,values in v['policy'].items()}
    protections=Policy(v['owner']['id'],'public-rc-1',**policy_fields)
    require(type(v['senders']) is list and len(v['senders'])<=500,'Bounded explicit sender relationships required')
    senders=tuple(ContextualSender(**{**s,'reply_to_domains':tuple(s.get('reply_to_domains',())),
                  'allowed_categories':tuple(s.get('allowed_categories',CATEGORIES))}) for s in v['senders'])
    policy=ClientPolicy(protections,senders,mode='practical')
    from automatic_filing import policy as automatic_policy
    automatic_policy(v,{'host':v['host'],'account':v['account'],'source_path':boxes['INBOX']['path'],'source_uidvalidity':boxes['INBOX']['uidvalidity']},{c:boxes[c]['uidvalidity'] for c in CATEGORIES},{c:boxes[c]['path'] for c in CATEGORIES})
    return MailboxNamespace(tuple(entries),digest(boxes)),policy

def binding(v):return digest({k:value for k,value in v.items() if k not in GATES and k!='automatic_filing_policy'})

def load():
    path=os.environ['INBOXTETHER_MOVE_CONFIG'];spec=load_protected_json(path)
    ns,policy=validate(spec);expected=binding(spec);baseline={'configuration_sha256':expected}
    paths={name:ns.path(name) for name in ('INBOX',*CATEGORIES)}
    pins={name:ns.identity(name) for name in CATEGORIES};source_uv=ns.identity('INBOX')
    registry=Registry(spec['journal'],{'host':spec['host'],'account':spec['account'],
                      'source_path':paths['INBOX'],'source_uidvalidity':source_uv})
    # No legacy inventory, ledger, external receipt or installation IDs are required.
    seed={'run_id':digest({'install':expected}),'fingerprint':digest({'scope':expected}),
          'inventory':[],'decisions':{},'excluded':[],'frontier':0}
    def current():
        v=load_protected_json(path);require(binding(v)==expected,'Configuration changed; do not reset state')
        require(all(type(v[n]) is bool for n in GATES),'Invalid operator gates');return v
    def baseline_check(value):require(value==baseline and binding(current())==expected,'Configuration binding changed')
    @contextlib.contextmanager
    def context(read_only=False):
        v=current()
        if read_only:
            for p in (registry.journal.path,registry.journal.directory/'account.lock'):
                require(p.is_file() and not p.is_symlink() and p.stat().st_uid==os.geteuid() and p.stat().st_mode&0o777==0o600,'Candidate discovery requires initialized state')
        with registry:
            state=registry.read()
            adapter=IMAPMailbox(spec['host'],spec['account'],spec['password_file'],live_enabled=True,
                                login_account=spec['login_account'],namespace=ns,corrective_enabled=True,port=spec.get('port',993))
            class Scoped:
                def __init__(self):
                    self.allowed=set(state.get('workflow',{}).get('inventory',[]));self.mapped=set()
                def inbox_identity(self):
                    with adapter.connection() as c:
                        uv=adapter._identity(c,'INBOX',source_uv);adapter._rights(c,'INBOX','lrte')
                        return uv,adapter._next_uid(c)
                def folder(self,name):
                    require(name in pins,'Destination outside scope')
                    with adapter.connection() as c:
                        uv=adapter._identity(c,name,pins[name]);adapter._rights(c,name,'lrisw');return uv
                def uids(self,low,high):
                    result=adapter.uids(low,high);self.allowed.update(result);return result
                def permit(self,name,uv,uid):
                    require(name in paths and uv==ns.identity(name),'Source folder identity changed')
                    if (name=='INBOX' and uid in self.allowed) or (name,uv,uid) in self.mapped:return
                    latest=registry.read();receipts=list(latest['batches'].values())+list(latest.get('client_native',{}).get('corrections',{}).values())
                    require(any(a.get('state')=='verified' and (a['mapping']['category'],a['mapping']['uidvalidity'],a['mapping']['uid'])==(name,uv,uid)
                                for b in receipts for a in b['attempts']),'Source lacks an exact verified receipt')
                def fetch(self,name,uv,uid):self.permit(name,uv,uid);return adapter.fetch(name,uv,uid)
                def raw_digest(self,name,uv,uid,size):self.permit(name,uv,uid);return adapter.raw_digest(name,uv,uid,size)
                def checked_move(self,source,uv,uid,destination,dest_uv,kwargs):
                    require(current()['execution_enabled'],'Mailbox execution disabled')
                    require(source in paths and destination in paths and source!=destination
                            and uv==ns.identity(source) and dest_uv==ns.identity(destination),'Move outside pinned scope')
                    self.permit(source,uv,uid)
                    callback=kwargs['on_prepared']
                    def checked(raw):
                        gates=current();require(gates['execution_enabled'] and gates['client_session_consent']==v['client_session_consent'],'Operator consent/execution gate changed');callback(raw)
                    kwargs={**kwargs,'on_prepared':checked}
                    mapped_uv,mapped_uid=adapter.move_from(source,uv,uid,destination,dest_uv,**kwargs)
                    self.mapped.add((destination,mapped_uv,mapped_uid))
                    return mapped_uv,mapped_uid
                def move(self,uv,uid,cat,dest_uv,**kwargs):return self.checked_move('INBOX',uv,uid,cat,dest_uv,kwargs)
                def move_from(self,source,uv,uid,cat,dest_uv,**kwargs):return self.checked_move(source,uv,uid,cat,dest_uv,kwargs)
            service=NativeMoveService(registry,Scoped(),policy,copy.deepcopy(seed),baseline,baseline_check,paths,pins,
                spec['owner'],spec['review_origin'],approval_method=spec['approval_method'],review_path_prefix=spec['review_path_prefix'],
                client_session_consent=v['client_session_consent'])
            from automatic_filing import policy as automatic_policy
            def current_automatic_policy():
                current_spec=current()
                return {**automatic_policy(current_spec,registry.identity,pins,paths),'execution_enabled':current_spec['execution_enabled']}
            service.automatic_policy=current_automatic_policy
            execute=service.execute
            def gated_execute(key):require(current()['execution_enabled'],'Mailbox execution disabled');return execute(key)
            service.execute=gated_execute
            yield service
            baseline_check(baseline)
    return spec,context
