"""Bounded organization workflow in the existing approval broker, private JSON only."""
import copy,secrets,time
from journal import require,digest
from batch_moves import BatchOperation

class MoveService:
    def __init__(self,registry,mailbox,policy,seed,baseline,assert_baseline,paths,pins,owner,origin,clock=time.time,approval_method='browser-oidc-session',review_path_prefix=''):
        self.registry,self.mailbox,self.policy,self.seed=registry,mailbox,policy,seed
        self.baseline,self.assert_baseline,self.paths,self.pins=baseline,assert_baseline,paths,pins
        self.owner,self.origin,self.clock=owner,origin,clock
        require(approval_method in ('browser-oidc-session','browser-password-session'),'Unsupported browser authorization method')
        self.approval_method=approval_method
        require(review_path_prefix in ('','/inboxtether'),'Invalid review prefix')
        self.review_path_prefix=review_path_prefix
        self.binding=digest({'identity':registry.identity,'policy':policy.fingerprint,'paths':paths,'pins':pins,'owner':owner,'baseline':baseline,'approval_method':approval_method,'review_prefix':review_path_prefix})
    def load(self):
        self.assert_baseline(self.baseline)
        value=self.registry.read()
        if 'workflow' not in value:
            require(not value['batches'],'Seed before preparing any batches')
            value['workflow']={'binding':self.binding,'inventory':self.seed['inventory'],
                'decisions':copy.deepcopy(self.seed['decisions']),'excluded':self.seed['excluded'],
                'frontier':self.seed['frontier'],'request':None,'accepted':{},'generation':0}
            self.registry.journal.write(value)
        require(value['workflow']['binding']==self.binding,'Configuration or source baseline changed; stop for reconciliation')
        return value
    def save(self,value):self.registry.journal.write(value)
    def identity(self):
        uv,next_uid=self.mailbox.inbox_identity()
        require(uv==self.registry.identity['source_uidvalidity'],'Inbox identity changed')
        for c,pin in self.pins.items():require(self.mailbox.folder(c)==pin,'Destination identity changed')
        return uv,next_uid
    def next(self):
        value=self.load();w=value['workflow'];uv,next_uid=self.identity()
        pending=[u for u in w['inventory'] if str(u) not in w['decisions'] and u not in w['excluded']]
        if not pending:
            require(next_uid-1>=w['frontier'],'UID frontier regressed')
            new=self.mailbox.uids(w['frontier']+1,next_uid-1) if next_uid-1>w['frontier'] else []
            require(len(new)<=20000 and new==sorted(set(new)) and all(type(u) is int and w['frontier']<u<next_uid for u in new),'Invalid discovered identities')
            require(self.mailbox.inbox_identity()[0]==uv,'Identity changed during inventory')
            w['inventory']+=new;w['frontier']=next_uid-1;pending=new;self.save(value)
        if not pending:return {'remaining':0,'notice':'No new messages; organization runs only on request.'}
        uid=pending[0]
        from organizer.imap_adapter import MessageUnsupported
        try:message=self.mailbox.fetch('INBOX',uv,uid)
        except MessageUnsupported:
            w['decisions'][str(uid)]={'uid':uid,'category':None,'move_eligible':False,'reason':'unreadable-or-oversized','classification_origin':'automatic_keep'};w['request']=None;self.save(value)
            return {'uid':uid,'category':'Inbox / Keep','origin':'automatic_keep','reason':'unreadable-or-oversized','remaining':len(pending)-1}
        guard,packet=self.policy.prepare(message) if message else ({'uid':uid,'category':None,'reason':'disappeared','move_eligible':False},None)
        if packet is None:
            w['decisions'][str(uid)]={**guard,'classification_origin':'automatic_keep'};w['request']=None;self.save(value)
            return {'uid':uid,'category':'Inbox / Keep','origin':'automatic_keep','reason':guard['reason'],'remaining':len(pending)-1}
        payload={'uid':uid,'evidence':message.evidence(),'packet':packet,'raw_sha256':self.mailbox.raw_digest('INBOX',uv,uid,message.evidence()['size']),'binding':self.binding}
        prior=w['request']
        if not prior or prior['payload']!=payload or prior['expires']<=self.clock():
            prior={'id':secrets.token_hex(32),'fingerprint':digest(payload),'payload':payload,'expires':self.clock()+300}
            w['request']=prior;self.save(value)
        return {'uid':uid,'request_id':prior['id'],'request_fingerprint':prior['fingerprint'],'context':packet,'remaining':len(pending),'expires':prior['expires']}
    def propose(self,proposal):
        require(type(proposal) is dict and set(proposal)=={'uid','request_id','request_fingerprint','category','customer_risk','reason'},'Exact source-bound proposal required; no authority fields')
        value=self.load();w=value['workflow'];uid=proposal['uid'];request=w['request'];uv,_=self.identity()
        require(type(uid) is int and 0<uid<=4294967295,'Exact UID integer required')
        if proposal['request_id'] in w['accepted']:
            prior=w['accepted'][proposal['request_id']];require(prior['submitted']==digest(proposal),'Cannot revise accepted proposal');return prior['result']
        require(request and request['id']==proposal['request_id'] and request['fingerprint']==proposal['request_fingerprint'] and request['payload']['uid']==uid and self.clock()<request['expires'],'Stale classification request')
        message=self.mailbox.fetch('INBOX',uv,uid)
        require(message and message.evidence()==request['payload']['evidence'],'Message or flags changed')
        guard,packet=self.policy.prepare(message)
        require(packet==request['payload']['packet'] and self.mailbox.raw_digest('INBOX',uv,uid,message.evidence()['size'])==request['payload']['raw_sha256'],'Source context changed')
        reply={k:proposal[k] for k in ('category','customer_risk','reason')}
        decision=self.policy.accept(message,reply,request['id'],request['fingerprint']);decision['classification_origin']='client'
        fields=packet.get('untrusted_message',{})
        decision['review_preview']={k:str(fields.get(k,''))[:1000] for k in ('sender','subject')}
        w['decisions'][str(uid)]=decision;w['request']=None
        result={'uid':uid,'category':decision.get('category') or 'Inbox / Keep','move_eligible':decision.get('move_eligible',False),'origin':'client','reason':decision['reason']}
        w['accepted'][request['id']]={'submitted':digest(proposal),'result':result};self.save(value);return result
    def operation(self,batch_id,scope):
        value=self.load();w=value['workflow'];decisions={u:w['decisions'][str(u)] for u,c in scope}
        def available(uid):
            self.assert_baseline(self.baseline)
            require(uid not in w['excluded'],'Organizer source exclusion')
            self.registry.available(uid,batch_id)
        operation_type=BatchOperation
        if len(scope)>10 or batch_id in value.get('bulk_preparations',{}) or value['batches'].get(batch_id,{}).get('manifest',{}).get('schema')=='inboxtether-owner-bulk-1':
            from bulk_moves import BulkOperation
            operation_type=BulkOperation
        return operation_type(self.mailbox,self.policy,decisions,self.baseline,self.assert_baseline,self.registry.batch(batch_id),
            {n:self.paths[n] for n in ('INBOX',*{c for u,c in scope})},scope=scope,
            source_uv=self.registry.identity['source_uidvalidity'],pins={c:self.pins[c] for u,c in scope},
            run_id=self.seed['run_id'],run_fingerprint=self.seed['fingerprint'],assert_available=available,clock=self.clock)
    def prepare(self,uids):
        require(type(uids) is list and 1<=len(uids)<=10 and all(type(u) is int for u in uids) and len(set(uids))==len(uids),'Exact 1..10 UIDs required')
        w=self.load()['workflow'];scope=[]
        for uid in uids:
            d=w['decisions'].get(str(uid),{})
            require(d.get('move_eligible') is True and d.get('customer') is False and d.get('category') in self.pins,'Customer/Keep/uncertain source cannot enter batch')
            scope.append((uid,d['category']))
        # Retire only expired, NEVER CLAIMED authorizations. Old manifest/approval
        # stay in history; preparing a replacement always needs new browser approval.
        for old_key,old in self.registry.read()['batches'].items():
            if old['state'] in ('prepared','approved') and not old['attempts'] and self.clock()>=old['manifest']['expires']:
                old['state']='expired';self.registry.batch(old_key).write(old)
        key=secrets.token_hex(32);self.operation(key,scope).validate(review_seconds=1800);return self.status(key)
    def status(self,key):
        self.load();value=self.registry.batch(key).read();require(value is not None,'Unknown batch')
        result=copy.deepcopy(value);result['batch_id']=key;result['review_url']=self.origin+self.review_path_prefix+'/review/'+key
        result['expired']=self.clock()>=value['manifest']['expires'];return result
    def decide(self,key,fp,decision,principal):
        require(principal==self.owner and decision in ('approved','rejected'),'Independent owner required')
        value=self.status(key);require(not value['expired'] and value['state']=='prepared' and fp==value['fingerprint'],'Review expired or consumed')
        value={k:v for k,v in value.items() if k not in ('batch_id','review_url','expired')}
        value['state']=decision
        value['approval']={'method':self.approval_method,'principal':copy.deepcopy(principal),'fingerprint':fp,'at':self.clock()}
        self.registry.batch(key).write(value);return {'state':decision}
    def execute(self,key):
        value=self.status(key);scope=[(e['uid'],e['category']) for e in value['manifest']['moves']]
        return self.operation(key,scope).execute_browser(self.owner,self.approval_method)
    def dispatch(self,action,payload):
        require(type(payload) is dict,'Object payload required')
        if action=='next':require(not payload,'No next arguments');return self.next()
        if action=='propose':return self.propose(payload)
        if action=='prepare':require(set(payload)=={'uids'},'Exact batch UIDs');return self.prepare(payload['uids'])
        require(action in ('status','execute') and set(payload)=={'batch_id'},'Unsupported operation or approval field')
        return self.status(payload['batch_id']) if action=='status' else self.execute(payload['batch_id'])
