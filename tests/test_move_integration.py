"""Synthetic end-to-end Reader RPC -> existing OIDC/CSRF UI -> verified native move."""
from contract_support import contract_hash
import ast,contextlib,copy,hashlib,json,os,re,secrets,socket,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode
import httpx,jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import approval_web as web
from move_web import app
from move_broker import MoveBroker
from move_service import MoveService
from registry import Registry
from journal import Refused,digest,require
from test_mailbox import Mailbox
from test_organizer import mail,policy
from organizer.classifier import ClientPolicy,ContextualSender
from organizer.model import Message

ORIGIN='https://review.example.org';ISSUER='https://identity.example.org';OWNER={'issuer':ISSUER,'subject':'owner-subject'}
WEB=19001;READER=19002
class Box(Mailbox):
    def __init__(self):
        super().__init__();self.source={1:mail(body='Wholesale inventory stock availability.'),2:mail(body='Can you help with my order?'),3:mail(body='Wholesale inventory allocation.')};self.pins={c:9000+i for i,c in enumerate(('Industry','Marketing','Orders','Review','Suppliers'))};self.discovered=3
    def inbox_identity(self):return self.uv,self.discovered+1
    def uids(self,low,high):return sorted(u for u in self.source if low<=u<=high)

class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.root.chmod(0o700)
        self.box=Box();self.registry=Registry(self.root,{'host':'example.org','account':'owner@example.org','source_path':'Shared/test/INBOX','source_uidvalidity':self.box.uv})
        self.policy=ClientPolicy(policy(),(ContextualSender('news@example.com','supplier'),),mode='practical');self.now=time.time()
        seed={'run_id':'1'*64,'fingerprint':'2'*64,'inventory':[1,2,3],'decisions':{},'excluded':[],'frontier':3}
        self.baseline={'ledger':'original','witness':'original'};self.current=copy.deepcopy(self.baseline)
        def baseline(expected):require(self.current==expected,'Baseline changed')
        self.service=MoveService(self.registry,self.box,self.policy,seed,self.baseline,baseline,{'INBOX':'Shared/test/INBOX',**{c:'Shared/test/'+c for c in self.box.pins}},self.box.pins,OWNER,ORIGIN,clock=lambda:self.now)
        @contextlib.contextmanager
        def ctx():
            with self.registry:yield self.service
        self.ctx=ctx;self.broker=MoveBroker(ctx,WEB,READER,OWNER)
    def call(self,action,payload=None,uid=READER):return self.broker.dispatch({'operation':'organize','action':action,'payload':payload or {}},uid)
    def classify(self):
        p=self.call('next');return self.call('propose',{'uid':p['uid'],'request_id':p['request_id'],'request_fingerprint':p['request_fingerprint'],'category':'Suppliers','customer_risk':'clear','reason':'supplier-notice'})
    def batch(self):self.classify();return self.call('prepare',{'uids':[1]})
    def decide(self,batch,decision='approved',uid=WEB,principal=None):return self.broker.dispatch({'operation':'decide','draft_id':batch['batch_id'],'principal':principal or OWNER,'fingerprint':batch['fingerprint'],'decision':decision},uid)
    def execute(self,batch):
        self.box.journal=self.registry.batch(batch['batch_id'])
        return self.call('execute',{'batch_id':batch['batch_id']})

class SecurityTests(Fixture):
    def test_reader_cannot_approve_even_with_exact_owner_object(self):
        b=self.batch()
        with self.assertRaises(Refused):self.decide(b,uid=READER)
        self.assertEqual(self.box.moves,[])
    def test_unapproved_and_rejected_never_move(self):
        b=self.batch()
        with self.assertRaises(Refused):self.execute(b)
        self.decide(b,'rejected')
        with self.assertRaises(Refused):self.execute(b)
    def test_owner_and_peer_are_both_required(self):
        b=self.batch()
        for uid,principal in ((99999,OWNER),(WEB,{'issuer':ISSUER,'subject':'other'})):
            with self.assertRaises(Refused):self.decide(b,uid=uid,principal=principal)
    def test_no_approval_fields_accepted_on_tool(self):
        for action in ('next','prepare','execute','status'):
            with self.assertRaises((Refused,KeyError)):self.call(action,{'approved':True,'owner':OWNER})
        with self.assertRaises(Refused):self.call('approve')
    def test_customer_automatic_keep_not_eligible_for_manifest(self):
        self.classify();p=self.call('next');self.assertEqual(p['origin'],'automatic_keep');self.assertEqual(p['uid'],2)
        with self.assertRaises(Refused):self.call('prepare',{'uids':[2]})
    def test_source_bound_submission_and_replay(self):
        p=self.call('next');q={'uid':1,'request_id':p['request_id'],'request_fingerprint':p['request_fingerprint'],'category':'Suppliers','customer_risk':'clear','reason':'supplier-notice'}
        with self.assertRaises(Refused):self.call('propose',{**q,'uid':3})
        a=self.call('propose',q);self.assertEqual(a,self.call('propose',q))
        with self.assertRaises(Refused):self.call('propose',{**q,'category':'Orders'})
    def test_accepted_batch_exact_verified_no_replay(self):
        b=self.batch();self.decide(b);v=self.execute(b)
        self.assertEqual(v['state'],'completed');self.assertEqual(self.box.moves,[1]);self.assertEqual(v['attempts'][0]['state'],'verified')
        with self.assertRaises(Refused):self.execute(b)
        with self.assertRaises(Refused):self.call('prepare',{'uids':[1]})
        self.assertEqual(self.current,self.baseline)
    def test_expired_approval_no_move(self):
        b=self.batch();self.decide(b);self.now+=1801
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.box.moves,[])
    def test_flags_changed_after_approval_no_move(self):
        b=self.batch();self.decide(b);self.box.source[1]=__import__('dataclasses').replace(self.box.source[1],flags=('\\Seen',))
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.box.moves,[])
    def test_ledger_change_refused(self):
        b=self.batch();self.decide(b);self.current['witness']='changed'
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.box.moves,[])
    def test_ambiguous_outcome_is_durable_not_retried(self):
        b=self.batch();self.decide(b);self.box.failure='before-ack'
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['state'],'uncertain')
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.box.moves,[1])
    def test_scope_and_destination_pins_revalidated(self):
        b=self.batch();self.decide(b);self.box.pins['Suppliers']+=1
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.box.moves,[])
    def test_discovery_finishes_inventory_then_only_new(self):
        self.classify();self.call('next');self.classify()
        self.assertEqual(self.call('next')['remaining'],0)
        self.box.source[4]=__import__('dataclasses').replace(mail(body='Wholesale inventory notice.'),uid=4);self.box.discovered=4
        self.assertEqual(self.call('next')['uid'],4)
        with self.registry:
            w=self.registry.read()['workflow'];self.assertEqual(w['inventory'],[1,2,3,4]);self.assertEqual(w['frontier'],4)
    def test_policy_cannot_be_overridden_by_owner(self):
        b=self.batch();self.decide(b);self.box.source[1]=mail(body='Can you help with my order?')
        with self.assertRaises(Refused):self.execute(b)
        self.assertEqual(self.box.moves,[])
    def test_seven_existing_tool_functions_unchanged(self):
        import hashlib
        root=Path(__file__).resolve().parents[1]
        expected=json.loads((root/"tests/reader-draft-contract.json").read_text())
        tree=ast.parse((root/"server.py").read_text())
        actual={n.name:contract_hash(n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in expected}
        self.assertEqual(actual,expected)

class BrowserTests(Fixture,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.config=web.WebConfig(ORIGIN,ISSUER,'review',OWNER['subject'],ISSUER+'/keys',self.root/'broker.sock',self.root/'web.sock',secrets.token_bytes(32))
        verifier=web.OIDCVerifier(self.config);verifier.keys=SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=key.public_key()))
        token=jwt.encode({'iss':ISSUER,'sub':OWNER['subject'],'aud':'review','iat':int(time.time())-1,'exp':int(time.time())+600},key,algorithm='RS256',headers={'kid':'synthetic'})
        broker=self.broker
        class Local:
            def call(self,operation,key,principal,**fields):return broker.dispatch({'operation':operation,'draft_id':key,'principal':principal,**fields},WEB)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app(self.config,verifier,Local())),base_url=ORIGIN,headers={'authorization':'Bearer '+token})
    async def asyncTearDown(self):await self.client.aclose()
    async def test_real_oidc_csrf_approval_then_execution_without_terminal(self):
        b=self.batch();r=await self.client.get('/review/'+b['batch_id']);self.assertEqual(r.status_code,200);self.assertIn('Suppliers',r.text);self.assertEqual(self.box.moves,[])
        token=re.search('name="decision" value="approved".*?name="csrf" value="([^"]+)"',r.text)[1]
        r=await self.client.post('/review/'+b['batch_id'],content=urlencode({'decision':'approved','csrf':token}),headers={'origin':ORIGIN,'content-type':'application/x-www-form-urlencoded'})
        self.assertEqual(r.status_code,200);self.assertEqual(self.box.moves,[])
        self.assertEqual(self.execute(b)['state'],'completed')
    async def test_oidc_forgery_and_csrf_are_rejected(self):
        b=self.batch();url='/review/'+b['batch_id']
        self.assertEqual((await self.client.get(url,headers={'authorization':'Bearer forged','x-auth-request-user':OWNER['subject']})).status_code,403)
        await self.client.get(url)
        for origin in (ORIGIN,'https://evil.invalid'):
            r=await self.client.post(url,content='decision=approved&csrf=forged',headers={'origin':origin,'content-type':'application/x-www-form-urlencoded'})
            self.assertEqual(r.status_code,409)
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['state'],'prepared')

class LifecycleTests(Fixture):
    def test_expired_unclaimed_batch_requires_fresh_owner_approval(self):
        b=self.batch();self.decide(b);self.now+=1801
        fresh=self.call('prepare',{'uids':[1]});self.assertNotEqual(fresh['batch_id'],b['batch_id'])
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['state'],'expired')
        with self.assertRaises(Refused):self.execute(fresh)
        self.decide(fresh);self.assertEqual(self.execute(fresh)['state'],'completed')
    def test_unread_and_persistent_flags_survive_browser_execution(self):
        import dataclasses
        for flags in ((),('\\Seen','$Custom')):
            # Each iteration uses a distinct source, not a reset or replay.
            uid=1 if not flags else 3
            self.box.source[uid]=dataclasses.replace(mail(uid=uid,body='Wholesale inventory notice.'),flags=flags)
            if uid==3:
                self.call('next') # UID2 customer automatic Keep
            self.classify();b=self.call('prepare',{'uids':[uid]});self.decide(b)
            v=self.execute(b);self.assertEqual(set(v['attempts'][0]['flags']),set(flags))
    def test_restart_resumes_existing_context_without_skipping(self):
        p=self.call('next')
        self.service.registry=Registry(self.root,self.registry.identity);self.registry=self.service.registry
        self.assertEqual(self.call('next')['request_id'],p['request_id'])
        self.assertEqual(self.call('next')['uid'],1)
    def test_external_exclusion_survives_workflow_seed(self):
        self.service.seed['excluded']=[1];self.service.seed['decisions']={'1':{'category':'Suppliers','move_eligible':True,'customer':False}}
        self.assertEqual(self.call('next')['uid'],2)
        with self.assertRaises(Refused):self.call('prepare',{'uids':[1]})
    def test_unexpected_reader_peer_rejected(self):
        with self.assertRaises(Refused):self.call('next',uid=99999)

class SocketAndToolTests(Fixture,unittest.IsolatedAsyncioTestCase):
    async def test_new_tool_real_unix_rpc_and_default_disabled(self):
        from mcp.server.fastmcp import FastMCP
        from move_connection import register
        import approval_broker
        default=FastMCP('default')
        with patch.dict(os.environ,{'INBOXTETHER_MOVES':'0'}):register(default)
        self.assertEqual(await default.list_tools(),[])
        # Same-UID local socket fixture exercises OS peer lookup; production loader
        # enforces distinct identities. Other role remains a different synthetic UID.
        self.broker.reader_uid=os.geteuid();self.broker.allowed_uids=(WEB,os.geteuid())
        runtime=self.root/'run';runtime.mkdir(mode=0o750);path=runtime/'b.sock'
        srv=self.broker.server(path);worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
        try:
            tool=FastMCP('existing-connection')
            with patch.dict(os.environ,{'INBOXTETHER_MOVES':'1','INBOXTETHER_MOVE_SOCKET':str(path)}):register(tool)
            listed=await tool.list_tools();self.assertEqual([t.name for t in listed],['organize_email'])
            self.assertNotIn('approved',listed[0].inputSchema['properties'])
            result=await tool.call_tool('organize_email',{'action':'next','payload':{}})
            self.assertIn('request_fingerprint',str(result));self.assertEqual(self.box.moves,[])
        finally:srv.shutdown();srv.server_close();worker.join();path.unlink(missing_ok=True)

class SocketAccessTests(unittest.TestCase):
    def test_post_start_waits_for_socket_and_only_grants_exact_clients(self):
        import socket_access
        from unittest.mock import Mock
        info=lambda mode,uid:SimpleNamespace(st_mode=mode,st_uid=uid,st_dev=1,st_ino=2)
        states=iter([False,True]);times=iter([0,0])
        with patch('socket_access.pwd.getpwnam',side_effect=lambda name:SimpleNamespace(pw_uid=19004 if name=='inboxtether-web' else 19003)),patch.object(Path,'exists',side_effect=lambda:next(states)),patch.object(Path,'is_symlink',return_value=False),patch.object(Path,'lstat',side_effect=[info(0o40750,19003),info(0o140660,19003),info(0o140660,19003)]),patch('socket_access.socket_ready',return_value=True):
            run=Mock();pause=Mock();socket_access.grant('broker',{'reader_uid':1000,'web_uid':19004},runner=run,clock=lambda:next(times),sleep=pause)
            self.assertEqual(run.call_count,4);self.assertEqual(pause.call_count,1)
            self.assertEqual(run.call_args_list[1].args[0],['/usr/bin/setfacl','-m','u:1000:rw-','/run/inboxtether-approval-broker/moves.sock'])
            self.assertEqual(run.call_args_list[2].args[0],['/usr/bin/setfacl','-m','u:19004:--x','/run/inboxtether-approval-broker'])
            self.assertEqual(run.call_args_list[3].args[0],['/usr/bin/setfacl','-m','u:19004:rw-','/run/inboxtether-approval-broker/moves.sock'])
    def test_socket_helper_refuses_symlinks_or_regular_files(self):
        import socket_access
        from unittest.mock import Mock
        for symlink,mode in ((True,0o140660),(False,0o100660)):
            with patch('socket_access.pwd.getpwnam',side_effect=lambda name:SimpleNamespace(pw_uid=19004 if name=='inboxtether-web' else 19003)),patch.object(Path,'exists',return_value=True),patch.object(Path,'is_symlink',return_value=symlink),patch.object(Path,'lstat',side_effect=[SimpleNamespace(st_mode=0o40750,st_uid=19003),SimpleNamespace(st_mode=mode,st_uid=19003)]):
                run=Mock()
                with self.assertRaises(Refused):socket_access.grant('broker',{'reader_uid':1000,'web_uid':19004},runner=run)
                run.assert_not_called()
