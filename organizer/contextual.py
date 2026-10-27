"""Bounded synthetic/explicitly approved sanitized-context packets. Sends nothing."""
from dataclasses import dataclass
from .hybrid import model_packet,shadow_review

@dataclass(frozen=True)
class ApprovedContext:
    text: str
    authorization: str  # trusted harness/operator metadata, never taken from mail/model
    complete: bool = True
    def __post_init__(self):
        if type(self.text) is not str or type(self.complete) is not bool:
            raise ValueError('Invalid context.')
        if self.authorization not in ('synthetic-fixture','owner-approved-sanitized'):
            raise ValueError('Context authorization required.')

def contextual_packet(features,relationships,context):
    packet=model_packet(features,relationships)
    if packet is None or not context.complete or not context.text.strip() or len(context.text)>2048:
        return None
    return {**packet,'prompt_version':'bounded-context-shadow-2','untrusted_message':{
        **packet['untrusted_message'],'readable_text':context.text},
        'context_authorization':context.authorization,'no_model_tools':True,
        'authentication':'not established by content, relationship or confidence'}

def contextual_review(features,relationships,context,model_reply):
    # A missing, partial or over-budget context cannot be silently truncated to win coverage.
    if contextual_packet(features,relationships,context) is None:
        return {'category':None,'suggested_category':None,'move_eligible':False,
                'operational_action':'Inbox / Keep','reason':'safety-context-or-authorization-veto'}
    if model_reply is None:
        return {'category':None,'suggested_category':None,'move_eligible':False,
                'operational_action':'Inbox / Keep','reason':'contextual-provider-required'}
    return shadow_review(features,relationships,model_reply)
