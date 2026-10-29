"""Synthetic only: delayed owner review, exact consent and guarded expiration."""
import copy,unittest
from unittest.mock import patch
from test_bulk_moves import BulkFixture
from journal import Refused,digest

class PracticalDeadlineTests(BulkFixture):
 def test_one_four_eleven_and_200_have_one_day_review_six_hour_tail(self):
  for n in (1,4,11,200):
   with self.subTest(n=n):
    b=self.prepared(n);m=b['manifest'];self.assertEqual(m['expires']-m['created'],86400);self.assertEqual(m['execution_deadline']-m['created'],108000)
    self.assertEqual(len(m['moves']),n);self.assertEqual(self.box.moves,[])
    self.call('cancel',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint']})
 def test_approve_after_23_hours_start_with_six_hours_remaining_one_consent(self):
  b=self.prepared(200);self.now=b['manifest']['expires']-1;self.approve(b);approval=copy.deepcopy(self.raw(b)['approval']);self.execute(b);self.now+=2
  for unused in range(19):v=self.execute(b)
  self.assertEqual(v['state'],'completed');self.assertEqual(v['verified_messages'],200);self.assertEqual(self.raw(b)['approval'],approval);self.assertEqual(len(self.box.moves),200)
 def test_approval_does_not_renew_start_or_execution_deadline(self):
  b=self.prepared();original=copy.deepcopy(b['manifest']);self.now+=23*3600;self.approve(b);self.assertEqual(self.raw(b)['manifest'],original)
  self.now=original['expires']
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.raw(b)['attempts'],[])
 def test_changed_sources_after_overnight_review_are_not_moved(self):
  b=self.prepared();self.now+=23*3600;self.approve(b);self.box.source[1].flags=['\\Seen']
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[]);self.assertEqual(self.raw(b)['attempts'],[])
 def test_late_customer_guard_still_vetoes_approved_batch(self):
  b=self.prepared(4);self.now+=23*3600;self.approve(b);self.policy.veto=True
  with self.assertRaises(Refused):self.execute(b)
  self.assertEqual(self.box.moves,[])
 def test_expired_unapproved_and_approved_reviews_retire_on_fresh_prepare(self):
  b=self.prepared();self.approve(b);old=copy.deepcopy(self.raw(b));decisions=copy.deepcopy(self.r.read()['workflow']);self.now=b['manifest']['expires']
  fresh=self.prepared();retired=self.raw(b);expected=copy.deepcopy(old);expected['state']='expired';self.assertEqual(retired,expected)
  self.assertNotEqual(fresh['batch_id'],b['batch_id']);self.assertIsNone(fresh['approval']);self.assertEqual(self.r.read()['workflow'],decisions)
  with self.assertRaises(Refused):self.execute(fresh)
  self.assertEqual(self.box.moves,[])
 def test_exact_expired_cancel_succeeds_and_wrong_fingerprint_does_not_write(self):
  b=self.prepared();self.approve(b);self.now=b['manifest']['expires'];before=self.r.journal.path.read_bytes()
  with self.assertRaises(Refused):self.call('cancel',{'batch_id':b['batch_id'],'fingerprint':'f'*64})
  self.assertEqual(before,self.r.journal.path.read_bytes());v=self.call('cancel',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint']});self.assertEqual(v['state'],'expired')
  self.r.available(11,'f'*64);again=self.r.journal.path.read_bytes();self.call('cancel',{'batch_id':b['batch_id'],'fingerprint':b['fingerprint']});self.assertEqual(again,self.r.journal.path.read_bytes())
 def test_expired_partial_preparation_retains_entries_releases_scope(self):
  p=self.call('prepare',{'uids':list(range(1,12))});original=copy.deepcopy(self.r.read()['bulk_preparations'][p['batch_id']]);self.now=p['expires']
  fresh=self.prepared();old=self.r.read()['bulk_preparations'][p['batch_id']];expected=copy.deepcopy(original);expected['state']='cancelled';self.assertEqual(old,expected);self.assertNotEqual(p['batch_id'],fresh['batch_id'])
 def test_expired_blocked_preparation_can_be_retired_without_reclassification(self):
  self.policy.veto=True
  with self.assertRaises(Refused):self.prepared()
  v=self.r.read();key=next(iter(v['bulk_preparations']));original=copy.deepcopy(v);self.now=v['bulk_preparations'][key]['plan']['expires'];self.r.retire_expired(self.now);original['bulk_preparations'][key]['state']='cancelled';self.assertEqual(self.r.read(),original)
 def test_never_retire_verified_prefix_or_uncertainty_or_any_claim(self):
  b=self.prepared();self.approve(b);self.execute(b);self.now=b['manifest']['execution_deadline']+1;before=self.r.journal.path.read_bytes();self.r.retire_expired(self.now);self.assertEqual(before,self.r.journal.path.read_bytes())
  with self.assertRaises(Refused):self.r.available(1,'f'*64)
 def test_uncertain_claim_permanent_after_expiration(self):
  b=self.prepared();self.approve(b);self.box.failure='before-ack'
  with self.assertRaises(Refused):self.execute(b)
  self.now=b['manifest']['execution_deadline']+1;before=self.r.journal.path.read_bytes();self.r.retire_expired(self.now);self.assertEqual(before,self.r.journal.path.read_bytes())
  with self.assertRaises(Refused):self.r.available(1,'f'*64)
 def test_expiration_write_failure_preserves_old_journal_and_no_move(self):
  b=self.prepared();self.now=b['manifest']['expires'];before=self.r.journal.path.read_bytes()
  with patch.object(self.r.journal,'write',side_effect=OSError('synthetic disk failure')),self.assertRaises(OSError):self.r.retire_expired(self.now)
  self.assertEqual(before,self.r.journal.path.read_bytes());self.assertEqual(self.box.moves,[])
 def test_all_expired_overlapping_records_retire_in_one_atomic_write(self):
  b=self.prepared();v=self.r.read();other='f'*64;v['batches'][other]=copy.deepcopy(v['batches'][b['batch_id']]);self.r.journal.write(v);self.now=b['manifest']['expires']
  with patch.object(self.r.journal,'write',wraps=self.r.journal.write) as write:self.r.retire_expired(self.now);self.assertEqual(write.call_count,1)
  self.r.available(1,'e'*64);self.assertEqual(self.box.moves,[])
 def test_legacy_bulk_and_small_approval_windows_not_extended(self):
  b=self.prepared();v=self.r.read();old=v['batches'][b['batch_id']];m=old['manifest'];m['expires']=m['created']+1800;m['execution_deadline']=m['expires']+21600;old['fingerprint']=digest(m);self.r.journal.write(v)
  self.now=m['expires'];before=self.r.journal.path.read_bytes()
  with self.assertRaises(Refused):self.call('consent',{'batch_id':b['batch_id'],'fingerprint':old['fingerprint'],'decision':'approved'})
  self.assertEqual(before,self.r.journal.path.read_bytes())
 def test_started_expired_budget_cannot_be_retired_or_freshly_prepared(self):
  b=self.prepared();self.approve(b);self.execute(b);self.now=b['manifest']['execution_deadline']+1;before=self.r.journal.path.read_bytes()
  with self.assertRaises(Refused):self.prepared()
  self.assertEqual(before,self.r.journal.path.read_bytes())
 def test_small_batch_browser_fallback_same_manifest_one_approval(self):
  b=self.prepared(4);self.now+=23*3600;self.approve(b,'browser');result=self.execute(b);self.assertEqual(result['state'],'completed');self.assertEqual(result['verified_messages'],4)
 def test_only_target_expired_batch_cancelled(self):
  a=self.prepared(4);b=self.call('prepare',{'uids':[5,6,7,8]});self.now=a['manifest']['expires'];other_before=copy.deepcopy(self.raw(b));self.call('cancel',{'batch_id':a['batch_id'],'fingerprint':a['fingerprint']});self.assertEqual(self.raw(b),other_before)
 def test_partial_expiration_write_is_quarantined_no_retry_or_history_restore(self):
  b=self.prepared();self.now=b['manifest']['expires'];before=self.r.journal.path.read_bytes()
  def interrupted(value):
   (self.root/'operation.next').write_bytes(b'{"incomplete":');raise OSError('synthetic interrupted write')
  with patch.object(self.r.journal,'write',side_effect=interrupted),self.assertRaises(OSError):self.r.retire_expired(self.now)
  self.assertEqual(before,self.r.journal.path.read_bytes())
  with self.assertRaises(Refused):self.r.read()
  self.assertEqual(self.box.moves,[])
 def test_forged_expiration_fingerprint_refuses_retirement(self):
  b=self.prepared();v=self.r.read();v['batches'][b['batch_id']]['fingerprint']='f'*64
  # A corrupted ready record is rejected on read; never repair or overwrite it.
  self.r.journal.write(v);self.now=b['manifest']['expires'];before=self.r.journal.path.read_bytes()
  with self.assertRaises(Refused):self.r.retire_expired(self.now)
  self.assertEqual(before,self.r.journal.path.read_bytes())
