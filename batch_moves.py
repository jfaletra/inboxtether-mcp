"""Isolated reusable utility core. No MCP registration, network setup or service entry.
Trusted callers supply the existing IMAP adapter, policy, exact namespace pins,
source-bound decisions and a read-only Organizer/witness conflict check.
TTY approval remains mandatory until a separately approved browser integration.
"""
import os,time,json
from journal import Journal,Refused,require,canonical,digest
CATEGORIES=frozenset(('Industry','Marketing','Orders','Review','Suppliers'))
REVIEW_SECONDS=1800
VALID_REVIEW_SECONDS=(600, REVIEW_SECONDS)
# Conservative admission allowance, not a guarantee against network stalls.
# Budget includes native MOVE, destination/source verification and durable receipts.
EXECUTION_SECONDS_PER_MESSAGE=90
EXECUTION_FINAL_MARGIN_SECONDS=30

class BatchOperation:
    def __init__(self,mailbox,policy,decisions,baseline,assert_baseline,journal,paths,*,scope,source_uv,pins,run_id,run_fingerprint,assert_available,clock=time.time):
        self.mailbox,self.policy,self.decisions=mailbox,policy,decisions
        self.baseline,self.assert_baseline,self.journal=baseline,assert_baseline,journal
        self.paths,self.clock=paths,clock
        self.scope=tuple(scope)
        require(1<=len(self.scope)<=10, 'Batch size must be 1..10')
        require(all(type(u) is int and 0<u<=4294967295 and c in CATEGORIES for u,c in self.scope), 'Invalid source or category')
        require(len({u for u,c in self.scope})==len(self.scope) and set(decisions)=={u for u,c in self.scope}, 'Duplicate or missing source decision')
        require(type(source_uv) is int and 0<source_uv<=4294967295, 'Invalid source UIDVALIDITY')
        require(set(pins)=={c for u,c in self.scope} and all(type(v) is int and 0<v<=4294967295 for v in pins.values()), 'Invalid destination pins')
        require(set(paths)=={'INBOX', *pins} and all(isinstance(p,str) and p for p in paths.values()) and len(set(paths.values()))==len(paths), 'Exact distinct mailbox paths required')
        require(all(isinstance(s,str) and len(s)==64 and all(c in '0123456789abcdef' for c in s) for s in (run_id,run_fingerprint)), 'Invalid run binding')
        self.uv,self.pins,self.run_id,self.run_fingerprint=source_uv,dict(pins),run_id,run_fingerprint
        self.assert_available=assert_available
    def unchanged(self):self.assert_baseline(self.baseline)
    def identities(self):
        require(self.mailbox.inbox_identity()[0]==self.uv,'Source identity changed')
        for _,category in self.scope:require(self.mailbox.folder(category)==self.pins[category],'Destination identity changed')
    def snapshot(self,uid,category):
        self.unchanged();self.assert_available(uid);self.identities();e=self.decisions[uid]
        require(e.get('category')==category and e.get('customer') is False and e.get('move_eligible') is True and e.get('classification_origin')=='client','Recorded proposal not eligible')
        source=getattr(self,'source_folder','INBOX')
        current=self.mailbox.fetch(source,self.uv,uid)
        require(current is not None,'Source disappeared')
        expected={k:e[k] for k in ('uid','sha256','size','flags','internaldate','identity_kind')}
        require(current.evidence()==expected,'Source content or flags changed')
        checked=self.policy.revalidate(current,e)
        require(checked.get('category')==category and checked.get('customer') is False and checked.get('move_eligible') is True and checked.get('rule_ids')==e.get('rule_ids'),'Customer, identity, uncertainty or classification veto')
        raw=self.mailbox.raw_digest(source,self.uv,uid,e['size'])
        require(isinstance(raw,str) and len(raw)==64 and all(c in '0123456789abcdef' for c in raw),'Invalid raw digest')
        after=self.mailbox.fetch(source,self.uv,uid)
        require(after is not None and after.evidence()==expected,'Source changed during validation')
        self.identities();self.unchanged()
        return {'uid':uid,'category':category,'source_path':self.paths[source],'source_uidvalidity':self.uv,'destination_path':self.paths[category],'destination_uidvalidity':self.pins[category],'evidence':expected,'raw_sha256':raw,'decision_sha256':digest(e),'classification_sha256':digest(e.get('classification')), 'preview':e.get('review_preview',{})}
    def validate(self,review_seconds=600, *, review_binding=None):
        require(type(review_seconds) is int and review_seconds in VALID_REVIEW_SECONDS,'Unsupported review lifetime')
        require(self.journal.read() is None,'Existing journal: inspect, never reset or repeat')
        entries=[self.snapshot(uid,category) for uid,category in self.scope]
        now=self.clock()
        manifest={'schema':'inboxtether-owner-batch-1','run_id':self.run_id,'run_fingerprint':self.run_fingerprint,'baseline':self.baseline,'moves':entries,'created':now,'expires':now+review_seconds}
        if review_binding is not None:manifest['review_binding']=review_binding
        value={'manifest':manifest,'fingerprint':digest(manifest),'state':'prepared','approval':None,'attempts':[]}
        self.journal.write(value);return value
    def execute(self,incoming,outgoing):
        require(incoming.isatty() and outgoing.isatty(),'Independent interactive terminal required')
        value=self.journal.read();require(value is not None,'Validate first')
        m=value['manifest'];fp=value['fingerprint']
        require(digest(m)==fp and m['run_id']==self.run_id and m['run_fingerprint']==self.run_fingerprint and m['baseline']==self.baseline,'Manifest binding changed')
        require(value['state']=='prepared' and not value['attempts'] and value['approval'] is None,'Journal consumed or quarantined; no replay')
        require([(e['uid'],e['category']) for e in m['moves']]==list(self.scope),'Move scope changed')
        require(m['expires']-m['created'] in VALID_REVIEW_SECONDS and m['created']<=self.clock()<m['expires'],'Manifest expired')
        # Freshly validate BOTH entries before asking the owner to approve either move.
        require([self.snapshot(u,c) for u,c in self.scope]==m['moves'],'Manifest needs new review; stop')
        outgoing.write(json.dumps(m,indent=2,ensure_ascii=True)+'\n')
        outgoing.write('Exact native move batch, no other mailbox changes. Type APPROVE '+fp+'\n');outgoing.flush()
        require(incoming.readline().rstrip('\n')=='APPROVE '+fp,'Approval cancelled')
        require(self.clock()<m['expires'],'Approval expired');self.unchanged()
        value['approval']={'method':'owner-tty','fingerprint':fp,'at':self.clock(),'uid':os.geteuid()}
        value['state']='approved';self.journal.write(value)
        return self._execute_authorized(value)

    def execute_browser(self,owner,approval_method='browser-oidc-session'):
        require(approval_method in ('browser-oidc-session','browser-password-session'),'Unsupported configured approval method')
        return self.execute_consented(owner,approval_method)

    def execute_consented(self,owner,approval_method):
        # Caller must enforce opt-in for client-session-consent. No human attestation implied.
        require(approval_method in ('browser-oidc-session','browser-password-session','client-session-consent'),'Unsupported approval method')
        value=self.journal.read();require(value is not None,'Prepare first')
        m=value['manifest'];a=value['approval']
        require(value['state']=='approved' and not value['attempts'],'Not approved or consumed')
        require(a is not None and a=={'method':approval_method,'principal':owner,'fingerprint':value['fingerprint'],'at':a.get('at')},'Exact configured consent record required')
        require(digest(m)==value['fingerprint'] and m['run_id']==self.run_id and m['run_fingerprint']==self.run_fingerprint and m['baseline']==self.baseline,'Manifest changed')
        require(m['created']<=a['at']<=self.clock()<m['expires'] and m['expires']-m['created'] in VALID_REVIEW_SECONDS,'Approval expired')
        require([(e['uid'],e['category']) for e in m['moves']]==list(self.scope),'Scope changed')
        self.require_execution_window(m,len(m['moves']))
        require([self.snapshot(u,c) for u,c in self.scope]==m['moves'],'Manifest requires new approval')
        return self._execute_authorized(value)

    def require_execution_window(self,manifest,remaining):
        required=EXECUTION_FINAL_MARGIN_SECONDS+EXECUTION_SECONDS_PER_MESSAGE*remaining
        require(manifest['expires']-self.clock()>=required,
                'Insufficient manifest lifetime for full remaining batch; no MOVE authorized')

    def _execute_authorized(self,value):
        m=value['manifest']
        # Recheck after all source validation and independent approval. An admission
        # refusal changes no batch/claim/approval and never renews its expiration.
        self.require_execution_window(m,len(m['moves']))
        for index,entry in enumerate(m['moves']):
            remaining=len(m['moves'])-index
            uid,category=entry['uid'],entry['category']
            try:
                self.require_execution_window(m,remaining)
                require(self.snapshot(uid,category)==entry,'Source changed before move')
                self.require_execution_window(m,remaining)
            except Exception:
                value['state']='blocked';self.journal.write(value);raise Refused('Pre-move validation failed; stop without retry') from None
            attempt={'uid':uid,'state':'claimed','at':self.clock()}
            value['attempts'].append(attempt);value['state']='executing'
            self.journal.write(value) # fsync claim BEFORE calling any possibly mutating method
            try:
                def prepared(raw):
                    require(raw==entry['raw_sha256'],'Raw content changed at MOVE boundary')
                    self.require_execution_window(m,remaining)
                    self.unchanged()
                dest_uv,dest_uid=self.mailbox.move(self.uv,uid,category,self.pins[category],evidence=self.decisions[uid],expires_at=m['expires'],on_prepared=prepared)
                require(type(dest_uid) is int and 0<dest_uid<=4294967295 and dest_uv==self.pins[category],'Invalid MOVE mapping')
                attempt['mapping']={'category':category,'uidvalidity':dest_uv,'uid':dest_uid}
                self.journal.write(value) # acknowledged mapping survives interruption during verification
                after=self.mailbox.fetch(category,dest_uv,dest_uid)
                require(after is not None and after.evidence()=={**entry['evidence'],'uid':dest_uid},'Destination content, flags or date mismatch')
                require(self.mailbox.raw_digest(category,dest_uv,dest_uid,entry['evidence']['size'])==entry['raw_sha256'],'Destination bytes mismatch')
                require(self.mailbox.fetch(getattr(self,'source_folder','INBOX'),self.uv,uid) is None,'Source still present')
                self.identities();self.unchanged()
                attempt.update(state='verified',raw_sha256=entry['raw_sha256'],flags=entry['evidence']['flags'],verified_at=self.clock())
                self.journal.write(value)
            except BaseException:
                attempt['state']='uncertain';value['state']='uncertain'
                self.journal.write(value)
                raise Refused('Uncertain MOVE outcome: stop; no retry or next message') from None
        value['state']='completed';self.journal.write(value);self.unchanged();return value
