"""Fixed public codes only. Never return/log raw exceptions or message content."""
import re
from journal import Refused
CODES=frozenset(('selection_invalid','selection_expired','selection_stale','selection_consumed','selection_blocked','selection_capacity','selection_empty','invalid_payload','cursor_stale','not_classified','customer_or_keep','not_client_accepted','source_excluded','external_claim','source_attempted','source_reserved','source_restored','preference_binding_missing','preference_binding_invalid','preference_changed','decision_invalid','preparation_conflict','preparation_unknown','preparation_expired','classification_changed','baseline_changed','source_identity_changed','destination_identity_changed','source_missing','source_evidence_changed','policy_validation_failed','source_validation_failed','source_bytes_invalid','authorization_denied','execution_disabled','guard_refused','state_unavailable','internal_error','transport_unavailable','execution_budget_insufficient','review_unavailable','approval_required','consent_invalid','start_deadline_expired','execution_uncertain'))
STAGES=frozenset(('selection','authorization','context','request','pagination','eligibility','preparation','source_validation','consent','execution','transport','state'))
HEX=re.compile(r'^[0-9a-f]{64}$')
MAPPED={
 'Insufficient manifest lifetime for full remaining batch; no MOVE authorized':'execution_budget_insufficient',
 'Exact unexpired review required':'review_unavailable',
 'Review preference revision changed; prepare fresh':'preference_changed',
 'Batch has no approval':'approval_required',
 'Exact bulk consent required':'consent_invalid',
 'Exact configured consent record required':'consent_invalid',
 'Approval start deadline expired':'start_deadline_expired',
 'Uncertain bulk MOVE; stop, no retry or continuation':'execution_uncertain',
 'Object payload required':'invalid_payload',
 'Exact batch UIDs':'invalid_payload',
 'Exact 1..200 distinct UIDs required':'invalid_payload',
 'No next arguments':'invalid_payload',
 'Unsupported operation or approval field':'invalid_payload',
 'Explicit decision required':'invalid_payload',
 'Mailbox execution disabled':'execution_disabled',
 'Inbox identity changed':'source_identity_changed',
 'Source identity changed':'source_identity_changed',
 'Destination identity changed':'destination_identity_changed',
 'Source disappeared':'source_missing',
 'Source content or flags changed':'source_evidence_changed',
 'Source changed during validation':'source_evidence_changed',
 'Customer, identity, uncertainty or classification veto':'policy_validation_failed',
 'Invalid raw digest':'source_bytes_invalid',
 'Ledger/witness/config baseline changed':'baseline_changed',
 'Configuration or source baseline changed; stop for reconciliation':'baseline_changed',
 'Candidate discovery requires initialized state':'state_unavailable',
}
def public_error(code,stage,*,uid=None,preparation_id=None):
 code=code if type(code) is str and code in CODES else 'internal_error';stage=stage if type(stage) is str and stage in STAGES else 'request'
 result={'error_code':code,'stage':stage,'retry_allowed':False,'next_action':'inspect_saved_state'}
 if type(uid) is int and 0<uid<=4294967295:result['failed_uid']=uid
 if type(preparation_id) is str and HEX.fullmatch(preparation_id):result['preparation_id']=preparation_id
 if code=='cursor_stale':result['next_action']='start_new_candidate_snapshot'
 if code.startswith('preference_'):result['next_action']='select_compatible_candidates'
 return result
class OrganizationError(Refused):
 def __init__(self,code,stage,*,uid=None,preparation_id=None):
  self.public=public_error(code,stage,uid=uid,preparation_id=preparation_id)
  super().__init__(self.public['error_code'])
def translate(exc,stage,*,uid=None,preparation_id=None):
 if isinstance(exc,OrganizationError):
  p=exc.public
  return OrganizationError(p['error_code'],p['stage'],uid=p.get('failed_uid',uid),preparation_id=p.get('preparation_id',preparation_id))
 code=MAPPED.get(str(exc),'guard_refused') if isinstance(exc,Refused) else 'internal_error'
 if stage=='source_validation' and code=='guard_refused':code='source_validation_failed'
 return OrganizationError(code,'execution' if code=='execution_disabled' else stage,uid=uid,preparation_id=preparation_id)
def frontend_error(value):
 """Treat even broker metadata as constrained input; no arbitrary strings escape."""
 if type(value) is not dict or type(value.get('error_code')) is not str or value.get('error_code') not in CODES or type(value.get('stage')) is not str or value.get('stage') not in STAGES:
  value=public_error('internal_error','transport')
 clean=public_error(value['error_code'],value['stage'],uid=value.get('failed_uid'),preparation_id=value.get('preparation_id'))
 return {'error':'Organization refused; inspect saved state. Do not retry execution.',**clean}
