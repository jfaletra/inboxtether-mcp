"""Bounded natural-language protection and fail-closed receiver-authentication evidence."""
import re
import unicodedata


def natural(value):
    value=''.join(c for c in unicodedata.normalize('NFKC',value).casefold() if unicodedata.category(c)!='Cf')
    return re.sub(r'[^\w]+',' ',value,flags=re.UNICODE).strip()


INTENT = tuple(re.compile(p) for p in (
    r'\bcustomer\b.{0,60}\b(?:asks?|needs?|wants?|order|inquiry|transfer|request)\b',
    r'\bmy\s+(?:order|transfer|gun|firearm|suppressor|purchase)\b',
    r'\b(?:incoming|ffl)\s+transfer\b',
    r'\b(?:can|could|would)\s+you\b',
    r'\b(?:i|we)\s+(?:need|want|would like|am looking|are looking)\b',
    r'\bhow much\b',
    r'\b(?:quote|quotation)\s+request\b',
    r'\b(?:request|requesting|need|want)\s+(?:a\s+)?(?:quote|refund|appointment)\b',
    r'\b(?:order|purchase)\s+(?:question|discussion|problem|issue)\b',
    r'\b(?:refund|pickup|pick up|appointment|complaint)\s+(?:request|for|my|needed)\b',
    r'\b(?:process|fees?)\s+(?:for|to)\s+(?:a\s+)?transfer\b',
))


def customer_intent(subject, text, additional_terms=()):
    value=natural(subject+'\n'+text)
    # Political phrase only: retain every other customer-intent match in the message.
    plural=re.search(r'\bour\s+(?:order|transfer|gun(?!\s+rights\b)|firearm|suppressor|purchase)\b',value)
    return bool(plural) or any(p.search(value) for p in INTENT) or any(
        re.search(r'(?<!\w)'+re.escape(natural(t))+r'(?!\w)',value)
        for t in additional_terms if natural(t))


def mixed_thread(msg, subject, text):
    return bool(msg.get('References') or msg.get('In-Reply-To')
        or any(name.casefold().startswith('resent-') for name in msg.keys())
        or re.match(r'^\s*(?:re|fw|fwd)\s*:',subject,re.I)
        or re.search(r'(?m)^\s*>',text)
        or re.search(r'(?im)^on [^\n]{1,200} wrote:',text))


def authenticated_sender(msg, sender, trusted_ids, boundary_sha256, signing_domain=''):
    """Interpret only a separately verified ingress boundary; headers alone never prove provenance.

    Deliberately small RFC8601 subset: comments/ambiguous/repeated methods fail closed.
    Exact configured From-domain DMARC plus pinned aligned DKIM required; SPF/ARC alone
    cannot authorize a proposal. The boundary hash is operator evidence, NOT a signature.
    """
    if not trusted_ids or not re.fullmatch(r'[0-9a-f]{64}',boundary_sha256):
        return 'authentication-boundary-unverified'
    from_domain=sender.rsplit('@',1)[-1].casefold()
    domain=(signing_domain or from_domain).casefold()
    if not (from_domain==domain or from_domain.endswith('.'+domain)):
        return 'authentication-domain-mismatch'
    selected=[]
    for header in msg.get_all('Authentication-Results',[]):
        raw=str(header)
        if len(raw)>4096:return 'authentication-ambiguous'
        # Remove bounded RFC comments without letting them supply method/property tokens.
        out=[];depth=0;quoted=False;escaped=False
        for char in raw:
            if escaped:
                if not depth:out.append(char)
                escaped=False;continue
            if char=='\\':
                escaped=True
                if not depth:out.append(char)
            elif char=='"' and not depth:quoted=not quoted;out.append(char)
            elif char=='(' and not quoted:
                depth+=1
                if depth>5:return 'authentication-unsupported'
                if depth==1:out.append(' ')
            elif char==')' and not quoted:
                if not depth:return 'authentication-unsupported'
                depth-=1
            elif not depth:out.append(char)
        if depth or quoted or escaped:return 'authentication-unsupported'
        parts=''.join(out).casefold().split(';')
        if parts[0].strip() in trusted_ids:selected.append(parts[1:])
    if len(selected)!=1:return 'authentication-ambiguous'
    dmarc=[];dkim=[]
    for clause in selected[0]:
        if not clause.strip():continue
        match=re.fullmatch(r'\s*([a-z0-9_-]+)=([a-z0-9_-]+)(.*)',clause,re.S)
        if not match:return 'authentication-unsupported'
        if match[1] not in ('dkim','dmarc'):continue
        attrs={};remaining=match[3]
        while remaining.strip():
            item=re.match(r'\s+([a-z][a-z0-9_.-]*)=(?:"([^"\\\x00-\x1f]{0,256})"|([a-z0-9@._:/+=-]+))',remaining)
            if not item or item[1] in attrs:return 'authentication-unsupported'
            attrs[item[1]]=item[2] if item[2] is not None else item[3]
            remaining=remaining[item.end():]
        if match[1]=='dmarc':dmarc.append((match[2],attrs.get('header.from','')))
        else:dkim.append((match[2],attrs.get('header.d','')))
    if dmarc!=[('pass',from_domain)] or len(dkim)!=1 or dkim[0]!=('pass',domain):
        return 'authentication-not-aligned'
    return 'aligned-dkim-and-dmarc'


def contextual_uncertainty(subject, text, *, allow_questions=False):
    """Additional conservative gate for an untrusted contextual proposer.

    Practical Mode permits ordinary questions for contextual assessment. Explicit
    customer reports remain protected; Strict Mode retains its original question gate.
    """
    combined=unicodedata.normalize('NFKC', subject+'\n'+text)
    if not allow_questions and '?' in combined:
        return 'customer-question-context-uncertain'
    value=natural(combined)
    if allow_questions and re.search(r'\b(?:is|when is|status of)\s+(?:my|the|our|this)\s+(?:ffl\s+)?transfer\b',value):
        return 'customer-transfer-context-uncertain'
    if re.search(r'\b(?:walk in buyer|customer|purchaser)\b.{0,120}\b(?:reports?|complains?|needs?|requests?|asks?|says)\b',value):
        return 'customer-report-context-uncertain'
    return ''
