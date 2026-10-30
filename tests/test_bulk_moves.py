"""Only disposable synthetic messages and journals. No live configuration/IMAP."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from journal import Refused,digest
from registry import Registry
from client_native import NativeMoveService,CHAT
from bulk_moves import CHUNK_SIZE,SCHEMA,EXECUTION_SECONDS,REVIEW_SECONDS,summary
from test_mailbox import Mailbox,Message

class Policy:
 owner='owner@synthetic.example.org'
 fingerprint=digest({'synthetic':'bulk'})
 veto=False
 def prepare(self,m):return {},{'untrusted_message':{'from':'news@example.example.org','subject':'Synthetic inventory'}}
 def revalidate(self,m,d):return {**d,'customer':self.veto,'move_eligible':not self.veto}

class BulkFixture(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.root.chmod(0o700)
  self.box=Mailbox();self.box.source={u:Message(u,flags=[] if u%2 else ['\\Seen','$Owner']) for u in range(1,202)};self.box.pins={c:9000+i for i,c in enumerate(('Industry','Marketing','Orders','Review','Suppliers'))}
  self.identity={'host':'synthetic.example.org','account':'owner@synthetic.example.org','source_path':'Shared/test/INBOX','source_uidvalidity':self.box.uv}
  self.r=Registry(self.root,self.identity);self.r.__enter__();self.addCleanup(self.r.__exit__)
  self.now=1000;self.baseline={'ledger':'original','witness':'original'};self.current=copy.deepcopy(self.baseline);self.policy=Policy();self.owner={'kind':'local-owner','id':'a'*32}
  decisions={str(u):{**m.evidence(),'category':('Marketing' if u%2 else 'Orders'),'customer':False,'move_eligible':True,'classification_origin':'client','rule_ids':['synthetic'],'classification':{'mode':'client-contextual-proposal-1','classifier':self.policy.fingerprint,'packet_sha256':digest(self.policy.prepare(m)[1]),'reply':{'category':'Marketing' if u%2 else 'Orders','customer_risk':'clear','reason':'promotion' if u%2 else 'vendor-purchase'},'request_id':digest({'synthetic_request_uid':u}),'request_fingerprint':digest({'synthetic_binding_uid':u})}} for u,m in self.box.source.items()}
  seed={'run_id':'1'*64,'fingerprint':'2'*64,'inventory':list(self.box.source),'decisions':decisions,'excluded':[],'frontier':201}
  def baseline(expected):
   if expected!=self.current:raise Refused('Baseline changed')
  self.s=NativeMoveService(self.r,self.box,self.policy,seed,self.baseline,baseline,{'INBOX':self.identity['source_path'],**{c:'Shared/test/'+c for c in self.box.pins}},self.box.pins,self.owner,'https://synthetic.example.org',clock=lambda:self.now,client_session_consent=True,approval_method='browser-password-session');self.s.load()
  v=self.r.read()
  for u,m in self.box.source.items():v['workflow']['decisions'][str(u)]['owner_preference_binding']={'revision':0,'policy':self.s.policy.fingerprint,'packet_sha256':digest(self.s.policy.prepare(m)[1]),'one_message':False,'rule_ids':[]}
  self.r.journal.write(v)
 def call(self,a,p):return self.s.dispatch(a,p)
 def prepared(self,n=11):
  b=self.call('prepare',{'uids':list(range(1,n+1))})
  while b['state']=='preparing':b=self.call('prepare',{'batch_id':b['batch_id']})
  return b
 def approve(self,b,method='chat'):
  if method=='browser':return self.s.decide(b['batch_id'],b['fingerprint'],'approved',self.owner)
  return self.call('consent',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint'],'decision':'approved'})
 def execute(self,b):
  self.box.journal=self.r.batch(b['batch_id']);return self.call('execute',{'batch_id':b['batch_id']})
 def raw(self,b):return self.r.batch(b['batch_id']).read()

class BulkTests(BulkFixture):
 def test_200_manifest_prepares_in_twenty_chunks_one_exact_fingerprint(self):
  b=self.call('prepare',{'uids':list(range(1,201))});self.assertEqual(b['state'],'preparing');self.assertEqual(b['prepared_messages'],10);self.assertNotIn(b['batch_id'],self.r.read()['batches'])
  for expected in range(20,201,10):
   b=self.call('prepare',{'batch_id':b['batch_id']})
   if expected<200:self.assertEqual(b['prepared_messages'],expected)
  self.assertEqual(b['state'],'prepared');self.assertEqual(len(b['manifest']['moves']),200);self.assertEqual(digest(b['manifest']),b['fingerprint']);self.assertEqual(b['summary_by_destination']['Marketing']['count'],100);self.assertEqual(self.box.moves,[])
 def test_201_duplicates_and_boolean_uids_refused(self):
  for uids in (list(range(1,202)),list(range(1,11))+[1],list(range(1,11))+[True]):
   before=self.r.journal.path.read_bytes()
   with self.assertRaises(Refused):self.call('prepare',{'uids':uids})
   self.assertEqual(before,self.r.journal.path.read_bytes())
 def test_preparation_not_approvable_and_reserves_all_sources(self):
  b=self.call('prepare',{'uids':list(range(1,12))})
  with self.assertRaises((Refused,KeyError)):self.call('consent',{'batch_id':b['batch_id'],'fingerprint':b['preparation_fingerprint'],'decision':'approved'})
  with self.assertRaises(Refused):self.r.available(11,'f'*64)
  with self.assertRaises(Refused):self.call('prepare',{'uids':[11]})
 def test_cancel_preparation_releases_only_its_reservation_preserves_decisions(self):
  before=copy.deepcopy(self.r.read()['workflow']);b=self.call('prepare',{'uids':list(range(1,12))});self.call('cancel',{'batch_id':b['batch_id'],'fingerprint':b['preparation_fingerprint']});self.r.available(11,'f'*64);self.assertEqual(before,self.r.read()['workflow'])
 def test_customer_never_enters_bulk_even_owner_consent(self):
  v=self.r.read();v['workflow']['decisions']['11']['customer']=True;self.r.journal.write(v)
  with self.assertRaises(Refused):self.call('prepare',{'uids':list(range(1,12))})
  self.assertEqual(self.box.moves,[])
 def test_policy_veto_stops_preparation(self):
  self.policy.veto=True
  with self.assertRaises(Refused):self.prepared()
  self.assertEqual(self.box.moves,[]);self.assertEqual(list(self.r.read()['bulk_preparations'].values())[0]['state'],'blocked')
 def test_changed_flag_or_uidvalidity_blocks_continuation(self):
  b=self.call('prepare',{'uids':list(range(1,12))});self.box.source[11].flags=['\\Seen']
  with self.assertRaises(Refused):self.call('prepare',{'batch_id':b['batch_id']})
  self.assertEqual(self.box.moves,[])
 def test_preparation_expiration_never_extends_or_auto_approves(self):
  b=self.call('prepare',{'uids':list(range(1,12))});self.now=b['expires']
  with self.assertRaises(Refused):self.call('prepare',{'batch_id':b['batch_id']})
  self.assertEqual(self.r.read()['bulk_preparations'][b['batch_id']]['plan']['expires'],b['expires'])
 def test_single_consent_executes_200_in_twenty_verified_chunks(self):
  b=self.prepared(200);self.approve(b);approval=copy.deepcopy(self.raw(b)['approval']);states=[]
  for i in range(20):
   v=self.execute(b);states.append(v['state']);self.assertEqual(v['verified_messages'],10*(i+1));self.assertEqual(len(v['attempts']),10);self.assertEqual(v['receipt_offset'],10*i);self.assertEqual(v['approval'],approval);self.assertTrue(all(a['state']=='verified' for a in v['attempts']))
  self.assertEqual(states,['paused']*19+['completed']);self.assertEqual(self.box.moves,list(range(1,201)));self.assertEqual(self.current,self.baseline)
  self.assertTrue(all(a['flags']==e['evidence']['flags'] for a,e in zip(self.raw(b)['attempts'],self.raw(b)['manifest']['moves'])))
  with self.assertRaises(Refused):self.execute(b)
 def test_browser_fallback_uses_same_single_approval(self):
  b=self.prepared();self.approve(b,'browser');self.assertEqual(self.execute(b)['state'],'paused');self.assertEqual(self.execute(b)['state'],'completed')
 def test_chat_opt_in_required_for_consent_and_every_continuation(self):
  b=self.prepared();self.s.client_session_consent=False
  with self.assertRaises(Refused):self.approve(b)
  self.s.client_session_consent=True;self.approve(b);self.execute(b);self.s.client_session_consent=False
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,list(range(1,11)))
 def test_unapproved_or_wrong_fingerprint_cannot_execute(self):
  b=self.prepared()
  with self.assertRaises(Refused):self.execute(b)
  with self.assertRaises(Refused):self.call('consent',{'batch_id':b['batch_id'],'fingerprint':'0'*64,'decision':'approved'})
  self.assertEqual(self.box.moves,[])
 def test_start_after_approval_deadline_refused_without_move(self):
  b=self.prepared();self.approve(b);self.now=b['manifest']['expires']
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.raw(b)['attempts'],[]);self.assertEqual(self.box.moves,[])
 def test_started_batch_can_continue_after_review_expiry_with_fixed_deadline(self):
  b=self.prepared();self.approve(b);self.execute(b);deadline=self.raw(b)['bulk_execution']['deadline'];self.now=b['manifest']['expires']+1
  self.assertEqual(self.execute(b)['state'],'completed');self.assertEqual(self.raw(b)['bulk_execution']['deadline'],deadline)
 def test_insufficient_execution_budget_blocks_continuation_no_new_claim(self):
  b=self.prepared(21);self.approve(b);self.execute(b);self.now=b['manifest']['execution_deadline']-(11*90+30)+1
  before=self.raw(b)
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.raw(b),before);self.assertEqual(len(self.box.moves),10)
 def test_fixed_execution_deadline_expired_preserves_verified_progress(self):
  b=self.prepared();self.approve(b);self.execute(b);self.now=b['manifest']['execution_deadline']
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(len(self.raw(b)['attempts']),10);self.assertEqual(len(self.box.moves),10)
 def test_uncertain_outcome_never_retried_or_continued(self):
  b=self.prepared();self.approve(b);self.box.failure='before-ack'
  with self.assertRaises(Refused):self.execute(b)
  prior=self.raw(b);self.assertEqual(prior['state'],'uncertain')
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.raw(b),prior);self.assertEqual(self.box.moves,[1])
 def test_restart_resumes_only_acknowledged_verified_prefix(self):
  b=self.prepared();self.approve(b);self.execute(b);saved=self.raw(b);self.assertEqual(saved['state'],'paused')
  # New operation instance is built for every dispatch, as after a broker restart.
  result=self.execute(b);self.assertEqual(self.raw(b)['attempts'][:10],saved['attempts']);self.assertEqual(result['state'],'completed')
 def test_changed_remaining_source_stops_before_that_chunk(self):
  b=self.prepared();self.approve(b);self.execute(b);self.box.source[11].flags=['\\Seen']
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,list(range(1,11)));self.assertEqual(len(self.raw(b)['attempts']),10)
 def test_claimed_interruption_cannot_be_reclassified_or_resumed(self):
  b=self.prepared();self.approve(b);self.box.failure='interrupt'
  with self.assertRaises(Refused):self.execute(b)
  with self.assertRaises(Refused):self.call('correction_context',{'uid':1})
  with self.assertRaises(Refused):self.execute(b)
 def test_manifest_deadline_and_prefix_tampering_refused(self):
  b=self.prepared();self.approve(b);self.execute(b);v=self.raw(b);v['bulk_execution']['deadline']+=1
  with self.assertRaises(Refused):self.r.batch(b['batch_id']).write(v)
 def test_preference_binding_change_stops_resume(self):
  b=self.prepared();self.approve(b);self.execute(b);v=self.r.read();v['client_native']['revision']+=1;self.r.journal.write(v)
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(len(self.box.moves),10)
 def test_grouped_browser_review_retains_all_individual_details(self):
  from move_web import render
  b=self.prepared();item={'manifest':b['manifest'],'expires':b['manifest']['expires'],'fingerprint':b['fingerprint'],'state':'view-only'}
  html=render(item,self.owner,'nonce',None).body.decode()
  self.assertIn('Exact batch summary',html);self.assertIn('Individual messages and destinations',html);self.assertIn('Fixed execution deadline',html)

 def test_source_uidvalidity_change_blocks_preparation(self):
  b=self.call('prepare',{'uids':list(range(1,12))});self.box.uv+=1
  with self.assertRaises(Refused):self.call('prepare',{'batch_id':b['batch_id']})
  self.assertEqual(self.box.moves,[])
 def test_destination_pin_change_blocks_execution_without_claim(self):
  b=self.prepared();self.approve(b);self.box.pins['Marketing']+=1
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.raw(b)['attempts'],[]);self.assertEqual(self.box.moves,[])
 def test_bad_destination_hash_preserves_mapping_and_stops(self):
  b=self.prepared();self.approve(b);self.box.failure='raw-destination'
  with self.assertRaises(Refused):self.execute(b)
  v=self.raw(b);self.assertEqual(v['state'],'uncertain');self.assertIn('mapping',v['attempts'][0]);self.assertEqual(len(v['attempts']),1)
  with self.assertRaises(Refused):self.execute(b)
 def test_customer_veto_after_approval_stops_without_move(self):
  b=self.prepared();self.approve(b);self.policy.veto=True
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.raw(b)['attempts'],[]);self.assertEqual(self.box.moves,[])
 def test_read_only_status_after_lost_ack_preserves_completed_chunk(self):
  b=self.prepared();self.approve(b);self.execute(b);before=self.r.journal.path.read_bytes()
  v=self.call('status',{'batch_id':b['batch_id']});self.assertEqual(v['state'],'paused');self.assertEqual(v['verified_messages'],10);self.assertEqual(v['remaining_messages'],1);self.assertTrue(v['can_continue']);self.assertEqual(before,self.r.journal.path.read_bytes())
 def test_foreign_preparation_id_cannot_continue_or_retarget(self):
  self.call('prepare',{'uids':list(range(1,12))});before=self.r.journal.path.read_bytes()
  with self.assertRaises(Refused):self.call('prepare',{'batch_id':'f'*64})
  self.assertEqual(before,self.r.journal.path.read_bytes())
 def test_browser_preview_escapes_html(self):
  from move_web import render
  b=self.prepared();m=copy.deepcopy(b['manifest']);m['moves'][0]['preview']={'subject':'<script>evil()</script>'}
  body=render({'manifest':m,'expires':m['expires'],'fingerprint':b['fingerprint'],'state':'view-only'},self.owner,'nonce',None).body.decode()
  self.assertNotIn('<script>evil()</script>',body);self.assertIn('&lt;script&gt;',body)
 def test_execution_deadline_expiring_after_ack_keeps_receipt_no_next_move(self):
  b=self.prepared();self.approve(b);fetch=self.box.fetch
  def delayed(folder,*args):
   result=fetch(folder,*args)
   if folder!='INBOX':self.now=b['manifest']['execution_deadline']+1
   return result
  with patch.object(self.box,'fetch',side_effect=delayed),self.assertRaises(Refused):self.execute(b)
  v=self.raw(b);self.assertEqual(v['state'],'blocked');self.assertEqual(len(v['attempts']),1);self.assertEqual(v['attempts'][0]['state'],'verified');self.assertEqual(self.box.moves,[1])
 def test_schema_accepts_exact_200_and_preparation_continuation_only(self):
  import asyncio,os,jsonschema
  from mcp.server.fastmcp import FastMCP
  from move_connection import register
  with patch.dict(os.environ,{'INBOXTETHER_MOVES':'1','INBOXTETHER_MOVE_SOCKET':'/synthetic.sock'}):
   server=FastMCP('synthetic');register(server)
  schema=asyncio.run(server.list_tools())[0].inputSchema;validator=jsonschema.Draft202012Validator(schema)
  self.assertTrue(validator.is_valid({'action':'prepare','payload':{'uids':list(range(1,201))}}));self.assertTrue(validator.is_valid({'action':'prepare','payload':{'batch_id':'a'*64}}))
  for payload in ({'uids':list(range(1,202))},{'batch_id':'a'*64,'approved':True},{'uids':[True]},{'batch_id':'a'*64,'uids':[1]}):self.assertFalse(validator.is_valid({'action':'prepare','payload':payload}))

class BulkSocketTests(BulkFixture,unittest.IsolatedAsyncioTestCase):
 async def test_200_through_existing_mcp_and_peer_broker_one_consent(self):
  import os,threading,contextlib
  from mcp.server.fastmcp import FastMCP
  from move_broker import MoveBroker
  from move_connection import register
  @contextlib.contextmanager
  def context():
   # This synthetic fixture already holds the actual account lock throughout.
   yield self.s
  broker=MoveBroker(context,os.geteuid()+101,os.geteuid()+102,self.owner);broker.reader_uid=os.geteuid();broker.allowed_uids=(os.geteuid()+101,os.geteuid())
  run=self.root/'run';run.mkdir(mode=0o750);path=run/'bulk.sock';server=broker.server(path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   mcp=FastMCP('existing-connection')
   with patch.dict(os.environ,{'INBOXTETHER_MOVES':'1','INBOXTETHER_MOVE_SOCKET':str(path)}):register(mcp)
   async def rpc(action,payload):
    result=await mcp.call_tool('organize_email',{'action':action,'payload':payload})
    value=result[1] if isinstance(result,tuple) else json.loads(next(x.text for x in result if x.type=='text'))
    self.assertNotIn('error',value);return value
   b=await rpc('prepare',{'uids':list(range(1,201))});calls=1
   while b['state']=='preparing':b=await rpc('prepare',{'batch_id':b['batch_id']});calls+=1
   self.assertEqual(calls,20);self.assertEqual(b['total_messages'],200);self.assertEqual(len(b['manifest']['moves']),200)
   self.box.journal=self.r.batch(b['batch_id'])
   self.now+=23*3600  # delayed owner review through the real synthetic MCP/broker path
   a=await rpc('consent',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint'],'decision':'approved'});self.assertEqual(a['method'],CHAT)
   for i in range(20):
    result=await rpc('execute',{'batch_id':b['batch_id']});self.assertEqual(result['verified_messages'],10*(i+1));self.assertEqual(result['receipt_offset'],10*i);self.assertNotIn('manifest',result)
   self.assertEqual(result['state'],'completed');self.assertEqual(self.box.moves,list(range(1,201)))
  finally:server.shutdown();server.server_close();thread.join();path.unlink(missing_ok=True)
