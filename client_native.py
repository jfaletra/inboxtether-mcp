"""Opt-in client-relayed consent and narrow owner preferences, in the existing journal.

Neither tool arguments nor their hashes attest a human interaction. The explicitly
configured owner session is trusted to relay consent. Never label it independent.
"""
import copy
import re
import secrets
from dataclasses import replace
from email.utils import getaddresses
from journal import require, digest
from move_service import MoveService
from batch_moves import BatchOperation
from organizer.classifier import ClientPolicy

CHAT = 'client-session-consent'
DESTINATIONS = ('Industry','Marketing','Orders','Review','Suppliers','Inbox / Keep')

def exact(value, fields):
    require(type(value) is dict and set(value)==set(fields), 'Exact action fields required')

def rule_spec(value):
    exact(value, ('sender','subject_contains','category'))
    sender=value['sender'];phrase=value['subject_contains']
    require(type(sender) is str and len(sender)<=320 and re.fullmatch(r'[^\s@<>*]+@[^\s@<>*]+',sender)
            and getaddresses([sender])==[('',sender)], 'Exact bare sender required')
    require(type(phrase) is str and 4<=len(phrase.strip())<=200 and phrase==phrase.strip()
            and not any(ord(c)<32 for c in phrase), 'Narrow literal subject context required')
    require(value['category'] in DESTINATIONS, 'Invalid preference destination')
    return {**value,'sender':sender.casefold()}


class PreferencePolicy:
    """Reuse existing customer/content guards; owner rules constrain classification only."""
    def __init__(self, base, native):
        self.base=base;self.revision=native['revision'];self.once=False
        self.rules=[r for r in native['rules'].values() if r['active']]
        self.owner=base.owner
        self.fingerprint=digest({'base':base.fingerprint,'preference_revision':self.revision,'rules':self.rules})

    def for_one_message(self):
        # Category preferences are overridable for an explicitly selected message.
        # Content, customer, identity and relationship protections stay unchanged.
        base=ClientPolicy(self.base.protections,
            tuple(replace(sender,preferred_category='',allowed_categories=tuple(DESTINATIONS[:-1]))
                  for sender in self.base.senders),evidence_source=self.base.evidence_source,
            mode=self.base.mode,identity_conflicts=self.base.identity_conflicts,
            supporting_source=self.base.supporting_source)
        result=PreferencePolicy(base,{'revision':self.revision,'rules':{}})
        result.once=True
        result.fingerprint=digest({'one_message_override':True,'policy':result.fingerprint})
        return result

    def selected(self, message):
        guard,packet=self.base.prepare(message)
        if packet is None:return self.base,guard,None,[]
        fields=packet['untrusted_message']
        sender=getaddresses([fields['from']])
        matches=[r for r in self.rules if len(sender)==1 and sender[0][1].casefold()==r['spec']['sender']
                 and r['spec']['subject_contains'].casefold() in fields['subject'].casefold()]
        cats={r['spec']['category'] for r in matches}
        if len(cats)>1 or cats=={'Inbox / Keep'}:
            return self.base,{**guard,'category':None,'move_eligible':False,'reason':'owner-rule-conflict' if len(cats)>1 else 'owner-rule-keep'},None,matches
        effective=self.base
        if cats:
            # Explicit approved context overrides a prior sender category constraint,
            # never a relationship, customer, content, identity or supplier guard.
            target=next(iter(cats))
            senders=tuple(replace(s,preferred_category=target,allowed_categories=tuple(sorted(set(s.allowed_categories)|{target})))
                          if s.sender.casefold()==sender[0][1].casefold() and s.kind!='unknown' else s
                          for s in self.base.senders)
            effective=ClientPolicy(self.base.protections,senders,evidence_source=self.base.evidence_source,
                                 mode=self.base.mode,identity_conflicts=self.base.identity_conflicts,
                                 supporting_source=self.base.supporting_source)
            guard,packet=effective.prepare(message)
        return effective,guard,packet,matches

    def prepare(self,message):
        _,guard,packet,matches=self.selected(message)
        if packet is not None:
            packet=copy.deepcopy(packet)
            packet['owner_preferences']={'revision':self.revision,'matches':matches,
                'required_category':matches[0]['spec']['category'] if matches else None,
                'notice':'Approved classification constraints only; never move approval.'}
        return guard,packet

    def accept(self,message,reply,request_id,request_fingerprint):
        effective,guard,packet,matches=self.selected(message)
        if packet is None:return {**guard,'category':None,'move_eligible':False}
        required=matches[0]['spec']['category'] if matches else None
        if required and reply.get('category')!=required:
            return {**guard,'category':None,'move_eligible':False,'reason':'client-category-outside-owner-preference'}
        decision=effective.accept(message,reply,request_id,request_fingerprint)
        decision['owner_preference_binding']={'revision':self.revision,'policy':self.fingerprint,
            'packet_sha256':digest(self.prepare(message)[1]),'one_message':self.once,'rule_ids':[r['id'] for r in matches]}
        return decision

    def revalidate(self,message,evidence):
        binding=evidence.get('owner_preference_binding')
        if binding and binding.get('one_message') is True and not self.once:
            return self.for_one_message().revalidate(message,evidence)
        if not binding or binding!={'revision':self.revision,'policy':self.fingerprint,
                'packet_sha256':digest(self.prepare(message)[1]),'one_message':self.once,
                'rule_ids':[r['id'] for r in self.selected(message)[3]]}:
            return {**evidence,'category':None,'move_eligible':False,'reason':'preference-revision-changed'}
        effective,_,packet,matches=self.selected(message)
        if packet is None:return {**evidence,'category':None,'move_eligible':False}
        result=effective.revalidate(message,evidence)
        if matches and result.get('category')!=matches[0]['spec']['category']:
            return {**result,'category':None,'move_eligible':False}
        return result


class NativeMoveService(MoveService):
    def __init__(self,*args,client_session_consent=False,**kwargs):
        super().__init__(*args,**kwargs)
        require(type(client_session_consent) is bool,'Explicit consent mode boolean required')
        self.client_session_consent=client_session_consent
        self.base_policy=self.policy

    def load(self):
        value=super().load()
        if 'client_native' not in value:
            value['client_native']={'schema':1,'revision':0,'rules':{},'pending_preferences':{},
                'events':[],'classification_history':[],'correction_requests':{},'corrections':{}}
            self.save(value)
        native=value['client_native']
        require(native['schema']==1 and type(native['revision']) is int,'Invalid preference state')
        self.policy=PreferencePolicy(self.base_policy,native)
        return value

    def chat_enabled(self):require(self.client_session_consent,'client session consent is not enabled')

    def review_binding(self):
        value=self.load()
        return {'preference_revision':value['client_native']['revision'],'policy_sha256':self.policy.fingerprint}

    def propose(self,proposal):
        exact(proposal,('uid','request_id','request_fingerprint','category','customer_risk','reason'))
        value=self.load();w=value['workflow'];uid=proposal['uid'];request=w['request'];uv,_=self.identity()
        require(type(uid) is int and 0<uid<=4294967295,'Exact UID integer required')
        if proposal['request_id'] in w['accepted']:
            prior=w['accepted'][proposal['request_id']]
            require(prior['submitted']==digest(proposal),'Cannot revise accepted proposal')
            return prior['result']
        require(request and request['id']==proposal['request_id'] and request['fingerprint']==proposal['request_fingerprint']
                and request['payload']['uid']==uid and self.clock()<request['expires'],'Stale classification request')
        policy=self.policy.for_one_message() if request.get('one_message') else self.policy
        message=self.mailbox.fetch('INBOX',uv,uid)
        require(message and message.evidence()==request['payload']['evidence'],'Message or flags changed')
        _,packet=policy.prepare(message)
        require(packet==request['payload']['packet'] and self.mailbox.raw_digest('INBOX',uv,uid,message.evidence()['size'])==request['payload']['raw_sha256'],'Source context changed')
        reply={k:proposal[k] for k in ('category','customer_risk','reason')}
        decision=policy.accept(message,reply,request['id'],request['fingerprint']);decision['classification_origin']='client'
        fields=packet.get('untrusted_message',{})
        decision['review_preview']={'sender':str(fields.get('from',''))[:1000],'subject':str(fields.get('subject',''))[:1000],'reason':reply['reason']}
        prior=copy.deepcopy(w['decisions'].get(str(uid)))
        if prior is not None:
            value['client_native']['classification_history'].append({'uid':uid,'prior':prior,
                'replacement':copy.deepcopy(decision),'at':self.clock()})
        w['decisions'][str(uid)]=decision;w['request']=None
        result={'uid':uid,'category':decision.get('category') or 'Inbox / Keep','move_eligible':decision.get('move_eligible',False),'origin':'client','reason':decision['reason']}
        w['accepted'][request['id']]={'submitted':digest(proposal),'result':result};self.save(value)
        return result

    def correction_context(self,uid):
        require(type(uid) is int and uid>0,'Exact source UID required')
        value=self.load();w=value['workflow']
        require(uid in w['inventory'] and uid not in w['excluded'] and str(uid) in w['decisions'],'Existing classified source required')
        self.registry.available(uid,None)
        uv,_=self.identity();message=self.mailbox.fetch('INBOX',uv,uid)
        require(message is not None,'Source disappeared')
        guard,packet=self.policy.for_one_message().prepare(message)
        require(packet is not None,'Customer/Keep/uncertain source cannot be overridden')
        payload={'uid':uid,'evidence':message.evidence(),'packet':packet,
            'raw_sha256':self.mailbox.raw_digest('INBOX',uv,uid,message.evidence()['size']),'binding':self.binding}
        request={'id':secrets.token_hex(32),'fingerprint':digest(payload),'payload':payload,'expires':self.clock()+300,'one_message':True}
        w['request']=request;self.save(value)
        return {'uid':uid,'request_id':request['id'],'request_fingerprint':request['fingerprint'],
                'context':packet,'expires':request['expires']}

    def operation(self,batch_id,scope):
        operation=super().operation(batch_id,scope)
        original=operation.assert_available
        def available(uid):
            original(uid)
            state=self.registry.read()
            for correction in state['client_native']['corrections'].values():
                for attempt in correction['attempts']:
                    mapping=attempt.get('mapping',{})
                    require(not (mapping.get('category')=='INBOX' and mapping.get('uidvalidity')==self.registry.identity['source_uidvalidity']
                        and mapping.get('uid')==uid), 'Restored source requires receipt-linked correction, never automatic refiling')
        operation.assert_available=available
        return operation

    def prepare(self,uids):
        # New normal reviews of every size share the fixed, separately bound deadlines.
        from bulk_moves import begin
        return begin(self,uids)

    def has_correction(self,key):return key in self.load()['client_native']['corrections']

    def status(self,key):
        from bulk_moves import preparation_status,is_bulk,enrich
        loaded=self.load()
        if key in loaded.get('candidate_selections',{}) and key not in loaded['batches']:
            from candidate_selection import compact
            return compact(self,key)
        if key in loaded.get('bulk_preparations',{}) and key not in loaded['batches']:return preparation_status(self,key)
        if key in self.registry.read()['client_native']['corrections']:
            value=CorrectionJournal(self.registry,key).read()
            return {**value,'batch_id':key,'review_url':self.origin+self.review_path_prefix+'/review/'+key,
                    'expired':self.clock()>=value['manifest']['expires']}
        value=super().status(key)
        if is_bulk(value['manifest']):
            value.update(enrich(value))
            if value['state'] in ('paused','executing') and value.get('bulk_execution'):
                value['expired']=self.clock()>=value['manifest']['execution_deadline']
        return value

    def checked_review(self,key,fp):
        value=self.status(key)
        require(value['fingerprint']==fp and digest(value['manifest'])==fp and not value['expired'], 'Exact unexpired review required')
        require(value['manifest'].get('review_binding')==self.review_binding(),'Review preference revision changed; prepare fresh')
        return value

    def decide(self,key,fp,decision,principal):
        require(principal==self.owner and decision in ('approved','rejected'),'Owner web peer required')
        return self.record_decision(key,fp,decision,self.approval_method)

    def record_decision(self,key,fp,decision,method):
        value=self.checked_review(key,fp)
        require('automatic_policy_binding' not in value['manifest'],'Automatic manifest uses policy authority; prepare a manual review for consent')
        require(value['state']=='prepared' and not value['attempts'] and value['approval'] is None,'Review consumed')
        value={k:v for k,v in value.items() if k not in ('batch_id','review_url','expired','summary_by_destination','total_messages','verified_messages','remaining_messages','chunk_size','approval_start_deadline','execution_deadline','can_continue')}
        value['state']=decision
        value['approval']={'method':method,'principal':copy.deepcopy(self.owner),'fingerprint':fp,'at':self.clock()}
        self.journal_for(key).write(value)
        return {'batch_id':key,'fingerprint':fp,'state':decision,'method':method,
                'independently_verified_human_approval':False if method==CHAT else True}

    def journal_for(self,key):
        return CorrectionJournal(self.registry,key) if key in self.load()['client_native']['corrections'] else self.registry.batch(key)

    def execute(self,key):
        value=self.status(key)
        if 'automatic_policy_binding' in value['manifest']:
            from automatic_filing import execute
            execute(self,key);current=self.status(key)
            report={k:current[k] for k in ('batch_id','fingerprint','state','approval','expired','summary_by_destination','total_messages','verified_messages','remaining_messages','chunk_size','execution_deadline','can_continue')}
            report.update(automatic_authorization=current.get('automatic_authorization'),receipt_offset=len(value['attempts']),attempts=current['attempts'][len(value['attempts']):])
            return report
        self.checked_review(key,value['fingerprint'])
        approval=value['approval'];require(approval is not None,'Batch has no approval')
        method=approval['method']
        if method==CHAT:self.chat_enabled()
        else:require(method==self.approval_method,'Configured browser approval required')
        if 'correction_of' in value['manifest']:
            operation=self.correction_operation(key,value['manifest'])
        else:
            operation=self.operation(key,[(e['uid'],e['category']) for e in value['manifest']['moves']])
        result=operation.execute_consented(self.owner,method)
        from bulk_moves import is_bulk
        if not is_bulk(value['manifest']):return result
        current=self.status(key)
        # Avoid repeating the 200-message manifest on every acknowledged chunk.
        report={k:current[k] for k in ('batch_id','fingerprint','state','approval','expired','review_url','summary_by_destination','total_messages','verified_messages','remaining_messages','chunk_size','approval_start_deadline','execution_deadline','can_continue')}
        report['receipt_offset']=len(value['attempts'])
        report['attempts']=current['attempts'][report['receipt_offset']:]
        report['full_receipts_available_via_status']=True
        return report

    def cancel(self,key,fp):
        self.chat_enabled();value=self.load()
        if key in value.get('bulk_preparations',{}) and key not in value['batches']:
            r=value['bulk_preparations'][key]
            require(r['fingerprint']==fp,'Exact preparation fingerprint required')
            if r['state']=='cancelled':return {'batch_id':key,'state':'cancelled','moves':0}
            from bulk_moves import cancel_preparation
            return cancel_preparation(self,key,fp)
        raw=value['batches'].get(key)
        if raw and raw['fingerprint']==fp and not raw['attempts'] and 'bulk_execution' not in raw and raw['state'] in ('prepared','approved','expired') and self.clock()>=raw['manifest']['expires']:
            self.registry.retire_expired(self.clock(),only=key)
            return {'batch_id':key,'state':'expired','moves':0}
        self.chat_enabled();value=self.status(key)
        require(value['fingerprint']==fp and value['state'] in ('prepared','approved') and not value['attempts'],
                'Only exact unattempted reviews can be cancelled')
        raw={k:v for k,v in value.items() if k not in ('batch_id','review_url','expired','summary_by_destination','total_messages','verified_messages','remaining_messages','chunk_size','approval_start_deadline','execution_deadline','can_continue')};raw['state']='rejected'
        self.journal_for(key).write(raw)
        return {'state':'rejected','batch_id':key}

    def preferences(self):
        value=self.load()
        return {'revision':value['client_native']['revision'],'rules':copy.deepcopy(value['client_native']['rules']),
                'history':copy.deepcopy(value['client_native']['events']),
                'configured_keep_rules':self.base_policy.protections.owner_keep_rules,
                'sender_contexts':[__import__('dataclasses').asdict(s) for s in self.base_policy.senders]}

    def prepare_preference(self,payload):
        self.chat_enabled();exact(payload,('operation','rule_id','spec','revision'))
        value=self.load();n=value['client_native']
        require(type(payload['revision']) is int and payload['revision']==n['revision'],'Stale preference revision')
        op=payload['operation'];key=payload['rule_id']
        require(op in ('upsert','revoke') and type(key) is str and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',key),'Exact preference operation/ID required')
        prior=n['rules'].get(key)
        if op=='revoke':require(prior is not None and prior['active'] and payload['spec'] is None,'Active rule required for revocation');spec=None
        else:
            spec=rule_spec(payload['spec'])
            for rid,r in n['rules'].items():
                require(rid==key or not r['active'] or r['spec']!=spec,'Duplicate rule')
        plan={'operation':op,'rule_id':key,'spec':spec,'prior':prior,'revision':n['revision'],
              'created':self.clock(),'expires':self.clock()+1800,'account':self.registry.identity}
        request_id=secrets.token_hex(32);fp=digest(plan)
        require(len(n['pending_preferences'])<500,'Preference review capacity reached')
        n['pending_preferences'][request_id]={'manifest':plan,'fingerprint':fp,'state':'prepared'}
        self.save(value)
        return {'preference_id':request_id,'fingerprint':fp,'manifest':plan}

    def decide_preference(self,payload):
        self.chat_enabled();exact(payload,('preference_id','fingerprint','decision'))
        value=self.load();n=value['client_native'];p=n['pending_preferences'].get(payload['preference_id'])
        require(p and p['state']=='prepared' and p['fingerprint']==payload['fingerprint']==digest(p['manifest']), 'Exact unused preference review required')
        plan=p['manifest'];require(plan['revision']==n['revision'] and self.clock()<plan['expires'],'Stale preference review')
        require(payload['decision'] in ('approved','rejected'),'Explicit decision required')
        p['state']=payload['decision'];p['consent']={'method':CHAT,'at':self.clock(),'fingerprint':p['fingerprint']}
        if p['state']=='approved':
            n['revision']+=1
            if plan['operation']=='revoke':n['rules'][plan['rule_id']]['active']=False
            else:
                require(plan['rule_id'] in n['rules'] or len(n['rules'])<500,'Preference capacity reached')
                n['rules'][plan['rule_id']]={'id':plan['rule_id'],'spec':plan['spec'],'active':True,'revision':n['revision'],
                    'approval_fingerprint':p['fingerprint'],'approval_method':CHAT,'approved_at':self.clock()}
            n['events'].append(copy.deepcopy(p));value['workflow']['request']=None
        self.save(value)
        return {'state':p['state'],'revision':n['revision'],'method':CHAT}

    def receipt(self,key,uid):
        require(type(uid) is int and uid>0,'Exact receipt source UID required')
        value=self.load();n=value['client_native']
        if key in value['batches']:original=value['batches'][key]
        elif key in n['corrections']:original=n['corrections'][key]
        elif key in value['external_claims'] and str(uid)==key:original=value['external_claims'][key]['receipt']
        else:require(False,'Unknown receipt')
        require(digest(original['manifest'])==original['fingerprint'],'Receipt manifest corrupted')
        matches=[a for a in original['attempts'] if a['uid']==uid and a['state']=='verified']
        require(len(matches)==1,'Verified unambiguous receipt required; uncertain sources cannot be corrected')
        a=matches[0];entries=[e for e in original['manifest']['moves'] if e['uid']==uid]
        require(len(entries)==1,'Exact receipt entry required');e=entries[0];mapping=a['mapping']
        require(a['raw_sha256']==e['raw_sha256'] and a['flags']==e['evidence']['flags']
                and mapping['category']==e['category'] and mapping['uidvalidity']==e['destination_uidvalidity'],'Receipt verification mismatch')
        require(mapping['category'] in self.pins or mapping['category']=='INBOX','Receipt folder outside scope')
        return {'receipt_id':key,'receipt_uid':uid,'receipt_sha256':digest(original),
                'folder':mapping['category'],'uidvalidity':mapping['uidvalidity'],'uid':mapping['uid'],
                'entry':copy.deepcopy(e),'mapping':copy.deepcopy(mapping)}

    def receipt_message(self,link):
        # Re-resolve the immutable receipt every time; never accept a caller-supplied source.
        require(self.receipt(link['receipt_id'],link['receipt_uid'])==link,'Receipt changed')
        uv,_=self.identity();pin=uv if link['folder']=='INBOX' else self.pins[link['folder']]
        require(link['uidvalidity']==pin,'Receipt source folder replaced')
        CorrectionJournal.available(self.registry,link,None)
        message=self.mailbox.fetch(link['folder'],pin,link['uid'])
        require(message is not None,'Receipt source missing; no search or inferred substitute')
        current=message.evidence();old=link['entry']['evidence']
        require(all(current[k]==old[k] for k in ('sha256','size','internaldate','identity_kind')),'Receipt source content changed')
        require(self.mailbox.raw_digest(link['folder'],pin,link['uid'],current['size'])==link['entry']['raw_sha256'],'Receipt full bytes changed')
        return message

    def filed_context(self,payload):
        exact(payload,('receipt_id','uid'))
        link=self.receipt(payload['receipt_id'],payload['uid']);message=self.receipt_message(link)
        _,packet=self.policy.for_one_message().prepare(message)
        # Guarded messages may only be restored to Inbox, never refiled elsewhere.
        request={'link':link,'evidence':message.evidence(),'packet':packet,'review_binding':self.review_binding(),
                 'created':self.clock(),'expires':self.clock()+300}
        key=secrets.token_hex(32);value=self.load();n=value['client_native']
        require(len(n['correction_requests'])<500,'Correction request capacity reached')
        n['correction_requests'][key]={'manifest':request,'fingerprint':digest(request),'state':'prepared'};self.save(value)
        return {'correction_id':key,'fingerprint':digest(request),'source':link,'context':packet,
                'restore_only':packet is None,'expires':request['expires']}

    def prepare_correction(self,payload):
        exact(payload,('correction_id','fingerprint','category','customer_risk','reason'))
        value=self.load();request=value['client_native']['correction_requests'].get(payload['correction_id'])
        require(request and request['state']=='prepared' and request['fingerprint']==payload['fingerprint']==digest(request['manifest']),'Exact correction context required')
        r=request['manifest'];require(self.clock()<r['expires'] and r['review_binding']==self.review_binding(),'Stale correction context')
        message=self.receipt_message(r['link']);require(message.evidence()==r['evidence'],'Correction flags/source changed')
        _,packet=self.policy.for_one_message().prepare(message);require(packet==r['packet'],'Correction context changed')
        reply={k:payload[k] for k in ('category','customer_risk','reason')}
        from organizer.classifier import parse_client_reply
        parse_client_reply(reply)
        target=reply['category']
        if target=='Inbox / Keep':
            require(r['link']['folder']!='INBOX','Already Inbox')
            decision={**message.evidence(),'category':'INBOX','customer':False,'move_eligible':True,
                      'classification_origin':'client','rule_ids':['receipt-restore-inbox'],'classification':{'restore':r['link']}}
        else:
            require(packet is not None and target!=r['link']['folder'],'Guarded source or unchanged destination')
            decision=self.policy.for_one_message().accept(message,reply,payload['correction_id'],payload['fingerprint']);decision['classification_origin']='client'
            require(decision.get('move_eligible') is True,'Corrective classification refused')
        decision['review_preview']={k:str((packet or {}).get('untrusted_message',{}).get('from' if k=='sender' else k,''))[:1000] for k in ('sender','subject')}
        decision['review_preview']['reason']=reply['reason']
        key=secrets.token_hex(32);target=decision['category']
        op=self.correction_operation(key,{'correction_of':r['link'],'correction_decision':decision})
        op.validate(review_seconds=1800,review_binding=self.review_binding())
        # CorrectionOperation installs receipt/decision bindings before first journal write.
        value=self.load();value['client_native']['correction_requests'][payload['correction_id']]['state']='prepared-batch';self.save(value)
        return self.status(key)

    def correction_operation(self,key,manifest):
        return CorrectionOperation(self,key,manifest['correction_of'],manifest['correction_decision'])

    def dispatch(self,action,payload):
        require(type(payload) is dict,'Object payload required')
        if action=='automatic_policy':
            require(not payload,'No automatic policy authority fields')
            from automatic_filing import inspect
            return inspect(self)
        if action=='candidates':
            from candidate_discovery import candidates
            return candidates(self,payload)
        if action=='prepare' and set(payload)=={'selection_ref'}:
            from candidate_selection import prepare
            return prepare(self,payload['selection_ref'])
        if action=='prepare' and set(payload)=={'batch_id'}:
            if payload['batch_id'] in self.load().get('candidate_selections',{}) and payload['batch_id'] not in self.load()['batches']:
                from candidate_selection import prepare
                return prepare(self,payload['batch_id'],continuation=True)
            from bulk_moves import advance
            return advance(self,payload['batch_id'])
        if action=='consent':
            self.chat_enabled();exact(payload,('batch_id','fingerprint','decision'))
            require(payload['decision'] in ('approved','rejected'),'Explicit decision required')
            return self.record_decision(payload['batch_id'],payload['fingerprint'],payload['decision'],CHAT)
        if action=='cancel':
            exact(payload,('batch_id','fingerprint'))
            if payload['batch_id'] in self.load().get('candidate_selections',{}) and payload['batch_id'] not in self.load()['batches']:
                from candidate_selection import cancel
                return cancel(self,payload['batch_id'],payload['fingerprint'])
            return self.cancel(payload['batch_id'],payload['fingerprint'])
        if action=='correction_context':exact(payload,('uid',));return self.correction_context(payload['uid'])
        if action=='preferences':require(not payload,'No preference arguments');return self.preferences()
        if action=='prepare_preference':return self.prepare_preference(payload)
        if action=='decide_preference':return self.decide_preference(payload)
        if action=='filed_context':return self.filed_context(payload)
        if action=='prepare_correction':return self.prepare_correction(payload)
        return super().dispatch(action,payload)


class CorrectionJournal:
    """Same private atomic journal and lock; reserve full folder/UV/UID identities."""
    def __init__(self,registry,key):self.registry,self.key=registry,key
    def read(self):return copy.deepcopy(self.registry.read()['client_native']['corrections'].get(self.key))
    @staticmethod
    def available(registry,link,key):
        value=registry.read()
        identity=(link['folder'],link['uidvalidity'],link['uid'])
        for bid,b in value['client_native']['corrections'].items():
            other=b['manifest']['correction_of']
            if bid!=key and identity==(other['folder'],other['uidvalidity'],other['uid']):
                require(b['state'] in ('expired','rejected') and not b['attempts'],'Corrective source already reserved/attempted')
        if link['folder']=='INBOX':registry.available(link['uid'],None)
    def write(self,batch):
        value=self.registry.read();previous=value['client_native']['corrections'].get(self.key)
        require(digest(batch['manifest'])==batch['fingerprint'],'Correction fingerprint mismatch')
        link=batch['manifest']['correction_of'];self.available(self.registry,link,self.key)
        if previous:
            require(previous['manifest']==batch['manifest'] and previous['fingerprint']==batch['fingerprint'],'Immutable corrective manifest changed')
            require(previous['state'] not in ('completed','uncertain','blocked','expired','rejected'),'Consumed corrective journal')
            require(previous['approval'] is None or previous['approval']==batch['approval'],'Corrective approval changed')
            require(len(batch['attempts'])>=len(previous['attempts']),'Corrective attempts removed')
            for before,after in zip(previous['attempts'],batch['attempts']):
                require(before['uid']==after['uid'] and before['at']==after['at'],'Corrective claim changed')
                require(before['state']!='verified' or before==after,'Verified corrective receipt changed')
                require(all(after.get(k)==v for k,v in before.items() if k!='state'),'Corrective receipt fields changed')
        value['client_native']['corrections'][self.key]=copy.deepcopy(batch);self.registry.journal.write(value)


class CorrectionOperation(BatchOperation):
    def __init__(self,service,key,link,decision):
        self.service,self.link=service,link
        self.mailbox=CorrectionMailbox(service.mailbox,link)
        self.policy=RestorePolicy(service.policy) if decision['category']=='INBOX' else service.policy
        self.decisions={link['uid']:decision};self.baseline=service.baseline;self.assert_baseline=service.assert_baseline
        self.journal=CorrectionJournal(service.registry,key);self.clock=service.clock
        self.scope=((link['uid'],decision['category']),);self.uv=link['uidvalidity']
        self.pins={decision['category']:service.registry.identity['source_uidvalidity'] if decision['category']=='INBOX' else service.pins[decision['category']]}
        self.source_folder=link['folder']
        self.paths={link['folder']:service.paths[link['folder']],decision['category']:service.paths[decision['category']]}
        self.run_id=service.seed['run_id'];self.run_fingerprint=service.seed['fingerprint']
        def available(uid):
            require(service.receipt(link['receipt_id'],link['receipt_uid'])==link,'Original receipt changed')
            CorrectionJournal.available(service.registry,link,key)
            old=self.journal.read();require(old is None or not old['attempts'],'Corrective source already claimed')
        self.assert_available=available
    def validate(self,review_seconds=1800,*,review_binding=None):
        # Enrich before the first durable write, retaining the batch utility validation.
        original=self.journal
        operation=self
        class Enriched:
            def read(self):return original.read()
            def write(self,value):
                value['manifest']['correction_of']=copy.deepcopy(operation.link)
                value['manifest']['correction_decision']=copy.deepcopy(next(iter(operation.decisions.values())))
                value['fingerprint']=digest(value['manifest']);original.write(value)
        self.journal=Enriched()
        try:return super().validate(review_seconds,review_binding=review_binding)
        finally:self.journal=original


class RestorePolicy:
    def __init__(self,base):self.base=base
    def revalidate(self,message,evidence):
        # Returning an exact receipt-linked message to Inbox is allowed even when
        # customer guards veto filing. This cannot choose another destination.
        require(evidence['category']=='INBOX' and evidence['rule_ids']==['receipt-restore-inbox'],'Restore Inbox only')
        return evidence


class CorrectionMailbox:
    def __init__(self,mailbox,link):self.mailbox,self.link=mailbox,link
    def inbox_identity(self):
        return (self.mailbox.inbox_identity()[0],0) if self.link['folder']=='INBOX' else (self.mailbox.folder(self.link['folder']),0)
    def folder(self,name):return self.mailbox.inbox_identity()[0] if name=='INBOX' else self.mailbox.folder(name)
    def fetch(self,name,uv,uid):return self.mailbox.fetch(name,uv,uid)
    def raw_digest(self,name,uv,uid,size):return self.mailbox.raw_digest(name,uv,uid,size)
    def move(self,uv,uid,category,dest_uv,**kwargs):
        require((uv,uid)==(self.link['uidvalidity'],self.link['uid']),'Exact corrective source required')
        result=self.mailbox.move_from(self.link['folder'],uv,uid,category,dest_uv,**kwargs)
        return result
