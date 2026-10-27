"""Public runtime integration against fabricated IMAP, no legacy or production files."""
import asyncio,contextlib,copy,json,os,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from journal import Refused,digest
from organizer.model import CATEGORIES,OrganizerError
from test_organizer import mail
import move_runtime as runtime

class Adapter:
    messages={};moves=[];config=None;fail=False;before_move=None
    def __init__(self,*args,**kwargs):self.settings=kwargs
    @contextlib.contextmanager
    def connection(self):yield self
    def _identity(self,c,name,pin):
        actual=self.config['mailboxes'][name]['uidvalidity']
        if actual!=pin:raise OrganizerError('Identity changed')
        return actual
    def _rights(self,c,name,rights):pass
    def _next_uid(self,c):return max([0,*[uid for name,uid in self.messages if name=='INBOX']])+1
    def uids(self,low,high):return sorted(uid for name,uid in self.messages if name=='INBOX' and low<=uid<=high)
    def fetch(self,name,uv,uid):return self.messages.get((name,uid))
    def raw_digest(self,name,uv,uid,size):return digest(self.fetch(name,uv,uid).raw)
    def move_from(self,source,uv,uid,dest,dest_uv,**kw):
        message=self.fetch(source,uv,uid)
        if type(self).before_move:type(self).before_move()
        kw['on_prepared'](digest(message.raw))
        if self.fail:raise OSError('Fabricated ambiguous response')
        new_uid=uid+10000
        self.messages[dest,new_uid]=replace(message,uid=new_uid,source_uidvalidity=dest_uv)
        del self.messages[source,uid];self.moves.append((source,uid,dest));return dest_uv,new_uid

class CleanInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.root.chmod(0o700)
        self.config=json.loads((Path(__file__).resolve().parents[1]/'examples/organization.json.example').read_text())
        self.config.update(journal=str(self.root),reader_uid=os.geteuid()+101,web_uid=os.geteuid()+102,
            owner={'kind':'local-owner','id':'a'*32},client_session_consent=True,
            senders=[{'sender':'news@example.com','kind':'supplier'}])
        for i,box in enumerate(self.config['mailboxes'].values()):box['uidvalidity']=8000+i
        Adapter.config=copy.deepcopy(self.config);Adapter.messages={('INBOX',4):mail(uid=4,body='Wholesale inventory stock availability.',flags=('\\Seen','$Custom'))}
        Adapter.moves=[];Adapter.fail=False;Adapter.before_move=None
        self.loader=patch.object(runtime,'load_protected_json',side_effect=lambda _:copy.deepcopy(self.config));self.loader.start();self.addCleanup(self.loader.stop)
        self.adapter=patch.object(runtime,'IMAPMailbox',Adapter);self.adapter.start();self.addCleanup(self.adapter.stop)
        self.env=patch.dict(os.environ,{'INBOXTETHER_MOVE_CONFIG':str(self.root/'unused.json')});self.env.start();self.addCleanup(self.env.stop)
        self.reload()
    def reload(self):self.spec,self.context=runtime.load()
    def call(self,action,payload=None):
        with self.context() as service:return service.dispatch(action,payload or {})
    def batch(self):
        p=self.call('next');self.assertEqual(p['uid'],4)
        self.call('propose',{'uid':4,'request_id':p['request_id'],'request_fingerprint':p['request_fingerprint'],
                            'category':'Suppliers','customer_risk':'clear','reason':'supplier-notice'})
        return self.call('prepare',{'uids':[4]})
    def consent(self,b):return self.call('consent',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint'],'decision':'approved'})
    def test_empty_journal_discovers_arbitrary_inventory_and_survives_restart(self):
        self.assertFalse((self.root/'operation.json').exists())
        b=self.batch();self.assertFalse(Adapter.moves);self.reload()
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['fingerprint'],b['fingerprint'])
        state=json.loads((self.root/'operation.json').read_text())
        self.assertEqual(state['workflow']['inventory'],[4]);self.assertFalse(state['external_claims'])
    def test_empty_mailbox_needs_no_seed_or_receipt(self):
        Adapter.messages={};self.assertEqual(self.call('next')['remaining'],0)
    def test_disabled_execution_then_independent_browser_approval(self):
        b=self.batch()
        with self.assertRaises(Refused):self.call('execute',{'batch_id':b['batch_id']})
        with self.context() as service:service.decide(b['batch_id'],b['fingerprint'],'approved',self.config['owner'])
        self.config['execution_enabled']=True;self.reload()
        result=self.call('execute',{'batch_id':b['batch_id']});self.assertEqual(result['state'],'completed')
        self.assertEqual(result['attempts'][0]['flags'],['$Custom','\\Seen'])
        self.reload()
        with self.assertRaises(Refused):self.call('execute',{'batch_id':b['batch_id']})
        self.assertEqual(len(Adapter.moves),1)
    def test_clean_install_chat_and_receipt_correction_chain(self):
        self.config['execution_enabled']=True;self.reload();b=self.batch();self.consent(b)
        self.call('execute',{'batch_id':b['batch_id']});self.reload()
        c=self.call('filed_context',{'receipt_id':b['batch_id'],'uid':4})
        correction=self.call('prepare_correction',{'correction_id':c['correction_id'],'fingerprint':c['fingerprint'],
                             'category':'Inbox / Keep','customer_risk':'clear','reason':'owner-review'})
        self.assertEqual(len(Adapter.moves),1)
        self.consent(correction);self.call('execute',{'batch_id':correction['batch_id']})
        self.assertEqual(Adapter.moves,[('INBOX',4,'Suppliers'),('Suppliers',10004,'INBOX')])
    def test_gate_revocation_at_actual_move_boundary(self):
        self.config['execution_enabled']=True;self.reload();b=self.batch();self.consent(b)
        Adapter.before_move=lambda:setattr(self,'config',{**self.config,'execution_enabled':False})
        with self.assertRaises(Refused):self.call('execute',{'batch_id':b['batch_id']})
        self.assertFalse(Adapter.moves)
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['state'],'uncertain')
    def test_config_drift_does_not_reinitialize_journal(self):
        self.batch();before=(self.root/'operation.json').read_bytes();self.config['account']='different@example.com'
        with self.assertRaises(Refused):self.call('next')
        self.assertEqual(before,(self.root/'operation.json').read_bytes())
    def test_uncertain_claim_is_not_retried_after_restart(self):
        self.config['execution_enabled']=True;self.reload();b=self.batch();self.consent(b);Adapter.fail=True
        with self.assertRaises(Refused):self.call('execute',{'batch_id':b['batch_id']})
        self.reload();Adapter.fail=False
        with self.assertRaises(Refused):self.call('execute',{'batch_id':b['batch_id']})
        self.assertFalse(Adapter.moves)
    def test_invalid_config_is_rejected_before_imap(self):
        cases=[{'execution_enabled':1},{'reader_uid':os.geteuid()},{'client_session_consent':'true'},
               {'review_origin':'http://review.example.com'},{'login_account':self.config['account']}]
        for delta in cases:
            with self.subTest(delta=delta),self.assertRaises((Refused,OrganizerError)):
                runtime.validate({**self.config,**delta})
        bad=copy.deepcopy(self.config);bad['mailboxes']['INBOX']['uidvalidity']=0
        with self.assertRaises(OrganizerError):runtime.validate(bad)

class PackagingContractTests(unittest.TestCase):
    def test_catalog_has_no_sending_even_with_old_switch_enabled(self):
        import server
        env={'INBOXTETHER_SEND_ASSISTANT':'1','INBOXTETHER_MOVES':'1','INBOXTETHER_MOVE_SOCKET':'/unused.sock',
             'INBOXTETHER_DRAFT_ASSISTANT':'1','INBOXTETHER_DRAFT_MODE':'basic',
             'INBOXTETHER_BASIC_ACK':'I_ACCEPT_CLIENT_CONTROLLED_APPROVAL','INBOXTETHER_DRAFT_STATE_DIR':'/synthetic/drafts','INBOXTETHER_DRAFTS_FOLDER':'Drafts'}
        with patch.dict(os.environ,env,clear=True):tools=asyncio.run(server.create_server().list_tools())
        self.assertEqual({t.name for t in tools},{'list_mailboxes','search_messages','read_message','list_attachments',
                         'retrieve_attachment','prepare_reply_draft','save_draft','organize_email'})
        self.assertEqual(len(next(t for t in tools if t.name=='organize_email').inputSchema['properties']['action']['enum']),13)
