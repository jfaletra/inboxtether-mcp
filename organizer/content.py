"""Bounded non-rendering MIME/HTML classification. No network or attachment decoder."""
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import base64
import binascii
import quopri
import re

MAX_HEADER = 65_536
MAX_PART = 393_216
MAX_TEXT_BYTES = 524_288
MAX_PARTS = 200
MAX_DEPTH = 20
MAX_MESSAGE_SIZE = 4_194_304
SUPPORTED_ENCODINGS = {'7BIT', '8BIT', 'BINARY', 'BASE64', 'QUOTED-PRINTABLE'}
ENCRYPTED = {'application/pkcs7-mime', 'application/x-pkcs7-mime', 'application/pgp-encrypted', 'multipart/encrypted'}
ATTACHMENT_TYPES = {'application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'text/plain', 'text/csv',
                    'application/msword', 'application/vnd.ms-excel',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


class ContentRefused(ValueError):
    pass


def check(condition):
    if not condition:
        raise ContentRefused('Unsupported or malformed classification content.')


def preview(value, limit=2000):
    return ''.join(c if c in '\n\t' or c.isprintable() else '\\u%04x' % ord(c) for c in str(value))[:limit]


@dataclass(frozen=True)
class TextSection:
    section: str
    content_type: str
    charset: str
    encoding: str
    payload: bytes


@dataclass(frozen=True)
class MimeView:
    headers: bytes
    sections: tuple[TextSection, ...]
    attachments: tuple[dict, ...]
    structure_sha256: str
    source_size: int
    blocked: bool = False

    def fingerprint(self):
        from .model import digest
        return digest({'format': 'mime-view-v1', 'headers': digest(self.headers),
                       'sections': [{'section': s.section, 'type': s.content_type, 'charset': s.charset,
                                     'encoding': s.encoding, 'sha256': digest(s.payload)} for s in self.sections],
                       'attachments': list(self.attachments), 'structure': self.structure_sha256,
                       'source_size': self.source_size, 'blocked': self.blocked})


class ReadableHTML(HTMLParser):
    """Extract text, not HTML sanitization or browser rendering. Nothing is fetched."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    OPTIONAL = {'p', 'li', 'dt', 'dd', 'tr', 'td', 'th', 'thead', 'tbody', 'tfoot', 'option'}
    ACTIVE = {'script', 'iframe', 'object', 'embed', 'form', 'input', 'svg', 'math', 'applet'}
    SKIP = {'script', 'style', 'head', 'template', 'noscript'}
    LAYOUT = {'html','head','body','table','thead','tbody','tfoot','tr','td','th','colgroup',
              'p','div','span','font','center','a','b','strong','i','em','u','s','small',
              'h1','h2','h3','h4','h5','h6','ul','ol','li','dl','dt','dd','blockquote',
              'section','article','header','footer','main','pre','code','title','style','sup','sub',
              'o:p'}  # Literal inert Office paragraph only; no namespace wildcard.

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.visible, self.all_text = [], [], []
        self.bad = False
        self.tokens = 0
        self.text_length = 0

    def handle_starttag(self, tag, attrs):
        self.tokens += 1
        check(self.tokens <= 10000 and len(attrs) <= 100)
        if tag in self.ACTIVE or any(k.startswith('on') for k, _ in attrs):
            self.bad = True
        if any(k in ('href', 'src', 'action') and v and
               v.lstrip().casefold().startswith(('javascript:', 'vbscript:', 'data:')) for k, v in attrs):
            self.bad = True
        if tag == 'meta':
            for key,value in attrs:
                if key == 'http-equiv' and (value or '').casefold() not in ('content-type','content-language','x-ua-compatible'):
                    self.bad = True
        if tag not in self.LAYOUT | self.VOID | self.ACTIVE | self.SKIP:
            self.bad = True
        if len({k for k, _ in attrs}) != len(attrs):
            self.bad = True
        # Attributes are never rendered/evaluated; include textual metadata for customer veto only.
        for key, value in attrs:
            if key in ('alt', 'title', 'aria-label') and value:
                self.all_text.append(value)
        if tag in self.OPTIONAL and self.stack and self.stack[-1] == tag:
            self.stack.pop()
        if tag not in self.VOID:
            self.stack.append(tag)
            check(len(self.stack) <= 100)
        if tag in {'br', 'p', 'div', 'li', 'tr', 'td', 'h1', 'h2', 'h3', 'hr'}:
            self.visible.append('\n')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        self.tokens += 1
        check(self.tokens <= 10000)
        if tag == 'br':
            return  # Observed inert </br>: retain every text node; no stack mutation.
        if tag == 'body' and tag not in self.stack:
            return  # Stray body closer is inert; never unwind an unrelated open stack.
        if tag in self.VOID:
            self.bad = True
            return
        if tag == 'p' and tag not in self.stack:
            return  # HTML's stray </p> creates/closes an empty paragraph; no content is skipped.
        if tag not in self.stack:
            self.bad = True
            return
        while self.stack and self.stack[-1] != tag:
            if self.stack[-1] not in self.OPTIONAL and not (tag in {'html','body','table','tbody','thead','tfoot','tr'} and self.stack[-1] in {'p','td','th','tr','tbody','thead','tfoot','colgroup'}):
                self.bad = True
            self.stack.pop()
        self.stack.pop()
        self.visible.append(' ')

    def handle_data(self, data):
        self.text_length += len(data)
        check(self.text_length <= MAX_TEXT_BYTES)
        # CSS syntax is not natural-language evidence; hidden/alternative HTML text still is.
        if 'style' not in self.stack:
            self.all_text.append(data)
        if '<' in data and 'style' not in self.stack:
            self.bad = True  # literal malformed markup; avoid a quadratic "strip all tags" regex
        if not set(self.stack) & self.SKIP:
            self.visible.append(data)

    def handle_decl(self, decl):
        normalized=' '.join(decl.casefold().replace("'",'"').split())
        ordinary = normalized in ('doctype html', 'doctypehtml') or re.fullmatch(
            r'doctype html public "-//w3c//dtd (?:xhtml 1\.0|html 4\.01) (?:transitional|strict)//en" "https?://www\.w3\.org/[^"\[\]]{1,150}"',normalized)
        if not ordinary:
            self.bad = True

    def unknown_decl(self, decl):
        self.bad = True

    def handle_pi(self, data):
        self.bad = True

    def result(self, html):
        check(len(html) <= MAX_TEXT_BYTES)
        self.feed(html); self.close()
        # HTMLParser may discard an unfinished final start tag when close() runs.
        # A linear suffix check prevents losing that tail from protection evidence.
        if html.rfind('<') > html.rfind('>'):
            self.bad = True
        if any(t not in self.OPTIONAL for t in self.stack) or self.rawdata:
            self.bad = True
        # Detect unfinished tags/comments that HTMLParser treats as literal data at EOF.
        if '<!--' in html and '-->' not in html:
            self.bad = True
        return ''.join(self.visible), ''.join(self.all_text), self.bad


def decode_text(section):
    check(len(section.payload) <= MAX_PART and section.encoding.upper() in SUPPORTED_ENCODINGS)
    encoded = section.payload
    encoding = section.encoding.upper()
    if encoding == 'BASE64':
        try:
            encoded = base64.b64decode(re.sub(rb'[\r\n\t ]', b'', encoded), validate=True)
        except (binascii.Error, ValueError):
            raise ContentRefused('Malformed text transfer encoding.') from None
    elif encoding == 'QUOTED-PRINTABLE':
        check(re.search(rb'=(?![0-9A-Fa-f]{2}|\r?\n)', encoded) is None)
        encoded = quopri.decodestring(encoded)
    check(len(encoded) <= MAX_PART)
    return encoded.decode(section.charset or 'us-ascii', errors='strict')


def from_raw(raw):
    """Synthetic/offline fixtures only. Attachment payloads are never decoded."""
    from .model import digest
    check(len(raw) <= MAX_MESSAGE_SIZE)
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    sections, attachments = [], []
    blocked, count, total = False, 0, 0

    def walk(part, section, depth):
        nonlocal blocked, count, total
        count += 1
        check(count <= MAX_PARTS and depth <= MAX_DEPTH)
        check(not part.defects)
        kind = part.get_content_type().lower()
        if kind in ENCRYPTED or kind == 'multipart/signed' or part.get_content_maintype() == 'message':
            blocked = True
            return
        filename = part.get_filename() or ''
        disposition = part.get_content_disposition() or ''
        if filename or disposition == 'attachment' or (not part.is_multipart() and kind not in ('text/plain', 'text/html')):
            attachments.append({'filename': filename, 'content_type': kind, 'disposition': disposition,
                                'size': len(str(part.get_payload())), 'section': section or '1'})
            if kind not in ATTACHMENT_TYPES:
                blocked = True
            return
        if part.is_multipart():
            if kind not in ('multipart/alternative', 'multipart/mixed', 'multipart/related'):
                blocked = True
            for index, child in enumerate(part.iter_parts(), 1):
                walk(child, (section + '.' if section else '') + str(index), depth + 1)
            return
        payload = part.get_payload()
        check(isinstance(payload, str))
        # BytesParser preserves arbitrary encoded octets via surrogateescape.
        try:
            encoded = payload.encode('ascii', 'surrogateescape')
        except UnicodeEncodeError:
            encoded = payload.encode(part.get_content_charset() or 'utf-8')
        total += len(encoded)
        check(total <= MAX_TEXT_BYTES)
        sections.append(TextSection(section or '1', kind, part.get_content_charset() or 'us-ascii',
                                    str(part.get('Content-Transfer-Encoding', '7bit')).upper(), encoded))
    walk(msg, '', 0)
    head = raw.split(b'\r\n\r\n', 1)[0] + b'\r\n\r\n'
    check(len(head) <= MAX_HEADER)
    return MimeView(head, tuple(sections), tuple(attachments), digest(raw), len(raw), blocked)


def analyze(view):
    """Return readable text plus ALL textual alternatives as protection evidence."""
    check(len(view.headers) <= MAX_HEADER and len(view.sections) + len(view.attachments) <= MAX_PARTS)
    check(sum(len(s.payload) for s in view.sections) <= MAX_TEXT_BYTES)
    visible, protection = [], []
    unsafe = view.blocked
    for section in view.sections:
        text = decode_text(section)
        if section.content_type == 'text/html':
            readable, all_text, bad = ReadableHTML().result(text)
            visible.append(readable); protection.append(all_text); unsafe |= bad
        elif section.content_type == 'text/plain':
            visible.append(text); protection.append(text)
            if any(marker in text.upper() for marker in ('-----BEGIN PGP MESSAGE-----', '-----BEGIN PKCS7-----')):
                unsafe = True
        else:
            unsafe = True
    protection.extend(str(a.get('filename', '')) for a in view.attachments)
    return '\n'.join(visible), '\n'.join(protection), unsafe
