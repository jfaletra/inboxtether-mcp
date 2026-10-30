"""Immutable identities and operator-owned classification rules."""
from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import hashlib
import json
import re
import unicodedata

CATEGORIES = ('Industry', 'Marketing', 'Orders', 'Review', 'Suppliers')
MAX_RAW = 1_048_576
MAX_TEXT = 100_000
MAX_PREVIEW = 2000
MAX_PAGE = 50
MAX_RUN = 100_000
PROTECTED_FLAGS = {'\\flagged', '\\draft', '\\deleted'}


class OrganizerError(Exception):
    """Public errors must contain fixed strings, never server or message data."""


def require(condition, message='Organization request refused.'):
    if not condition:
        raise OrganizerError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def integer(value, low=1, high=4294967295):
    require(type(value) is int and low <= value <= high, 'Invalid numeric argument.')
    return value


def persistent(flags):
    require(all(isinstance(f, str) and re.fullmatch(r'[^\s(){}%*"\x00-\x1f\x7f]+', f) for f in flags),
            'Unsupported flags.')
    return sorted(set(f for f in flags if f.casefold() != '\\recent'), key=str.casefold)


@dataclass(frozen=True)
class Message:
    uid: int
    raw: bytes
    flags: tuple[str, ...] = ()
    internaldate: str = '01-Jan-2026 00:00:00 +0000'
    view: object = None
    source_uidvalidity: int = 0

    def evidence(self):
        integer(self.uid)
        require(isinstance(self.raw, bytes) and len(self.raw) <= MAX_RAW, 'Message exceeds safety limit.')
        return {'uid': self.uid, 'sha256': self.view.fingerprint() if self.view else digest(self.raw),
                'size': self.view.source_size if self.view else len(self.raw),
                'identity_kind': 'mime-view-v1' if self.view else 'raw-v1',
                'flags': persistent(self.flags), 'internaldate': self.internaldate}


@dataclass(frozen=True)
class Rule:
    """Explicit sender + subject pattern. client cannot add or edit rules."""
    rule_id: str
    sender: str
    category: str
    subject_pattern: str
    list_id: str = ''
    signing_domain: str = ''
    reply_to_domains: tuple[str, ...] = ()
    # Precedence only resolves two matching rules for the SAME category.


@dataclass(frozen=True)
class Policy:
    owner: str
    version: str
    customer_addresses: tuple[str, ...] = ()
    customer_domains: tuple[str, ...] = ()
    protected_thread_ids: tuple[str, ...] = ()
    rules: tuple[Rule, ...] = ()
    customer_terms: tuple[str, ...] = ()  # Additional explicit owner phrases, not broad noun vetoes.
    owner_keep_rules: tuple[tuple[str,str], ...] = ()
    trusted_authserv_ids: tuple[str, ...] = ()
    authentication_boundary_sha256: str = ''

    def __post_init__(self):
        require(bool(self.owner) and bool(self.version), 'Owner and policy version required.')
        require(len(self.rules) <= 500, 'Too many classification rules.')
        require(len(self.trusted_authserv_ids)<=10 and all(re.fullmatch(r'[a-z0-9.-]+',x) for x in self.trusted_authserv_ids), 'Invalid authserv IDs.')
        require(not self.authentication_boundary_sha256 or re.fullmatch(r'[0-9a-f]{64}',self.authentication_boundary_sha256), 'Invalid authentication boundary evidence.')
        require(len(self.owner_keep_rules)<=500 and all(len(pair)==2 and all(isinstance(x,str) and 0<len(x)<=1000 for x in pair) for pair in self.owner_keep_rules), 'Invalid owner keep rules.')
        ids = set()
        for rule in self.rules:
            require(rule.category in CATEGORIES and rule.rule_id not in ids, 'Invalid classification rule.')
            require(bool(rule.rule_id) and len(rule.subject_pattern) <= 200 and bool(rule.subject_pattern),
                    'Invalid classification rule.')
            require(re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', rule.sender) is not None, 'Invalid rule sender.')
            # Literal subject phrases: no regex evaluation / sender-controlled backtracking.
            require(not rule.signing_domain or re.fullmatch(r'[a-z0-9.-]+',rule.signing_domain), 'Invalid signing domain.')
            require(len(rule.reply_to_domains)<=10 and all(re.fullmatch(r'[a-z0-9.-]+',d) for d in rule.reply_to_domains), 'Invalid reply identity pin.')
            ids.add(rule.rule_id)

    @property
    def fingerprint(self):
        from dataclasses import asdict
        return digest(asdict(self))

    def classify(self, message):
        return self._classify(message)

    def contextual_guard(self, message, rule, *, verified_domain=None, authentication_required=True):
        """Backend-only exact-sender guard. Placeholder category is NEVER an AI decision."""
        require(isinstance(rule, Rule), 'Trusted contextual sender rule required.')
        require(type(authentication_required) is bool, 'Explicit authentication policy required.')
        return self._classify(message, rule, verified_domain=verified_domain, authentication_required=authentication_required)

    def _classify(self, message, contextual_rule=None, *, verified_domain=None, authentication_required=True):
        """Rules propose; unknown senders and ambiguous content stay in Inbox."""
        evidence = message.evidence()
        result = {'category': None, 'reason': 'uncertain', 'customer': False, 'rule_ids': [],
                  'sender': '', 'subject': '', 'date': '', 'text': '', **evidence}
        if {f.casefold() for f in message.flags} & PROTECTED_FLAGS:
            return {**result, 'reason': 'protected-flags'}
        try:
            from .content import analyze, from_raw, preview
            from .context import customer_intent
            view = message.view or from_raw(message.raw)
            msg = BytesParser(policy=policy.default).parsebytes(view.headers, headersonly=True)
            for name in ('From', 'Sender', 'Reply-To', 'Subject', 'Date', 'List-ID', 'Message-ID', 'References', 'In-Reply-To'):
                if len(msg.get_all(name, [])) > 1:
                    return {**result, 'reason': 'ambiguous-headers'}
            # Python's stricter parser can reject a whole combined list containing
            # absent/empty optional fields. Parse each PRESENT occurrence separately.
            addresses, address_defect = [], False
            for name in ('From', 'Sender', 'To', 'Cc', 'Bcc', 'Reply-To'):
                for header in msg.get_all(name, []):
                    parsed = getaddresses([str(header)]) if str(header).strip() else []
                    address_defect |= bool(getattr(header, 'defects', ())) or not parsed or any(not a for _, a in parsed)
                    addresses.extend(a.casefold() for _, a in parsed if a)
            froms = getaddresses([str(msg.get('From', ''))])
            visible, protection_text, unsafe = analyze(view)
            subject = str(msg.get('Subject', ''))
            result.update(sender=preview(msg.get('From', ''), 1000), subject=preview(subject, 1000),
                          date=preview(msg.get('Date', ''), 1000), text=preview(visible, MAX_PREVIEW),
                          preview_truncated=len(visible) > MAX_PREVIEW,
                          attachments=[{**a, 'filename': preview(a.get('filename', ''), 256)}
                                       for a in view.attachments[:20]],
                          attachments_truncated=len(view.attachments) > 20)
            thread = ' '.join(str(msg.get(k, '')) for k in ('Message-ID', 'References', 'In-Reply-To'))
            matches = [r for r in (self.rules if contextual_rule is None else (contextual_rule,))
                       if len(froms)==1 and froms[0][1].casefold() == r.sender.casefold()
                       and (contextual_rule is not None or r.subject_pattern.casefold() in subject.casefold())
                       and (not r.list_id or str(msg.get('List-ID', '')).strip() == r.list_id)]
            categories = {r.category for r in matches}
            customer = (any(a in {x.casefold() for x in self.customer_addresses} or
                            a.rsplit('@', 1)[-1] in {x.casefold() for x in self.customer_domains} for a in addresses)
                        or any(t in thread.split() for t in self.protected_thread_ids)
                        or customer_intent(
                            subject,protection_text,self.customer_terms))
            if customer:
                return {**result, 'reason': 'customer-protected', 'customer': True}
            if len(froms)==1 and any(froms[0][1].casefold()==sender.casefold() and subject==phrase for sender,phrase in self.owner_keep_rules):
                return {**result,'reason':'owner-kept'}
            if unsafe or address_defect:
                return {**result, 'reason': 'unsafe-or-unsupported-content'}
            if (msg.defects or len(froms) != 1 or not froms[0][1] or not visible.strip()
                    or len(protection_text) > MAX_TEXT or len(subject) > 1000):
                return {**result, 'reason': 'incomplete-or-ambiguous-content'}
            from .context import mixed_thread, authenticated_sender
            if mixed_thread(msg,subject,protection_text):
                return {**result,'reason':'thread-context-required'}
            reply=getaddresses([str(msg.get('Reply-To',''))]) if msg.get('Reply-To') else []
            reply_domain=reply[0][1].rsplit('@',1)[-1].casefold() if len(reply)==1 and reply[0][1] else ''
            pinned_reply=bool(matches) and all(reply_domain in r.reply_to_domains for r in matches)
            if reply and (not reply_domain or (reply_domain!=froms[0][1].rsplit('@',1)[-1].casefold() and not pinned_reply)):
                return {**result,'reason':'reply-identity-uncertain'}
            # A model may only make the result MORE conservative, never override these gates.
            if len(categories) == 1:
                if not authentication_required:
                    require(contextual_rule is not None, 'Practical policy requires contextual proposal.')
                    return {**result, 'category': categories.pop(), 'reason': 'operator-rule',
                            'rule_ids': sorted(r.rule_id for r in matches)}
                auth=[('aligned-dkim-and-dmarc' if verified_domain == (r.signing_domain or froms[0][1].rsplit('@',1)[-1]).casefold() else 'authentication-domain-mismatch')
                    if verified_domain is not None else authenticated_sender(msg,froms[0][1],self.trusted_authserv_ids,
                    self.authentication_boundary_sha256,r.signing_domain) for r in matches]
                if any(a!='aligned-dkim-and-dmarc' for a in auth):
                    return {**result,'reason':auth[0] if len(set(auth))==1 else 'authentication-ambiguous',
                            'proposed_category':next(iter(categories)),'move_eligible':False}
                return {**result, 'category': categories.pop(), 'reason': 'operator-rule',
                        'rule_ids': sorted(r.rule_id for r in matches)}
            return {**result, 'reason': 'category-conflict' if matches else 'uncertain'}
        except Exception:
            return {**result, 'reason': 'unreadable'}


@dataclass(frozen=True)
class Config:
    account: str
    host: str
    owner: str
    pins: dict[str, int]
    moves_enabled: bool = False
    approval_seconds: int = 600
    max_batch_moves: int = 500
    principal_binding_sha256: str = ''

    def __post_init__(self):
        require(bool(self.account) and bool(self.host) and bool(self.owner), 'Fixed scope required.')
        require(set(self.pins) == set(CATEGORIES), 'Exactly five destination pins required.')
        for value in self.pins.values():
            integer(value)
        integer(self.approval_seconds, 30, 3600)
        integer(self.max_batch_moves, 1, 500)
        require(self.principal_binding_sha256 == '' or bool(re.fullmatch(r'[0-9a-f]{64}',self.principal_binding_sha256)), 'Invalid principal binding.')
        require(type(self.moves_enabled) is bool, 'Invalid move switch.')

    def scope(self, policy):
        require(policy.owner == self.owner, 'Policy owner mismatch.')
        return {'account': self.account, 'host': self.host, 'owner': self.owner,
                'source': 'INBOX', 'destinations': dict(self.pins), 'policy': policy.fingerprint,
                'principal_binding_sha256': self.principal_binding_sha256, 'format': 10 if getattr(policy, 'mode', '') == 'practical' else 9 if getattr(policy, 'evidence_source', None) is not None else 7 if getattr(policy, 'classification_mode', '') == 'client-contextual-proposal-1' else 5,
                'classifier': getattr(policy, 'classification_mode', 'forwarding-context-proposal-4')}
