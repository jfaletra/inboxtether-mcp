"""Synthetic owner-session workflows. No production configuration, mail or sockets."""
from contract_support import contract_hash
import ast
import asyncio
import contextlib
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import jsonschema
from mcp.server.fastmcp import FastMCP
from test_move_integration import Fixture, OWNER, WEB, READER
from test_organizer import mail
from journal import Refused,digest,require
from client_native import NativeMoveService,CHAT,CorrectionJournal
from move_broker import MoveBroker

class FolderBox:
    def __init__(self,box):
        self.uv=box.uv;self.pins=box.pins;self.source=box.source;self.dest={}
        self.moves=[];self.discovered=3;self.journal=None;self.failure=None
    def inbox_identity(self):return self.uv,self.discovered+1
    def folder(self,name):return self.pins[name]
    def uids(self,low,high):return sorted(u for u in self.source if low<=u<=high)
    def fetch(self,name,uv,uid):return self.source.get(uid) if name=='INBOX' else self.dest.get((name,uid))
    def raw_digest(self,name,uv,uid,size):return digest(self.fetch(name,uv,uid).raw)
    def move(self,uv,uid,category,dest_uv,**kwargs):return self.move_from('INBOX',uv,uid,category,dest_uv,**kwargs)
    def move_from(self,source,uv,uid,destination,dest_uv,*,evidence,expires_at,on_prepared):
        require(self.journal.read()['attempts'][-1]['state']=='claimed','Durable claim first')
        message=self.fetch(source,uv,uid);on_prepared(digest(message.raw))
        self.moves.append((source,uid,destination))
        if self.failure:raise OSError('synthetic ambiguous outcome')
        new_uid=uid+1000
        moved=replace(message,uid=new_uid,source_uidvalidity=dest_uv)
        if destination=='INBOX':self.source[new_uid]=moved;self.discovered=max(self.discovered,new_uid)
        else:self.dest[destination,new_uid]=moved
        if source=='INBOX':del self.source[uid]
        else:del self.dest[source,uid]
        return dest_uv,new_uid

class NativeFixture(Fixture):
    def setUp(self):
        super().setUp();old=self.service;self.box=FolderBox(self.box)
        self.service=NativeMoveService(old.registry,self.box,old.policy,old.seed,old.baseline,
            old.assert_baseline,old.paths,old.pins,OWNER,old.origin,clock=lambda:self.now,client_session_consent=True)
        self.broker=MoveBroker(self.ctx,WEB,READER,OWNER)
    def approve(self,b):return self.call('consent',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint'],'decision':'approved'})
    def execute(self,b):
        with self.registry:self.box.journal=self.service.journal_for(b['batch_id'])
        return self.call('execute',{'batch_id':b['batch_id']})
    def preference(self,category='Marketing',phrase='Industry bulletin',rule_id='test_rule'):
        p=self.call('preferences')
        return self.call('prepare_preference',{'operation':'upsert','rule_id':rule_id,
            'spec':{'sender':'news@example.com','subject_contains':phrase,'category':category},'revision':p['revision']})
    def approve_preference(self,p,decision='approved'):
        return self.call('decide_preference',{'preference_id':p['preference_id'],'fingerprint':p['fingerprint'],'decision':decision})
    def filed(self):
        b=self.batch();self.approve(b);self.execute(b)
        return b,self.call('filed_context',{'receipt_id':b['batch_id'],'uid':1})
    def correction_batch(self,c,category='Marketing'):
        return self.call('prepare_correction',{'correction_id':c['correction_id'],'fingerprint':c['fingerprint'],
            'category':category,'customer_risk':'clear','reason':'promotion'})

class NativeTests(NativeFixture):
    def test_exact_chat_consent_then_execution_preserves_flags_and_receipt(self):
        self.box.source[1]=replace(self.box.source[1],flags=('\\Seen','$Owner'))
        b=self.batch();self.assertEqual(self.box.moves,[])
        with self.assertRaises(Refused):self.execute(b)
        a=self.approve(b);self.assertEqual(a['method'],CHAT);self.assertFalse(a['independently_verified_human_approval'])
        v=self.execute(b);self.assertEqual(v['state'],'completed');self.assertEqual(v['attempts'][0]['flags'],['$Owner','\\Seen'])
        self.assertEqual(self.box.moves,[('INBOX',1,'Suppliers')])
        with self.assertRaises(Refused):self.execute(b)
    def test_browser_fallback(self):
        b=self.batch();self.decide(b);self.assertEqual(self.execute(b)['state'],'completed')
    def test_native_flag_defaults_off_and_revocation_blocks_chat_approval_execution(self):
        b=self.batch();self.service.client_session_consent=False
        with self.assertRaises(Refused):self.approve(b)
        self.service.client_session_consent=True;self.approve(b);self.service.client_session_consent=False
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.box.moves,[])
    def test_no_boolean_owner_or_attestation_fields(self):
        b=self.batch()
        for extra in ({'approved':True},{'principal':OWNER},{'human_verified':True}):
            with self.assertRaises(Refused):self.call('consent',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint'],'decision':'approved',**extra})
        with self.assertRaises(Refused):self.call('consent',{'batch_id':b['batch_id'],'fingerprint':'0'*64,'decision':'approved'})
    def test_expired_and_replayed_consent(self):
        b=self.batch();self.approve(b)
        with self.assertRaises(Refused):self.approve(b)
        self.now=b['manifest']['expires']
        with self.assertRaises(Refused):self.execute(b)
    def test_preference_change_blocks_old_consent_and_execution(self):
        b=self.batch();self.approve(b);p=self.preference();self.approve_preference(p)
        with self.assertRaises(Refused):self.execute(b)
        with self.assertRaises(Refused):self.approve(b)
        self.assertEqual(self.box.moves,[])
    def test_one_message_correction_and_history(self):
        self.classify();p=self.call('correction_context',{'uid':1})
        self.call('propose',{'uid':1,'request_id':p['request_id'],'request_fingerprint':p['request_fingerprint'],
            'category':'Marketing','customer_risk':'clear','reason':'promotion'})
        self.assertEqual(self.call('preferences')['revision'],0)
        b=self.call('prepare',{'uids':[1]});self.assertEqual(b['manifest']['moves'][0]['category'],'Marketing')
        with self.registry:self.assertEqual(self.registry.read()['client_native']['classification_history'][0]['prior']['category'],'Suppliers')
        self.assertEqual(self.box.moves,[])
    def test_reserved_and_customer_corrections_refused(self):
        b=self.batch()
        with self.assertRaises(Refused):self.call('correction_context',{'uid':1})
        self.call('next')
        with self.assertRaises(Refused):self.call('correction_context',{'uid':2})
        self.call('cancel',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint']})
        self.assertEqual(self.call('correction_context',{'uid':1})['uid'],1)
    def test_cancel_does_not_erase_approval_or_allow_claim_reset(self):
        b=self.batch();self.approve(b);self.call('cancel',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint']})
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['approval']['method'],CHAT)
        with self.assertRaises(Refused):self.execute(b)
    def test_pending_preferences_do_not_apply_then_approved_rule_is_enforced(self):
        p=self.preference(phrase='Industry')
        self.assertEqual(self.call('preferences')['revision'],0)
        self.approve_preference(p)
        q=self.call('next');self.assertEqual(q['context']['owner_preferences']['required_category'],'Marketing')
        result=self.call('propose',{'uid':q['uid'],'request_id':q['request_id'],'request_fingerprint':q['request_fingerprint'],
            'category':'Suppliers','customer_risk':'clear','reason':'supplier-notice'})
        self.assertFalse(result['move_eligible'])
        q=self.call('correction_context',{'uid':1})
        self.call('propose',{'uid':1,'request_id':q['request_id'],'request_fingerprint':q['request_fingerprint'],
            'category':'Marketing','customer_risk':'clear','reason':'promotion'})
        b=self.call('prepare',{'uids':[1]});self.approve(b);self.assertEqual(self.execute(b)['state'],'completed')
    def test_narrow_sender_and_context_both_required(self):
        self.approve_preference(self.preference(phrase='Does not match'))
        self.assertIsNone(self.call('next')['context']['owner_preferences']['required_category'])
    def test_rule_edit_inspect_revoke_and_audit(self):
        self.approve_preference(self.preference(phrase='Industry'))
        self.approve_preference(self.preference(category='Industry',phrase='Industry'))
        state=self.call('preferences');self.assertEqual(state['rules']['test_rule']['spec']['category'],'Industry')
        p=self.call('prepare_preference',{'operation':'revoke','rule_id':'test_rule','spec':None,'revision':state['revision']})
        self.approve_preference(p);state=self.call('preferences')
        self.assertEqual(state['revision'],3);self.assertFalse(state['rules']['test_rule']['active']);self.assertEqual(len(state['history']),3)
        self.assertIsNone(self.call('next')['context']['owner_preferences']['required_category'])
    def test_stale_edit_and_preference_replay_refused(self):
        a=self.preference();b=self.preference(rule_id='other');self.approve_preference(a)
        with self.assertRaises(Refused):self.approve_preference(a)
        with self.assertRaises(Refused):self.approve_preference(b)
    def test_rejected_and_expired_preference_never_apply(self):
        a=self.preference();self.approve_preference(a,'rejected');b=self.preference();self.now+=1801
        with self.assertRaises(Refused):self.approve_preference(b)
        self.assertEqual(self.call('preferences')['revision'],0)
    def test_broad_sender_and_empty_context_refused(self):
        for sender,phrase in (('*@example.com','Synthetic'),('example.com','Synthetic'),('news@example.com',''),('news@example.com','*'),('Name <news@example.com>','Synthetic')):
            with self.subTest(sender=sender,phrase=phrase),self.assertRaises(Refused):
                self.call('prepare_preference',{'operation':'upsert','rule_id':'x','spec':{'sender':sender,'subject_contains':phrase,'category':'Marketing'},'revision':0})
    def test_conflicting_preferences_keep(self):
        self.approve_preference(self.preference(phrase='Industry'))
        self.approve_preference(self.preference(category='Industry',phrase='Industry',rule_id='other'))
        self.assertEqual(self.call('next')['reason'],'owner-rule-conflict')
    def test_keep_preference_cannot_move(self):
        self.approve_preference(self.preference(category='Inbox / Keep',phrase='Industry'))
        self.assertEqual(self.call('next')['reason'],'owner-rule-keep')
        with self.assertRaises(Refused):self.call('prepare',{'uids':[1]})
    def test_customer_guard_precedes_preference(self):
        self.approve_preference(self.preference(phrase='Industry'))
        self.box.source[1]=mail(body='Can you help with my order?')
        self.assertEqual(self.call('next')['origin'],'automatic_keep')
    def test_preference_only_never_moves_existing_mail(self):
        b,c=self.filed();before=copy.deepcopy(self.box.moves)
        self.approve_preference(self.preference(phrase='Industry'))
        self.assertEqual(self.box.moves,before)
    def test_corrective_move_requires_fresh_separate_consent_and_preserves_original(self):
        b,c=self.filed();original=self.call('status',{'batch_id':b['batch_id']})
        correction=self.correction_batch(c)
        with self.assertRaises(Refused):self.execute(correction)
        self.approve(correction);result=self.execute(correction)
        self.assertEqual(result['state'],'completed');self.assertEqual(result['attempts'][0]['mapping']['category'],'Marketing')
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']}),original)
        with self.assertRaises(Refused):self.execute(correction)
        with self.assertRaises(Refused):self.call('filed_context',{'receipt_id':b['batch_id'],'uid':1})
    def test_corrective_browser_fallback(self):
        b,c=self.filed();correction=self.correction_batch(c);self.decide(correction)
        self.assertEqual(self.execute(correction)['state'],'completed')
    def test_restore_to_inbox_and_next_corrective_receipt(self):
        b,c=self.filed();correction=self.correction_batch(c,'Inbox / Keep');self.approve(correction)
        result=self.execute(correction);self.assertEqual(result['attempts'][0]['mapping']['category'],'INBOX')
        with self.assertRaises(Refused):self.execute(correction)
        self.assertEqual(len(self.box.moves),2)
    def test_correction_missing_content_changed_uv_changed_refused(self):
        b,c=self.filed();source=self.box.dest['Suppliers',1001]
        self.box.dest['Suppliers',1001]=replace(source,raw=b'changed')
        with self.assertRaises(Refused):self.correction_batch(c)
        self.box.dest['Suppliers',1001]=source;self.box.pins['Suppliers']+=1
        with self.assertRaises(Refused):self.correction_batch(c)
        self.box.pins['Suppliers']-=1;del self.box.dest['Suppliers',1001]
        with self.assertRaises(Refused):self.correction_batch(c)
    def test_correction_preference_revision_and_expiry(self):
        b,c=self.filed();self.approve_preference(self.preference())
        with self.assertRaises(Refused):self.correction_batch(c)
    def test_correction_flag_change_after_review_refused(self):
        b,c=self.filed();correction=self.correction_batch(c);self.approve(correction)
        self.box.dest['Suppliers',1001]=replace(self.box.dest['Suppliers',1001],flags=('\\Seen',))
        with self.assertRaises(Refused):self.execute(correction)
        self.assertEqual(len(self.box.moves),1)
    def test_corrective_ambiguous_outcome_never_retried(self):
        b,c=self.filed();correction=self.correction_batch(c);self.approve(correction);self.box.failure=True
        with self.assertRaises(Refused):self.execute(correction)
        self.assertEqual(self.call('status',{'batch_id':correction['batch_id']})['state'],'uncertain')
        with self.assertRaises(Refused):self.execute(correction)
        with self.assertRaises(Refused):self.call('filed_context',{'receipt_id':b['batch_id'],'uid':1})
        self.assertEqual(len(self.box.moves),2)
    def test_uncertain_original_is_not_a_verified_receipt(self):
        b=self.batch();self.approve(b);self.box.failure=True
        with self.assertRaises(Refused):self.execute(b)
        with self.assertRaises(Refused):self.call('filed_context',{'receipt_id':b['batch_id'],'uid':1})
    def test_legacy_external_claims_cannot_be_imported(self):
        with self.registry:
            value=self.service.load()
            value["external_claims"]={"7":{"state":"uncertain"}}
            self.registry.journal.write(value)
        with self.assertRaises(Refused):
            self.call("preferences")
    def test_unauthorized_peer_cannot_relay_consent(self):
        b=self.batch()
        with self.assertRaises(Refused):self.call('consent',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint'],'decision':'approved'},uid=99999)

class NativeContractTests(unittest.TestCase):
    def test_real_mcp_schema_exact_action_shapes(self):
        import move_connection as c
        server=FastMCP('synthetic')
        with patch.dict(os.environ,{'INBOXTETHER_MOVES':'1','INBOXTETHER_MOVE_SOCKET':'/synthetic/no-socket'}):c.register(server)
        schema=asyncio.run(server.list_tools())[0].inputSchema
        validator=jsonschema.Draft202012Validator(schema)
        for action,shape in c.ACTION_SHAPES.items():self.assertIn(action,schema['properties']['action']['enum'])
        good={'action':'consent','payload':{'batch_id':'1'*64,'fingerprint':'2'*64,'decision':'approved'}}
        validator.validate(good)
        for bad in ({'action':'consent','payload':{}},{'action':'execute','payload':good['payload']},
                    {'action':'consent','payload':{**good['payload'],'approved':True}},
                    {'action':'prepare','payload':{'uids':[True]}}):
            self.assertFalse(validator.is_valid(bad),bad)
    def test_reader_draft_files_byte_identical_to_baseline(self):
        import hashlib
        root=Path(__file__).resolve().parents[1]
        expected=json.loads((root/"tests/reader-draft-contract.json").read_text())
        tree=ast.parse((root/"server.py").read_text())
        actual={n.name:contract_hash(n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in expected}
        self.assertEqual(actual,expected)


class NativeRegressionTests(NativeFixture):
    def test_one_message_override_does_not_change_persistent_preference(self):
        self.approve_preference(self.preference(category='Industry',phrase='Industry'))
        q=self.call('next')
        self.call('propose',{'uid':1,'request_id':q['request_id'],'request_fingerprint':q['request_fingerprint'],
            'category':'Industry','customer_risk':'clear','reason':'industry-publication'})
        q=self.call('correction_context',{'uid':1})
        self.call('propose',{'uid':1,'request_id':q['request_id'],'request_fingerprint':q['request_fingerprint'],
            'category':'Marketing','customer_risk':'clear','reason':'promotion'})
        b=self.call('prepare',{'uids':[1]});self.approve(b)
        self.assertEqual(self.execute(b)['state'],'completed')
        self.assertEqual(self.call('preferences')['rules']['test_rule']['spec']['category'],'Industry')
    def test_restored_inbox_is_not_eligible_for_ordinary_refiling(self):
        b,c=self.filed();correction=self.correction_batch(c,'Inbox / Keep');self.approve(correction);self.execute(correction)
        # Finish existing inventory, then restored message is discovered as a new UID.
        self.call('next');self.classify();q=self.call('next');self.assertEqual(q['uid'],2001)
        self.call('propose',{'uid':q['uid'],'request_id':q['request_id'],'request_fingerprint':q['request_fingerprint'],
            'category':'Suppliers','customer_risk':'clear','reason':'supplier-notice'})
        with self.assertRaises(Refused):self.call('prepare',{'uids':[2001]})
    def test_corrective_chain_follows_new_receipt_without_reusing_original_claim(self):
        b,c=self.filed();correction=self.correction_batch(c);self.approve(correction);self.execute(correction)
        c2=self.call('filed_context',{'receipt_id':correction['batch_id'],'uid':1001})
        b2=self.correction_batch(c2,'Inbox / Keep');self.approve(b2);self.assertEqual(self.execute(b2)['state'],'completed')
        self.assertEqual(len(self.box.moves),3)
    def test_review_cannot_be_retargeted_or_rehashed(self):
        b=self.batch();self.approve(b)
        with self.registry:
            raw=self.registry.batch(b['batch_id']).read();raw['manifest']['moves'][0]['category']='Marketing';raw['fingerprint']=digest(raw['manifest'])
            with self.assertRaises(Refused):self.registry.batch(b['batch_id']).write(raw)
        self.assertEqual(self.box.moves,[])
    def test_restart_keeps_rules_approvals_and_receipts(self):
        b=self.batch();self.approve(b)
        old=self.service
        self.service=NativeMoveService(old.registry,self.box,old.base_policy,old.seed,old.baseline,old.assert_baseline,
            old.paths,old.pins,OWNER,old.origin,clock=lambda:self.now,client_session_consent=True)
        self.assertEqual(self.execute(b)['state'],'completed')
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['approval']['method'],CHAT)

class CorrectiveWireTests(unittest.TestCase):
    def fixture(self):
        from test_organizer_protocol import ScriptedIMAP,AdapterTests
        from organizer.imap_adapter import IMAPMailbox
        c=ScriptedIMAP();a=AdapterTests().adapter(c);a.corrective_enabled=True
        return c,a,IMAPMailbox._fetch(c,1).evidence()
    def test_exact_folder_source_native_move_and_mapping(self):
        import time
        c,a,e=self.fixture()
        self.assertEqual(a.move_from('Suppliers',200,1,'Marketing',200,evidence=e,on_prepared=lambda _:None,expires_at=time.time()+20),(200,55))
        self.assertIn(('SELECT','"Suppliers"'),c.commands)
        self.assertFalse(any(x in str(c.commands) for x in ('COPY','STORE','EXPUNGE','CLOSE')))
    def test_restore_inbox_uses_its_own_uidvalidity(self):
        import time
        c,a,e=self.fixture();c.mapping=b'100 1 55'
        self.assertEqual(a.move_from('Suppliers',200,1,'INBOX',100,evidence=e,on_prepared=lambda _:None,expires_at=time.time()+20),(100,55))
    def test_corrective_disabled_and_outside_scope_refused(self):
        from organizer.model import OrganizerError
        import time
        c,a,e=self.fixture();a.corrective_enabled=False
        with self.assertRaises(OrganizerError):a.move_from('Suppliers',200,1,'Marketing',200,evidence=e,on_prepared=lambda _:None,expires_at=time.time()+20)
        a.corrective_enabled=True
        for source,dest in (('Trash','Industry'),('Suppliers','Trash'),('Suppliers','Suppliers')):
            with self.assertRaises(OrganizerError):a.move_from(source,200,1,dest,200,evidence=e,on_prepared=lambda _:None,expires_at=time.time()+20)
    def test_select_permit_binds_exact_source_and_is_consumed(self):
        import imaplib
        from organizer.imap_adapter import GuardedIMAP
        from organizer.model import OrganizerError
        c=object.__new__(GuardedIMAP);c._select_permit='Suppliers'
        with patch.object(imaplib.IMAP4,'_command',return_value='synthetic'):
            self.assertEqual(c._command('SELECT','"Suppliers"'),'synthetic')
            with self.assertRaises(OrganizerError):c._command('SELECT','"Suppliers"')
        c._select_permit='Suppliers'
        with self.assertRaises(OrganizerError):c._command('SELECT','"Marketing"')
    def test_combined_rights_only_in_corrective_mode(self):
        from organizer.imap_adapter import IMAPMailbox
        from organizer.model import OrganizerError
        c,a,e=self.fixture();c._namespace_validities={'INBOX':100,'Suppliers':200}
        with self.assertRaises(OrganizerError):IMAPMailbox._rights(c,'Suppliers','lrte')
        c._corrective_rights=True;IMAPMailbox._rights(c,'Suppliers','lrte')
        with patch.object(c,'myrights',return_value=('OK',[b'"Suppliers" lriswtea'])):
            with self.assertRaises(OrganizerError):IMAPMailbox._rights(c,'Suppliers','lrte')

class NativeSocketTests(NativeFixture,unittest.IsolatedAsyncioTestCase):
    async def test_exact_native_workflow_through_existing_mcp_and_unix_broker(self):
        import threading
        import move_connection
        self.broker.reader_uid=os.geteuid();self.broker.allowed_uids=(WEB,os.geteuid())
        runtime=self.root/'run';runtime.mkdir(mode=0o750);path=runtime/'native.sock'
        server=self.broker.server(path);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            tool=FastMCP('existing-native-connection')
            with patch.dict(os.environ,{'INBOXTETHER_MOVES':'1','INBOXTETHER_MOVE_SOCKET':str(path)}):move_connection.register(tool)
            async def rpc(action,payload):
                # FastMCP structured result retains the actual server response.
                result=await tool.call_tool('organize_email',{'action':action,'payload':payload})
                if isinstance(result,tuple):return result[1]
                return json.loads(next(item.text for item in result if item.type=='text'))
            q=await rpc('next',{})
            await rpc('propose',{'uid':q['uid'],'request_id':q['request_id'],'request_fingerprint':q['request_fingerprint'],
                 'category':'Suppliers','customer_risk':'clear','reason':'supplier-notice'})
            b=await rpc('prepare',{'uids':[1]})
            with self.registry:self.box.journal=self.service.journal_for(b['batch_id'])
            refused=await rpc('execute',{'batch_id':b['batch_id']});self.assertIn('error',refused)
            approved=await rpc('consent',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint'],'decision':'approved'})
            self.assertEqual(approved['method'],CHAT)
            self.assertEqual((await rpc('execute',{'batch_id':b['batch_id']}))['state'],'completed')
        finally:server.shutdown();server.server_close();worker.join();path.unlink(missing_ok=True)


from test_move_integration import BrowserTests
class NativeBrowserTests(NativeFixture,unittest.IsolatedAsyncioTestCase):
    asyncSetUp=BrowserTests.asyncSetUp
    asyncTearDown=BrowserTests.asyncTearDown
    async def test_corrective_fallback_through_real_browser_review_csrf_and_broker(self):
        import re
        from urllib.parse import urlencode
        b,c=self.filed();correction=self.correction_batch(c)
        url='/review/'+correction['batch_id']
        response=await self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertIn('Marketing',response.text)
        csrf=re.search('name="decision" value="approved".*?name="csrf" value="([^"]+)"',response.text)[1]
        response=await self.client.post(url,content=urlencode({'decision':'approved','csrf':csrf}),
            headers={'origin':self.service.origin,'content-type':'application/x-www-form-urlencoded'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.execute(correction)['state'],'completed')
        self.assertEqual(self.call('status',{'batch_id':correction['batch_id']})['approval']['method'],self.service.approval_method)

if __name__=='__main__':unittest.main(verbosity=2)
