"""Synthetic copies of observed record SHAPES, plus real classifier-produced bindings.
No production identifiers, headers, bytes, state files or credentials are loaded.
"""
import copy,json,unittest
from pathlib import Path
from journal import Refused,digest
from organization_errors import OrganizationError
from automatic_filing import clear_customer_risk,FOLDERS
import test_automatic_filing as automatic_tests
import test_client_native as native_tests

class RiskShapeTests(unittest.TestCase):
 def setUp(self):self.records=json.loads(Path(__file__).with_name('sanitized_saved_record_shapes.json').read_text())
 def test_observed_bound_and_legacy_shapes(self):
  for name,record in self.records.items():
   with self.subTest(name=name):self.assertEqual(clear_customer_risk(record),name in ('accepted_bound','accepted_legacy_without_preference_binding','accepted_one_message_binding'))
 def test_missing_malformed_and_uncertain_risk_is_closed(self):
  good=self.records['accepted_bound']
  for risk in (None,False,True,0,1,[],{},'possible','customer','CLEAR','unknown',''):
   with self.subTest(risk=risk):
    d=copy.deepcopy(good);d['classification']['reply']['customer_risk']=risk;self.assertFalse(clear_customer_risk(d))
  for bad in (None,[],False,'clear',{},1):
   with self.subTest(binding=bad):
    d=copy.deepcopy(good);d['classification']=bad;self.assertFalse(clear_customer_risk(d))
    d=copy.deepcopy(good);d['classification']['reply']=bad;self.assertFalse(clear_customer_risk(d))
  d=copy.deepcopy(good);del d['classification']['reply']['customer_risk'];self.assertFalse(clear_customer_risk(d))
 def test_no_flat_field_fallback_or_uncertainty_override(self):
  d=copy.deepcopy(self.records['accepted_bound']);d['classification']['customer_risk']='clear';d['classification']['reply']['customer_risk']='possible';self.assertFalse(clear_customer_risk(d))
  del d['classification']['reply'];self.assertFalse(clear_customer_risk(d))

class SavedSelectionTests(automatic_tests.AutomaticTests):
 # Inherit the complete automatic-policy regression suite using corrected fixtures.
 def test_missing_risk_records_excluded_without_reservations(self):
  v=self.r.read()
  for u in v['workflow']['decisions']:v['workflow']['decisions'][u]['classification']['reply'].pop('customer_risk')
  self.r.journal.write(v);before=self.r.journal.path.read_bytes()
  with self.assertRaises(OrganizationError) as e:self.call('candidates',{'select_count':200,'filing_mode':'automatic'})
  self.assertEqual(e.exception.public['error_code'],'selection_empty');self.assertEqual(before,self.r.journal.path.read_bytes());self.assertEqual(self.box.moves,[])
 def test_legacy_missing_preference_binding_is_not_fabricated(self):
  v=self.r.read();v['workflow']['decisions']['1'].pop('owner_preference_binding');self.r.journal.write(v)
  s=self.call('candidates',{'select_count':1,'filing_mode':'automatic'});self.assertEqual(self.r.read()['candidate_selections'][s['selection_ref']]['plan']['scope'][0][0],2);self.assertNotIn('owner_preference_binding',self.r.read()['workflow']['decisions']['1'])
 def test_execution_rechecks_missing_or_uncertain_nested_risk(self):
  from automatic_filing import authorize
  b=self.prepared_auto(1);original=copy.deepcopy(self.r.read());row=self.s.status(b['batch_id']);authorize(self.s,row);u=row['manifest']['moves'][0]['uid']
  for risk in (None,'possible','customer',True):
   v=copy.deepcopy(original);d=v['workflow']['decisions'][str(u)];d['classification']['reply']['customer_risk']=risk;entry=copy.deepcopy(row);entry['manifest']['moves'][0]['decision_sha256']=digest(d);self.r.journal.write(v)
   with self.assertRaises(Refused):authorize(self.s,entry)
   self.assertEqual(self.box.moves,[])
  self.r.journal.write(original)
 def test_preserved_keeps_and_uncertain_uncertain_claim_remain_unchanged(self):
  from test_mailbox import Message
  value=self.r.read();template=copy.deepcopy(value['workflow']['decisions']['1']);keep_uids=list(range(1,202))+list(range(10000,10854))
  value['workflow']['inventory']=keep_uids+[777]
  value['workflow']['decisions']={str(u):{'uid':u,'category':None,'customer':u%3==0,'move_eligible':False,'classification_origin':'automatic_keep','reason':'customer-protected' if u%3==0 else 'owner-kept'} for u in keep_uids}
  def accepted(u):return {**copy.deepcopy(template),**self.box.source[u].evidence()}
  self.box.source[777]=Message(777);value['workflow']['decisions']['777']=accepted(777);self.r.journal.write(value)
  b=self.prepared_auto(1);self.box.failure='interrupt'
  with self.assertRaises(Refused):self.execute(b)
  original=copy.deepcopy(self.r.read());prior_batch=copy.deepcopy(self.raw(b));self.assertEqual(prior_batch['attempts'][0]['uid'],777);self.assertEqual(prior_batch['attempts'][0]['state'],'uncertain')
  old_claim_attempt_count=self.box.moves.count(777)
  self.box.failure=None;self.box.source[2000]=Message(2000);v=self.r.read();v['workflow']['inventory'].append(2000);v['workflow']['decisions']['2000']=accepted(2000);self.r.journal.write(v)
  fresh=self.prepared_auto(1);self.assertEqual(self.raw(fresh)['manifest']['moves'][0]['uid'],2000);self.execute(fresh)
  now=self.r.read();self.assertEqual(self.raw(b),prior_batch);self.assertEqual({str(u):now['workflow']['decisions'][str(u)] for u in keep_uids},{str(u):original['workflow']['decisions'][str(u)] for u in keep_uids});self.assertEqual(len(keep_uids),1055)
  self.assertEqual(self.box.moves.count(777),old_claim_attempt_count);self.assertEqual(self.box.moves[-1],2000)

class ActualClassifierTests(native_tests.NativeFixture):
 def setUp(self):
  super().setUp();self.service.automatic_policy=lambda:{'enabled':True,'execution_enabled':True,'fingerprint':'a'*64,'folders':list(FOLDERS)}
 def proposal(self,category,risk='clear',reason='promotion'):
  p=self.call('next');return self.call('propose',{'uid':p['uid'],'request_id':p['request_id'],'request_fingerprint':p['request_fingerprint'],'category':category,'customer_risk':risk,'reason':reason})
 def auto_batch(self):
  s=self.call('candidates',{'select_count':200,'filing_mode':'automatic'});return self.call('prepare',{'selection_ref':s['selection_ref']})
 def test_real_classifier_to_saved_binding_to_automatic_execution_all_four_folders(self):
  reasons={'Industry':'industry-publication','Marketing':'promotion','Orders':'vendor-purchase','Suppliers':'supplier-notice'}
  for category,reason in reasons.items():
   with self.subTest(category=category):
    case=ActualClassifierTests();case.setUp()
    try:
     result=case.proposal(category,reason=reason);case.assertTrue(result['move_eligible'])
     with case.registry:d=case.service.load()['workflow']['decisions']['1']
     case.assertEqual(set(d['classification']),{'mode','classifier','packet_sha256','reply','request_id','request_fingerprint'});case.assertNotIn('customer_risk',d['classification']);case.assertEqual(d['classification']['reply']['customer_risk'],'clear')
     b=case.auto_batch();out=case.execute(b);case.assertEqual(out['state'],'completed');case.assertIsNone(out['approval']);case.assertEqual(case.box.moves,[('INBOX',1,category)]);case.assertEqual(out['attempts'][0]['flags'],d['flags'])
    finally:case.doCleanups()
 def test_real_review_classification_is_kept_out_of_automatic_mode(self):
  self.assertTrue(self.proposal('Review',reason='owner-review')['move_eligible'])
  with self.registry:before=copy.deepcopy(self.service.load()['workflow']['decisions']['1'])
  with self.assertRaises(OrganizationError):self.auto_batch()
  with self.registry:self.assertEqual(self.service.load()['workflow']['decisions']['1'],before)
  self.assertIn(1,self.box.source);self.assertEqual(self.box.moves,[])
 def test_real_uncertain_reply_remains_keep(self):
  out=self.proposal('Marketing',risk='possible',reason='uncertain');self.assertFalse(out['move_eligible']);self.assertEqual(out['category'],'Inbox / Keep')
  with self.assertRaises(OrganizationError):self.auto_batch()
  self.assertEqual(self.box.moves,[])
 def test_real_customer_automatic_keep_not_reclassified_or_filed(self):
  self.proposal('Suppliers',reason='supplier-notice');keep=self.call('next');self.assertEqual(keep['uid'],2);self.assertEqual(keep['origin'],'automatic_keep')
  with self.registry:before=copy.deepcopy(self.service.load()['workflow']['decisions']['2'])
  b=self.auto_batch();self.assertEqual([e['uid'] for e in self.call('status',{'batch_id':b['batch_id']})['manifest']['moves']],[1]);self.execute(b)
  with self.registry:self.assertEqual(self.service.load()['workflow']['decisions']['2'],before)
  self.assertIn(2,self.box.source)
