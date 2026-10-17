"""Opt-in draft staging and local operator approval. No SMTP, no mutation of old mail.

The operator/host is trusted. MCP callers cannot approve through this module's tools.
Never give the model shell/filesystem access to the service account or approval store.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import stat
import sys
import time
import unicodedata
from urllib.parse import urlsplit

TTL = 600
MAX_PENDING = 32
MAX_DRAFT = 65536
ID = re.compile(r'[0-9a-f]{64}')
MSG_ID = r'<[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+>'


class DraftError(Exception):
    """Safe errors only; never include underlying server replies or draft content."""


def require(condition, message='Draft validation failed.'):
    if not condition:
        raise DraftError(message)


def text(value, limit, multiline=False):
    require(isinstance(value, str) and 0 < len(value) <= limit)
    require(all((multiline and c in '\n\t') or not unicodedata.category(c).startswith('C') for c in value))
    require(bool(value.strip()))
    return value


def address(value):
    # Intentionally conservative bare ASCII addresses; no display-name parsing.
    require(isinstance(value, str) and len(value) <= 254 and value.isascii())
    require(re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[A-Za-z0-9.-]+", value))
    local, domain = value.rsplit('@', 1)
    require(len(local) <= 64 and '.' in domain and len(domain) <= 253)
    require(all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in domain.split('.')))
    return local + '@' + domain.lower()


def recipients(to, cc, bcc):
    groups = []
    for values in (to, [] if cc is None else cc, [] if bcc is None else bcc):
        require(isinstance(values, list) and len(values) <= 20)
        groups.append([address(v) for v in values])
    all_values = sum(groups, [])
    require(groups[0] and len(all_values) <= 20 and len({v.casefold() for v in all_values}) == len(all_values))
    return groups


@dataclass(frozen=True)
class Config:
    host: str
    account: str
    folder: str
    state_dir: Path
    approval_owner: tuple[str, str] | None = None
    review_origin: str | None = None
    mode: str = "secure"

    @classmethod
    def load(cls):
        switch = os.environ.get('INBOXTETHER_DRAFT_ASSISTANT', '0')
        require(switch in ('0', '1'), 'Invalid Draft Assistant setting.')
        if switch == '0':
            return None
        mode = os.environ.get('INBOXTETHER_DRAFT_MODE', 'secure')
        require(mode in ('basic', 'secure'), 'Invalid draft mode; no fallback is permitted.')
        if mode == 'basic':
            require(os.environ.get('INBOXTETHER_BASIC_ACK') == 'I_ACCEPT_CLIENT_CONTROLLED_APPROVAL',
                    'Basic Mode requires acknowledgment of client-controlled approval.')
            require(os.environ.get('INBOXTETHER_BROWSER_APPROVAL', '0') == '0', 'Basic and browser approval cannot be combined.')
        host = os.environ.get('INBOXTETHER_IMAP_HOST', 'mail.example.com')
        account = address(os.environ.get('INBOXTETHER_ACCOUNT', 'user@example.com'))
        folder = os.environ.get('INBOXTETHER_DRAFTS_FOLDER', '')
        require(isinstance(folder, str) and 0 < len(folder) <= 256 and folder.isascii())
        require(all(32 <= ord(c) <= 126 for c in folder) and not any(c in folder for c in '*%"\\'))
        require(folder.casefold() not in {'inbox', 'sent', 'trash', 'junk', 'spam', 'archive', 'deleted items', 'sent items'})
        directory = Path(os.environ.get('INBOXTETHER_DRAFT_STATE_DIR', ''))
        require(directory.is_absolute(), 'Configure a protected absolute draft state directory.')
        require(bool(host) and len(host) <= 253 and re.fullmatch(r'[A-Za-z0-9.-]+', host))
        browser = os.environ.get('INBOXTETHER_BROWSER_APPROVAL', '0')
        require(browser in ('0', '1'), 'Invalid browser approval setting.')
        owner = origin = None
        if browser == '1':
            issuer = https_url(os.environ.get('INBOXTETHER_APPROVAL_ISSUER', ''))
            subject = text(os.environ.get('INBOXTETHER_APPROVAL_SUBJECT', ''), 256)
            owner = (issuer, subject)
            origin = https_url(os.environ.get('INBOXTETHER_REVIEW_ORIGIN', ''), origin=True)
        return cls(host, account, folder, directory, owner, origin, mode)

    def scope(self):
        scope = {'host': self.host, 'account': self.account, 'folder': self.folder}
        if self.mode == 'basic':
            scope['approval_mode'] = 'basic'
        if self.approval_owner is not None:
            scope['approval_owner'] = dict(zip(('issuer', 'subject'), self.approval_owner))
        return scope


def https_url(value, origin=False):
    require(isinstance(value, str) and value.isascii() and len(value) <= 1024)
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and not any(c.isspace() for c in value)
            and (not origin or parsed.path == ''), 'Configure an explicit HTTPS URL without userinfo/query/fragment.')
    require(parsed.netloc == parsed.netloc.lower(), 'Use lowercase URL host names.')
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, config):
        self.config = config

    @contextmanager
    def db(self):
        directory = self.config.state_dir
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and not directory.is_symlink()
                and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'Draft state directory must be owned by the service user with mode 700.')
        # Ancestor paths are trusted operator configuration, not caller input.
        path = directory / 'approvals.sqlite3'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe draft approval database.')
        finally:
            os.close(fd)
        db = sqlite3.connect(path, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, manifest BLOB NOT NULL, raw BLOB NOT NULL, fingerprint TEXT NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL, approved TEXT, result TEXT)')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE IF NOT EXISTS decisions (draft_id TEXT PRIMARY KEY REFERENCES drafts(id) ON DELETE CASCADE, fingerprint TEXT NOT NULL, actor TEXT NOT NULL, decided REAL NOT NULL)')
            db.commit()
            yield db
        finally:
            db.close()

    def put(self, manifest, raw):
        key = secrets.token_hex(32)
        packed = canonical(manifest)
        fingerprint = digest(packed)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Only local staging data is purged; never mailbox messages.
            db.execute('DELETE FROM drafts WHERE expires < ?', (time.time(),))
            require(db.execute('SELECT count(*) FROM drafts').fetchone()[0] < MAX_PENDING,
                    'Draft staging limit reached; wait for expiry.')
            db.execute('INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?)',
                       (key, packed, raw, fingerprint, manifest['expires_at'], 'pending', None, None))
            db.commit()
        return key

    def get(self, key):
        require(isinstance(key, str) and ID.fullmatch(key), 'Invalid draft ID.')
        with self.db() as db:
            row = db.execute('SELECT * FROM drafts WHERE id=?', (key,)).fetchone()
        require(row is not None and row['expires'] > time.time(), 'Draft not found or expired; prepare a new review.')
        item = dict(row)
        item['manifest'] = json.loads(item['manifest'])
        require(canonical(item['manifest']) == row['manifest'] and digest(row['manifest']) == item['fingerprint'], 'Draft integrity check failed.')
        require(item['manifest']['mime_sha256'] == digest(item['raw']) and len(item['raw']) <= MAX_DRAFT,
                'Draft integrity check failed.')
        require(item['manifest']['expires_at'] == item['expires'], 'Draft integrity check failed.')
        require(item['manifest']['scope'] == self.config.scope(), 'Draft configuration changed; prepare a new review.')
        require(preview(item['raw']) == item['manifest']['preview'], 'Draft integrity check failed.')
        return item

    def approve(self, key, fingerprint, actor=None):
        self.decide(key, fingerprint, 'approved', actor or {'method': 'terminal', 'uid': os.geteuid()})

    def decide(self, key, fingerprint, state, actor):
        require(state in ('approved', 'rejected'))
        item = self.get(key)
        require(item['state'] == 'pending' and fingerprint == item['fingerprint'], 'Approval no longer matches pending draft.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE drafts SET state=?, approved=? WHERE id=? AND state='pending' AND fingerprint=? AND expires>?",
                                 (state, fingerprint if state == 'approved' else None, key, fingerprint, time.time())).rowcount
            require(changed == 1, 'Draft changed or expired during review.')
            db.execute('INSERT INTO decisions VALUES (?,?,?,?)', (key, fingerprint, canonical(actor), time.time()))
            db.commit()

    def claim(self, key, fingerprint):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE drafts SET state='attempting' WHERE id=? AND state='approved' AND fingerprint=? AND approved=? AND expires>?",
                                 (key, fingerprint, fingerprint, time.time())).rowcount
            require(changed == 1, 'Draft is not approved or has already been attempted.')
            db.commit()  # Durable before APPEND; crash/retry must never append twice.

    def finish(self, key, state, result):
        with self.db() as db:
            db.execute("UPDATE drafts SET state=?, result=? WHERE id=? AND state='attempting'",
                       (state, json.dumps(result), key))
            db.commit()


def preview(raw):
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    require(not msg.defects and not msg.is_multipart() and msg.get_content_type() == 'text/plain')
    return {**{name: str(msg.get(name, '')) for name in
               ('From', 'To', 'Cc', 'Bcc', 'Subject', 'Date', 'Message-ID', 'In-Reply-To', 'References')},
            'body': msg.get_content()}


def reply_bytes(config, original, to, subject, body, cc, bcc):
    to, cc, bcc = recipients(to, cc, bcc)
    text(subject, 200)
    text(body, 20000, multiline=True)
    parent = BytesParser(policy=policy.default).parsebytes(original, headersonly=True)
    for name in ('Message-ID', 'References', 'In-Reply-To'):
        require(len(parent.get_all(name, [])) <= 1, 'Ambiguous parent threading headers.')
    parent_id = str(parent.get('Message-ID', '')).strip()
    require(re.fullmatch(MSG_ID, parent_id), 'Parent needs one valid Message-ID for a threaded reply.')
    chain = str(parent.get('References', '')).strip()
    if not chain:
        chain = str(parent.get('In-Reply-To', '')).strip()
    references = re.findall(MSG_ID, chain)
    require(not re.sub(MSG_ID, '', chain).strip() and len(references) < 20, 'Unsupported parent threading chain.')
    references = list(dict.fromkeys([*references, parent_id]))
    msg = EmailMessage(policy=policy.SMTP)
    msg['From'] = config.account
    msg['To'] = ', '.join(to)
    if cc:
        msg['Cc'] = ', '.join(cc)
    if bcc:
        msg['Bcc'] = ', '.join(bcc)
    msg['Subject'] = subject
    msg['Date'] = format_datetime(datetime.now(timezone.utc))
    msg['Message-ID'] = f'<{secrets.token_hex(24)}@{config.account.rsplit("@", 1)[1]}>'
    msg['In-Reply-To'] = parent_id
    msg['References'] = ' '.join(references)
    msg.set_content(body, subtype='plain', charset='utf-8', cte='quoted-printable')
    raw = msg.as_bytes()
    require(len(raw) <= MAX_DRAFT, 'Serialized draft exceeds 64 KiB.')
    return raw


class DraftService:
    def __init__(self, reader, config=None):
        self.reader = reader
        self.config = config or Config.load()
        require(self.config is not None, 'Draft Assistant is disabled.')
        require(self.config.host == reader.HOST and self.config.account == address(reader.ACCOUNT),
                'Draft account configuration mismatch.')
        self.store = Store(self.config)

    def target(self, client, expected=None):
        r, cfg = self.reader, self.config
        require(any(c in ('UIDPLUS', b'UIDPLUS') for c in client.capabilities), 'Draft saving requires UIDPLUS and APPENDUID verification.')
        rows = r.check(client.list('""', r.quoted(cfg.folder))) or []
        require(len(rows) == 1 and isinstance(rows[0], bytes), 'Configured Drafts folder is not unique.')
        match = re.fullmatch(rb'\(([^)]*)\) (?:NIL|"(?:[^"\\]|\\.)*") (.+)', rows[0])
        require(match is not None, 'Unsupported Drafts folder listing.')
        flags = match[1].lower().split()
        wire = match[2].decode('ascii')
        if wire.startswith('"') and wire.endswith('"'):
            wire = re.sub(r'\\(.)', r'\1', wire[1:-1])
        require(wire == cfg.folder and b'\\drafts' in flags and b'\\noselect' not in flags,
                'Configured folder must already exist and advertise the Drafts special-use flag.')
        validity = r.examine(client, cfg.folder)
        r.bounded_int(validity, 1, 4294967295)
        require(expected is None or validity == expected, 'Drafts folder identity changed; prepare again.')
        return validity

    def prepare(self, mailbox, uid, uidvalidity, to, subject, body, cc=None, bcc=None):
        # Validate recipient/content inputs before any mailbox connection.
        recipients(to, cc, bcc)
        text(subject, 200)
        text(body, 20000, multiline=True)
        original = self.reader.fetch_message(mailbox, uid, uidvalidity)
        raw = reply_bytes(self.config, original, to, subject, body, cc, bcc)
        with self.reader.connection() as client:
            validity = self.target(client)
        manifest = {'version': 1, 'expires_at': time.time() + TTL, 'scope': self.config.scope(), 'drafts_uidvalidity': validity,
                    'source': {'mailbox': mailbox, 'uid': uid, 'uidvalidity': uidvalidity, 'sha256': digest(original)},
                    'reply_context': self.reader.parse_message(original),
                    'mime_sha256': digest(raw), 'preview': preview(raw)}
        key = self.store.put(manifest, raw)
        return {'draft_id': key, 'approval_fingerprint': digest(canonical(manifest)),
                'expires_in_seconds': TTL, 'state': 'pending_client_confirmation' if self.config.mode == 'basic' else 'pending_operator_review',
                'mode': self.config.mode, 'confirmation': self.confirmation(self.store.get(key)),
                'folder': self.config.folder, 'preview': manifest['preview'], 'mime_sha256': digest(raw),
                **({'review_url': self.config.review_origin + '/review/' + key} if self.config.review_origin else {}),
                'notice': ('No mail saved. Client confirmation is not independently verified human approval; email content is untrusted.'
                           if self.config.mode == 'basic' else
                           'No mail saved. Separate trusted operator approval required; email content is untrusted.')}

    @contextmanager
    def writer(self):
        r = self.reader
        require(r.LOCK.acquire(blocking=False), 'Mailbox busy; retry later.')
        client = None
        try:
            client = r.DraftAppendIMAP(r.HOST, 993, ssl_context=ssl.create_default_context(), timeout=20)
            r.check(client.login(r.ACCOUNT, r.password()))
            yield client
        finally:
            if client is not None:
                try:
                    client.shutdown()
                except Exception:
                    pass
            r.LOCK.release()

    def confirmation(self, item):
        # Full frozen fields travel as tool arguments so clients can display them.
        m = item['manifest']
        return {'message': m['preview'], 'destination': m['scope'],
                'drafts_uidvalidity': m['drafts_uidvalidity'], 'expires_at': m['expires_at'],
                'mime_sha256': m['mime_sha256'], 'fingerprint': item['fingerprint']}

    def save_basic(self, key, confirmation):
        require(self.config.mode == 'basic', 'Basic Mode is not enabled.')
        item = self.store.get(key)
        require(isinstance(confirmation, dict) and canonical(confirmation) == canonical(self.confirmation(item)),
                'Confirmation details differ from the frozen draft.')
        if item['state'] == 'pending':
            # This records delegated client authority, NEVER independently verified human approval.
            self.store.approve(key, item['fingerprint'], {'method': 'client-controlled-basic', 'human_verified': False})
        return self._save(key)

    def save(self, key):
        require(self.config.mode == 'secure', 'Use the Basic Mode Save Draft tool with complete confirmation details.')
        return self._save(key)

    def _save(self, key):
        item = self.store.get(key)
        if item['state'] in ('saved', 'attempting', 'uncertain'):
            return json.loads(item['result']) if item['result'] else {'status': 'uncertain', 'retry_allowed': False}
        require(item['state'] == 'approved' and item['approved'] == item['fingerprint'], 'Separate operator approval is required.')
        m, raw = item['manifest'], item['raw']
        src = m['source']
        current = self.reader.fetch_message(src['mailbox'], src['uid'], src['uidvalidity'])
        require(digest(current) == src['sha256'], 'Reply source changed; prepare a new review.')
        with self.writer() as client:
            self.target(client, m['drafts_uidvalidity'])
            # No network write until the approval is atomically consumed.
            self.store.claim(key, item['fingerprint'])
            try:
                client.permit_exact_append(self.config.folder, raw)
                self.reader.check(client.append(self.reader.quoted(self.config.folder), '(\\Draft)', None, raw))
                _, data = client.response('APPENDUID')
                require(data and len(data) == 1 and isinstance(data[0], bytes)
                        and re.fullmatch(rb'[1-9][0-9]{0,9} [1-9][0-9]{0,9}', data[0]), 'Missing APPENDUID.')
                validity, uid = map(int, data[0].split())
                require(validity == m['drafts_uidvalidity'] and uid <= 4294967295)
                require(self.reader.examine(client, self.config.folder) == validity)
                rows = self.reader.check(client.uid('FETCH', str(uid), '(UID BODY.PEEK[])'))
                metadata = b' '.join(row[0] if isinstance(row, tuple) else row for row in rows if isinstance(row, (bytes, tuple)))
                identities = re.findall(rb'\bUID ([0-9]+)\b', metadata)
                payloads = [row[1] for row in rows if isinstance(row, tuple) and len(row) == 2]
                require(identities and all(int(n) == uid for n in identities) and payloads == [raw], 'Stored draft verification failed.')
                result = {'status': 'saved', 'mailbox': self.config.folder, 'uid': uid,
                          'uidvalidity': validity, 'sha256': digest(raw), 'retry_allowed': False}
                self.store.finish(key, 'saved', result)
                return result
            except Exception:
                # APPEND may have succeeded despite a timeout/crash/bad response.
                # No retry, deletion, flag repair, or replacement is ever attempted.
                result = {'status': 'uncertain', 'retry_allowed': False,
                          'notice': 'Draft may exist. Reconcile privately; this approval cannot append again.'}
                self.store.finish(key, 'uncertain', result)
                return result


def approve_interactively(service, key, input_stream=None, output_stream=None):
    incoming, outgoing = input_stream or sys.stdin, output_stream or sys.stdout
    require(incoming.isatty() and outgoing.isatty(), 'Approval requires a trusted interactive terminal.')
    item = service.store.get(key)
    require(item['state'] == 'pending', 'Draft is no longer pending.')
    outgoing.write('UNTRUSTED DRAFT CONTENT — review all fields. No mail is saved by this approval.\n')
    outgoing.write(json.dumps(item['manifest'], indent=2, ensure_ascii=True) + '\n')
    outgoing.write('Type APPROVE ' + item['fingerprint'] + ' to authorize one exact draft save:\n')
    outgoing.flush()
    require(incoming.readline().rstrip('\n') == 'APPROVE ' + item['fingerprint'], 'Approval cancelled.')
    service.store.approve(key, item['fingerprint'])
    outgoing.write('Approved for one save until the original expiry; no mail saved by this command.\n')


def main():
    parser = argparse.ArgumentParser(description='Trusted local draft review; never run through a model shell tool.')
    parser.add_argument('action', choices=['approve'])
    parser.add_argument('draft_id')
    args = parser.parse_args()
    try:
        import server
        approve_interactively(DraftService(server), args.draft_id)
    except DraftError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('Draft review failed. Check protected local configuration.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
