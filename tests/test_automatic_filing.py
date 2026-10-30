"""Synthetic policy authority and unchanged mailbox protections only."""
import asyncio,contextlib,copy,io,json,os,sys,threading,unittest
from unittest.mock import patch
from pathlib import Path
from test_bulk_moves import BulkFixture
from journal import Refused,digest
from automatic_filing import FOLDERS,policy

class AutomaticTests(BulkFixture):
 def setUp(self):
  super().setUp();self.gate=True;self.enabled=True;self.revision='a'*64
  self.s.automatic_policy=lambda:{'enabled':self.enabled,'execution_enabled':self.gate,'fingerprint':self.revision,'folders':list(FOLDERS)}
 def prepared_auto(self,n=11):
  selection=self.call('candidates',{'select_count':n,'filing_mode':'automatic'});b=self.call('prepare',{'selection_ref':selection['selection_ref']})
  while b['state']=='preparing':b=self.call('prepare',{'batch_id':b['batch_id']})
  return b
 def test_disabled_by_default_and_no_tool_activation(self):
  del self.s.automatic_policy
  self.assertFalse(self.call('automatic_policy',{})['enabled'])
  with self.assertRaises(Refused):self.prepared_auto()
  with self.assertRaises(Refused):self.call('automatic_policy',{'enabled':True})
  self.assertEqual(self.box.moves,[])
 def test_automatic_chunks_without_fabricating_chat_or_browser_consent(self):
  b=self.prepared_auto(21);self.assertIsNone(self.raw(b)['approval'])
  for count,state in ((10,'paused'),(20,'paused'),(21,'completed')):
   v=self.execute(b);self.assertEqual(v['state'],state);self.assertEqual(v['verified_messages'],count);self.assertIsNone(v['approval']);self.assertFalse(v['automatic_authorization']['independent_per_batch_human_approval'])
  raw=self.raw(b);self.assertEqual(raw['automatic_authorization']['method'],'owner-enabled-automatic-policy');self.assertEqual(raw['automatic_authorization']['manifest_fingerprint'],b['fingerprint']);self.assertEqual(self.box.moves,list(range(1,22)))
  self.assertTrue(all(a['flags']==e['evidence']['flags'] and a['raw_sha256']==e['raw_sha256'] for a,e in zip(raw['attempts'],raw['manifest']['moves'])))
  with self.assertRaises(Refused):self.execute(b)
 def test_review_customer_uncertainty_and_automatic_keeps_are_not_selected(self):
  v=self.r.read()
  v['workflow']['decisions']['1']['category']='Review';v['workflow']['decisions']['2']['customer']=True;v['workflow']['decisions']['3']['move_eligible']=False;v['workflow']['decisions']['4']['classification_origin']='automatic_keep';v['workflow']['decisions']['5']['classification']['reply']['customer_risk']='possible';self.r.journal.write(v)
  s=self.call('candidates',{'select_count':10,'filing_mode':'automatic'});p=self.r.read()['candidate_selections'][s['selection_ref']]['plan'];self.assertTrue(all(u>5 and c in FOLDERS for u,c in p['scope']));self.assertEqual(s['Review_attention_count'],1)
  self.assertEqual(self.r.read()['workflow']['decisions']['1']['category'],'Review');self.assertIn(1,self.box.source)
 def test_manual_batches_still_require_exact_owner_consent_when_policy_enabled(self):
  b=self.prepared(2)
  with self.assertRaises(Refused):self.execute(b)
  self.approve(b);self.assertEqual(self.execute(b)['state'],'completed');self.assertEqual(self.raw(b)['approval']['method'],'client-session-consent');self.assertNotIn('automatic_authorization',self.raw(b))
 def test_automatic_manifest_rejects_fabricated_per_batch_consent(self):
  b=self.prepared_auto(1)
  with self.assertRaises(Refused):self.approve(b)
  self.assertIsNone(self.raw(b)['approval'])
 def test_revocation_or_execution_disable_before_start_makes_no_attempt(self):
  b=self.prepared_auto(1)
  for field in ('enabled','gate'):
   setattr(self,field,False)
   with self.assertRaises(Refused):self.execute(b)
   self.assertEqual(self.raw(b)['attempts'],[]);setattr(self,field,True)
 def test_reenable_new_revision_cannot_resume_old_authority(self):
  b=self.prepared_auto();self.execute(b);self.revision='b'*64
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(len(self.box.moves),10)
 def test_revoke_at_wire_boundary_preserves_no_retry_claim(self):
  b=self.prepared_auto(1);original=self.box.move
  def revoked(*a,**kw):self.enabled=False;return original(*a,**kw)
  with patch.object(self.box,'move',side_effect=revoked),self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.raw(b)['state'],'uncertain');self.enabled=True
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(len(self.raw(b)['attempts']),1)
 def test_revoke_between_messages_stops_without_next_move(self):
  b=self.prepared_auto(3);fetch=self.box.fetch
  def revoke(name,*a):
   result=fetch(name,*a)
   if name!='INBOX':self.enabled=False
   return result
  with patch.object(self.box,'fetch',side_effect=revoke),self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[1]);self.assertEqual(self.raw(b)['attempts'][0]['state'],'verified')
 def test_fresh_customer_or_changed_flags_after_preparation_prevent_move(self):
  b=self.prepared_auto(1);self.policy.veto=True
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[]);self.policy.veto=False;self.box.source[1].flags=['Changed']
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[])
 def test_interrupted_move_and_wrong_destination_never_retry(self):
  for failure in ('interrupt','before-ack','mapping','dest-flags','raw-destination'):
   with self.subTest(failure=failure):
    case=AutomaticTests();case.setUp()
    try:
     case.box.source[1].flags=['\\Seen'];value=case.r.read();value['workflow']['decisions']['1']['flags']=['\\Seen'];case.r.journal.write(value)
     b=case.prepared_auto(1);case.box.failure=failure
     with case.assertRaises(Refused):case.execute(b)
     before=case.raw(b)
     with case.assertRaises(Refused):case.execute(b)
     case.assertEqual(case.raw(b),before)
    finally:case.doCleanups()
 def test_fixed_deadline_and_preference_changes_remain_guards(self):
  b=self.prepared_auto(1);self.now=b['approval_start_deadline']
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[])
 def test_selection_revocation_prevents_preparation(self):
  s=self.call('candidates',{'select_count':1,'filing_mode':'automatic'});self.enabled=False
  with self.assertRaises(Refused):self.call('prepare',{'selection_ref':s['selection_ref']})
  self.assertEqual(self.r.read().get('bulk_preparations',{}),{})
 def test_exact_folder_owner_and_pin_binding_and_invalid_policy(self):
  spec={'owner':self.owner,'automatic_filing_policy':{'enabled':True,'revision':'a'*64,'folders':list(FOLDERS)}};p=policy(spec,self.identity,self.box.pins,self.s.paths)
  pins={**self.box.pins,'Marketing':1234};self.assertNotEqual(p['fingerprint'],policy(spec,self.identity,pins,self.s.paths)['fingerprint'])
  spec['automatic_filing_policy']['folders'].append('Review')
  with self.assertRaises(Refused):policy(spec,self.identity,self.box.pins,self.s.paths)
  self.assertFalse(policy({},self.identity,self.box.pins,self.s.paths)['enabled'])

class EnrollmentTests(BulkFixture):
 def test_owner_terminal_enrollment_and_revocation_only_change_policy(self):
  import enroll_automatic_policy as entry
  class TTY(io.StringIO):
   def isatty(self):return True
  path=self.root/'synthetic-config.json';spec={'owner':self.owner,'host':'mail.example.org','account':'owner@example.org','mailboxes':{'INBOX':{'path':'INBOX','uidvalidity':123}},'execution_enabled':True};path.write_text(json.dumps(spec));path.chmod(0o644)
  from types import SimpleNamespace
  original_lstat=Path.lstat
  def root_stat(p):
   st=original_lstat(p);values=list(st);values[4]=0;return os.stat_result(values)
  for enabled,action in ((True,'ENABLE-AUTOMATIC-FILING'),(False,'REVOKE-AUTOMATIC-FILING')):
   proposed={'enabled':enabled,'revision':('a' if enabled else 'b')*64,'folders':list(FOLDERS)}
   fingerprint=digest({'owner':spec['owner'],'host':spec['host'],'account':spec['account'],'mailboxes':spec['mailboxes'],'automatic_filing_policy':proposed})
   before=copy.deepcopy(json.loads(path.read_text()))
   with patch.object(entry.os,'geteuid',return_value=0),patch.object(Path,'lstat',autospec=True,side_effect=lambda p:root_stat(p)),patch.object(entry.os,'chown'),patch.object(entry,'load_protected_json',side_effect=lambda _:json.loads(path.read_text())),patch.object(sys,'argv',['enroll','--config',str(path),'--enable' if enabled else '--disable']),patch.object(sys,'stdin',TTY(action+' '+fingerprint+'\n')),patch.object(sys,'stdout',TTY()),patch.object(entry.secrets,'token_hex',return_value=proposed['revision']):entry.main()
   updated=json.loads(path.read_text());self.assertEqual(updated,{**before,'automatic_filing_policy':proposed});self.assertTrue(updated['execution_enabled']);self.assertEqual(path.stat().st_mode&0o777,0o644)
  self.assertEqual(self.box.moves,[])
 def test_noninteractive_activation_refused_without_changes(self):
  import enroll_automatic_policy as entry
  path=self.root/'unused.json'
  with patch.object(sys,'argv',['enroll','--config',str(path),'--enable']),patch.object(sys,'stdin',io.StringIO()),self.assertRaises(Refused):entry.main()
  self.assertFalse(path.exists())

class AutomaticSocketTests(BulkFixture,unittest.IsolatedAsyncioTestCase):
 async def test_existing_mcp_broker_policy_inspection_and_automatic_chunks(self):
  from mcp.server.fastmcp import FastMCP
  from move_broker import MoveBroker
  from move_connection import register
  self.s.automatic_policy=lambda:{'enabled':True,'execution_enabled':True,'fingerprint':'a'*64,'folders':list(FOLDERS)}
  @contextlib.contextmanager
  def context(read_only=False):yield self.s
  broker=MoveBroker(context,os.geteuid()+101,os.geteuid()+102,self.owner);broker.reader_uid=os.geteuid();broker.allowed_uids=(os.geteuid()+101,os.geteuid());run=self.root/'run';run.mkdir(mode=0o750);path=run/'automatic.sock';server=broker.server(path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   mcp=FastMCP('existing-connection')
   with patch.dict(os.environ,{'INBOXTETHER_MOVES':'1','INBOXTETHER_MOVE_SOCKET':str(path)}):register(mcp)
   async def rpc(action,payload):
    out=await mcp.call_tool('organize_email',{'action':action,'payload':payload})
    return out[1] if isinstance(out,tuple) else json.loads(next(x.text for x in out if x.type=='text'))
   p=await rpc('automatic_policy',{});self.assertTrue(p['enabled']);self.assertFalse(p['activation_via_MCP'])
   s=await rpc('candidates',{'select_count':11,'filing_mode':'automatic'});b=await rpc('prepare',{'selection_ref':s['selection_ref']})
   self.assertEqual(b['state'],'preparing');b=await rpc('prepare',{'batch_id':b['batch_id']});self.assertIsNone(self.raw(b)['approval'])
   self.box.journal=self.r.batch(b['batch_id'])
   out=await rpc('execute',{'batch_id':b['batch_id']});self.assertIn('state',out,out);self.assertEqual(out['state'],'paused');self.assertEqual(out['verified_messages'],10)
   out=await rpc('execute',{'batch_id':b['batch_id']});self.assertEqual(out['state'],'completed');self.assertEqual(out['verified_messages'],11);self.assertIsNone(self.raw(b)['approval']);self.assertEqual(self.box.moves,list(range(1,12)))
  finally:server.shutdown();server.server_close();thread.join();path.unlink(missing_ok=True)
