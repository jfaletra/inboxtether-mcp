"""Synthetic batch deadlines only; no real email, accounts or production state."""
import copy
from unittest.mock import patch
from test_move_integration import Fixture
from journal import Refused
from registry import Registry
from batch_moves import EXECUTION_SECONDS_PER_MESSAGE as PER,EXECUTION_FINAL_MARGIN_SECONDS as MARGIN

class DeadlineTests(Fixture):
 def approved(self,two=True):
  self.classify()
  if two:self.call('next');self.classify()
  b=self.call('prepare',{'uids':[1,3] if two else [1]});self.decide(b)
  return b
 def state(self,b):
  with self.registry:return self.registry.batch(b['batch_id']).read()
 def remaining(self,b,seconds):self.now=b['manifest']['expires']-seconds
 def test_two_messages_require_full_batch_window_before_any_claim(self):
  b=self.approved();before=self.state(b);self.remaining(b,MARGIN+2*PER-1)
  with self.assertRaisesRegex(Refused,'execution_budget_insufficient'):self.execute(b)
  self.assertEqual(self.state(b),before);self.assertEqual(self.box.moves,[])
 def test_exact_threshold_allows_verified_two_message_batch(self):
  b=self.approved();self.remaining(b,MARGIN+2*PER)
  result=self.execute(b);self.assertEqual(result['state'],'completed');self.assertEqual(self.box.moves,[1,3]);self.assertTrue(all(a['state']=='verified' for a in result['attempts']))
 def test_one_message_budget_scales(self):
  b=self.approved(False);self.remaining(b,MARGIN+PER-1)
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.state(b)['attempts'],[]);self.assertEqual(self.box.moves,[])
 def test_full_preflight_consuming_window_refuses_without_claim(self):
  b=self.approved();before=self.state(b);self.remaining(b,MARGIN+2*PER+1)
  raw=self.box.raw_digest
  def slow(*a):
   result=raw(*a);self.now+=1;return result
  with patch.object(self.box,'raw_digest',side_effect=slow),self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.state(b),before);self.assertEqual(self.box.moves,[])
 def test_final_source_check_consuming_window_has_no_move_claim(self):
  b=self.approved();self.remaining(b,MARGIN+2*PER+1);fetch=self.box.fetch;count=0
  def slow(*a):
   nonlocal count
   result=fetch(*a);count+=1
   if count==5:self.now+=2 # after full two-source preflight, in first per-move snapshot
   return result
  with patch.object(self.box,'fetch',side_effect=slow),self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.state(b)['attempts'],[]);self.assertEqual(self.box.moves,[])
 def test_move_boundary_lost_window_preserves_claim_no_retry(self):
  b=self.approved();original=self.box.move
  def delayed(uv,uid,cat,dest,**kw):
   self.now=b['manifest']['expires']-1
   kw['on_prepared'](self.box.raw_digest('INBOX',uv,uid,80))
   return original(uv,uid,cat,dest,**kw)
  with patch.object(self.box,'move',side_effect=delayed),self.assertRaises(Refused):self.execute(b)
  state=self.state(b);self.assertEqual(state['state'],'uncertain');self.assertEqual([a['uid'] for a in state['attempts']],[1]);self.assertEqual(self.box.moves,[])
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[])
 def test_expiration_during_verification_preserves_first_receipt_stops_second(self):
  b=self.approved();fetch=self.box.fetch
  def slow(name,*a):
   result=fetch(name,*a)
   if name!='INBOX':self.now=b['manifest']['expires']+1
   return result
  with patch.object(self.box,'fetch',side_effect=slow),self.assertRaises(Refused):self.execute(b)
  state=self.state(b);self.assertEqual(self.box.moves,[1]);self.assertEqual(state['attempts'][0]['state'],'verified');self.assertEqual(state['state'],'blocked');self.assertIn(3,self.box.source)
 def test_positive_but_insufficient_remaining_time_stops_next_move(self):
  b=self.approved();fetch=self.box.fetch
  def slow(name,*a):
   result=fetch(name,*a)
   if name!='INBOX':self.now=b['manifest']['expires']-(MARGIN+PER-1)
   return result
  with patch.object(self.box,'fetch',side_effect=slow),self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[1]);self.assertEqual(len(self.state(b)['attempts']),1)
 def test_interrupted_move_recovery_preserves_uncertain_claim(self):
  b=self.approved();self.box.failure='interrupt'
  with self.assertRaises(Refused):self.execute(b)
  before=self.state(b);self.assertEqual(before['state'],'uncertain')
  self.registry=Registry(self.root,self.registry.identity);self.service.registry=self.registry
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.state(b),before);self.assertEqual(self.box.moves,[1])
 def test_refusal_never_extends_expiration_or_changes_approval(self):
  b=self.approved();before=self.state(b);self.remaining(b,1)
  with self.assertRaises(Refused):self.execute(b)
  after=self.state(b);self.assertEqual(after['manifest'],before['manifest']);self.assertEqual(after['approval'],before['approval']);self.assertEqual(after['attempts'],[])
 def test_no_browser_approval_cannot_use_extra_time_as_authority(self):
  b=self.batch()
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[])
 def test_mapping_survives_verification_failure_and_restart(self):
  b=self.approved();self.box.failure='raw-destination'
  with self.assertRaises(Refused):self.execute(b)
  before=self.state(b);self.assertEqual(before['attempts'][0]['mapping']['uid'],1001);self.assertEqual(before['attempts'][0]['state'],'uncertain')
  self.registry=Registry(self.root,self.registry.identity);self.service.registry=self.registry
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.state(b),before);self.assertEqual(self.box.moves,[1])
