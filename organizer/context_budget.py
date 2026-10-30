"""Deterministic excerpts of an already safety-checked MIME view. No IO or model.

Excerpts never replace full-view protection checks. Practical Mode may use body
excerpts only when metadata is complete and potential customer material is covered.
"""
import re

BODY_LIMIT = 8192
PACKET_LIMIT = 16384  # canonical ASCII JSON bytes, including every field
CONTEXT_VERSION = 'normalized-context-v2'
GAP = '\n[content omitted]\n'
SIGNAL = re.compile(r'(?im)^.*\b(?:invoice|shipment|tracking|wholesale|allocation|'
                    r'supplier|industry|publication|government|promotion|sale|'
                    r'customer|transfer|repair|refund|question)\b')


def normalize_text(text):
    """Classification presentation only; original bytes/full protection view remain intact."""
    value = '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines())
    value = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', value).strip()
    if text.split() != value.split():
        raise ValueError('Context normalization changed tokens.')
    return value


def excerpts(text, limit=BODY_LIMIT):
    """Bound head + a relevant middle window + tail, with exact source offsets."""
    if len(text) <= limit:
        return text, [{'source_start': 0, 'source_end': len(text),
                       'context_start': 0, 'context_end': len(text)}], 0
    # Reserve two explicit gap markers, then prioritize introduction and closing.
    available = max(0, limit - 2 * len(GAP))
    head, tail = available // 2, available // 4
    middle = available - head - tail
    hit = SIGNAL.search(text, head, max(head, len(text) - tail))
    start = max(head, (hit.start() if hit else len(text)//2) - middle//4)
    start = min(start, max(head, len(text)-tail-middle))
    ranges = sorted([(0, head), (start, start+middle), (len(text)-tail, len(text))])
    merged = []
    for left, right in ranges:
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        elif right > left:
            merged.append((left, right))
    value, positions = '', []
    for left, right in merged:
        if positions:
            value += GAP
        begin = len(value);value += text[left:right]
        positions.append({'source_start':left,'source_end':right,
                          'context_start':begin,'context_end':len(value)})
    assert len(value) <= limit
    return value, positions, len(text)-sum(b-a for a,b in merged)


def bounded_metadata(guard):
    """Keep sender/subject first, expose only bounded attachment metadata."""
    fields, omitted = {}, []
    for key, source, limit in (('from','sender',320),('subject','subject',512)):
        value=guard[source];fields[key]=value[:limit]
        if len(value)>limit:omitted.append(key)
    attachments=[];changed=False
    for value in guard.get('attachments',[])[:8]:
        row={}
        for key,limit in (('filename',96),('content_type',64),('disposition',32)):
            text=str(value.get(key) or '');row[key]=text[:limit]
            changed |= len(text)>limit
        size=value.get('size');row['size']=size if type(size) is int and 0<=size<=2**63-1 else None
        changed |= size is not None and row['size'] is None
        attachments.append(row)
    omitted_count=max(0,len(guard.get('attachments',[]))-len(attachments))
    return fields,attachments,omitted,changed,omitted_count


# Potentially material correspondence signals get surrounding context, not just a
# keyword match. This supplements, and never replaces, the full-view customer guard.
MATERIAL = re.compile(
    r'\b(?:customer|client|buyer|purchaser|pickup|pick up|ffl|transfer|gunsmith\w*|'
    r'repair\w*|refund\w*|appointment|quote|quotation|complaint|problem|damage\w*|'
    r'warranty|cancellation)\b|'
    r'\b(?:my|your|our|their|the)\s+(?:order|purchase|shipment|invoice|payment)\b|'
    r'\b(?:i\s+(?:have|placed|ordered|bought|paid|sent|received)|'
    r'please\s+(?:reply|respond|confirm|review|call|contact|send)|'
    r'(?:can|could|would)\s+you|(?:reply|respond|call|contact)\s+(?:me|us))\b')


def omission_assessment(visible, protection_text, positions):
    """Conservative material-coverage assessment; no claim of semantic certainty.

    Scan ALL protection text, including MIME alternatives and hidden HTML text.
    A potential customer/correspondence signal must have its surrounding context
    wholly visible in one excerpt. Metadata omissions are handled separately.
    """
    from .context import natural
    chunks=[];last=0
    for span in positions:
        a,b=span['source_start'],span['source_end']
        if not (type(a) is int and type(b) is int and last<=a<=b<=len(visible)):
            return {'status':'invalid-excerpt-coverage','material_signals_checked':0}
        chunks.append(natural(visible[a:b]));last=b
    full=natural(protection_text);count=0
    for match in MATERIAL.finditer(full):
        count+=1
        if count>128:return {'status':'material-signal-budget-exceeded','material_signals_checked':128}
        window=full[max(0,match.start()-120):min(len(full),match.end()+120)].strip()
        if not any(window in chunk for chunk in chunks):
            return {'status':'potential-customer-material-omitted','material_signals_checked':count}
    return {'status':'no-material-omission-detected','material_signals_checked':count}
