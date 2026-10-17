"""Secure-only, separately owned send staging and terminal approval authority.

No network connection is made by preparation, review, status, or rejection.
Never run this account's terminal command for an AI, or grant it model shell access.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime
import hashlib
import imaplib
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import socket
import sqlite3
import ssl
import stat
import sys
import time
from types import SimpleNamespace

from draft_assistant import address, canonical, digest, recipients, reply_bytes, text
from send_client import IPC_SECONDS, SendError, peer_uid, receive, remaining, require, transmit

TTL = 600
MAX_MIME = 1_048_576
MAX_ATTACHMENT = 262_144
MAX_ATTACHMENTS_TOTAL = 524_288
MAX_RECORDS = 256
ID = re.compile(r'[0-9a-f]{64}')
TYPES = {'text/plain': {'.txt'}, 'application/pdf': {'.pdf'},
         'image/png': {'.png'}, 'image/jpeg': {'.jpg', '.jpeg'}}



def trusted_ancestors(path):
    """Reject mutable/symlinked trusted paths; allow the root-owned sticky /tmp boundary."""
    for parent in (path, *path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.geteuid()), 'Untrusted sender path.')
        writable = stat.S_IMODE(info.st_mode) & 0o022
        require(not writable or (info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)), 'Writable sender ancestor.')


def trusted_installation(config, config_path):
    # The MCP account must not be able to replace code/configuration loaded by the sender.
    for path in (Path(__file__), Path(__file__).with_name('send_client.py'), Path(__file__).with_name('draft_assistant.py')):
        trusted_ancestors(path.absolute().parent)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.geteuid())
                and not (stat.S_IMODE(info.st_mode) & 0o022), 'Untrusted sender code.')
    private_parents = (config.sent_copy.password_file.parent,) if config.sent_copy else ()
    for path in (config.state_dir, config.password_file.parent, config.socket_path.parent, config_path.absolute().parent, *private_parents):
        trusted_ancestors(path)


def private_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe sender private file.')
        raw = os.read(fd, MAX_MIME + 1)
        require(len(raw) <= MAX_MIME, 'Sender private file too large.')
        return raw
    finally:
        os.close(fd)


@contextmanager
def sent_connection(config):
    sent = config.sent_copy
    require(sent is not None and sent.enabled, 'Sent synchronization is disabled.')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    client = None
    try:
        client = imaplib.IMAP4_SSL(sent.host, sent.port, ssl_context=context, timeout=10)
        secret = private_file(sent.password_file).decode('utf-8').rstrip('\r\n')
        require(0 < len(secret) <= 4096 and not any(c in secret for c in '\r\n\x00'))
        require(client.login(sent.username, secret)[0] == 'OK', 'IMAP authentication failed.')
        secret = None
        # Providers may change advertised capabilities after authentication.
        typ, rows = client.capability()
        require(typ == 'OK' and all(isinstance(r, bytes) for r in rows), 'IMAP capability refresh failed.')
        caps = b' '.join(rows).upper().split()
        require(b'UIDPLUS' in caps, 'Sent verification requires UIDPLUS.')
        yield client
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                try:
                    client.shutdown()
                except Exception:
                    pass


def sent_folders(client):
    typ, rows = client.list('""', '"*"')
    require(typ == 'OK' and len(rows) <= 1024, 'Sent folder discovery failed.')
    folders = []
    prefix = rb'\(([^)]*)\) (?:NIL|"(?:[^"\\]|\\.)*") '
    for row in rows:
        if isinstance(row, tuple):
            header, wire = row
            match = re.fullmatch(prefix + rb'\{([0-9]+)\}', header)
            require(match is not None and int(match[2]) == len(wire), 'Invalid literal folder.')
        else:
            require(isinstance(row, bytes))
            match = re.fullmatch(prefix + rb'("(?:[^"\\]|\\.)*"|[^\s"{}]+)', row)
            require(match is not None, 'Invalid folder response.')
            wire = match[2]
            if wire.startswith(b'"'):
                wire = re.sub(rb'\\(.)', rb'\1', wire[1:-1])
        flags = match[1].upper().split()
        if b'\\NOSELECT' not in flags:
            folders.append((folder_name(wire), b'\\SENT' in flags))
    return folders


def choose_sent(client, override):
    folders = sent_folders(client)
    matches = [name for name, special in folders if name == override] if override is not None else [name for name, special in folders if special]
    require(len(matches) == 1, 'Sent folder missing or ambiguous; configure an explicit existing folder.')
    return matches[0]


def discover_sent(config):
    """Trusted operator setup only. Broker prepares offline from this private pin."""
    with sent_connection(config) as client:
        folder = choose_sent(client, config.sent_copy.folder)
        validity = sent_select(client, folder)
    pin = {'policy': config.sent_copy.scope(), 'folder': folder, 'uidvalidity': validity}
    trusted_ancestors(config.state_dir)
    # Atomic update, never follow an existing destination symlink.
    path = config.state_dir / 'sent-destination.json'
    temporary = config.state_dir / ('sent-pin-' + secrets.token_hex(16))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(canonical(pin))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {'sent_folder': folder, 'selection': 'override' if config.sent_copy.folder is not None else 'special-use',
            'notice': 'Pinned for future approvals; no message appended.'}


def sent_destination(config):
    sent = config.sent_copy
    require(sent is not None and sent.enabled, 'Sent synchronization disabled.')
    pin = json.loads(private_file(config.state_dir / 'sent-destination.json'))
    require(set(pin) == {'policy', 'folder', 'uidvalidity'} and pin['policy'] == sent.scope(), 'Run trusted discover-sent after configuration changes.')
    folder_wire(pin['folder'])
    require(type(pin['uidvalidity']) is int and 0 < pin['uidvalidity'] <= 4294967295, 'Invalid pinned mailbox identity.')
    if sent.folder is not None:
        require(pin['folder'] == sent.folder, 'Pinned folder differs from override.')
    return pin


def sent_select(client, folder):
    require(client.select(folder_wire(folder), readonly=True)[0] == 'OK', 'Sent folder unavailable.')
    kind, values = client.response('UIDVALIDITY')
    require(kind == 'UIDVALIDITY' and values and re.fullmatch(rb'[1-9][0-9]*', values[0]), 'Missing UIDVALIDITY.')
    validity = int(values[0])
    require(validity <= 4294967295)
    return validity


def sent_fetch(client, uid, expected):
    # Check size before requesting the bounded exact message. A malicious IMAP
    # server is outside the trust model; imaplib itself may allocate literals.
    typ, rows = client.uid('FETCH', str(uid), '(RFC822.SIZE)')
    require(typ == 'OK')
    metadata = b' '.join(r for r in rows if isinstance(r, bytes))
    require(re.search(rb'\bUID ' + str(uid).encode() + rb'\b', metadata, re.I))
    sizes = re.findall(rb'RFC822.SIZE ([0-9]+)', metadata, re.I)
    require(len(sizes) == 1 and int(sizes[0]) == len(expected), 'Stored MIME size differs.')
    typ, rows = client.uid('FETCH', str(uid), '(BODY.PEEK[])')
    require(typ == 'OK')
    literals = [r for r in rows if isinstance(r, tuple)]
    require(len(literals) == 1 and re.search(rb'\bUID ' + str(uid).encode() + rb'\b', literals[0][0], re.I))
    require(literals[0][1] == expected, 'Stored MIME bytes differ.')


def find_sent(client, item):
    mid = item['manifest']['preview']['Message-ID']
    require(re.fullmatch(r'<[A-Za-z0-9._@+\-]{1,254}>', mid), 'Unsafe Message-ID.')
    typ, rows = client.uid('SEARCH', None, 'HEADER', 'Message-ID', '"' + mid + '"')
    require(typ == 'OK' and len(rows) == 1 and isinstance(rows[0], bytes))
    uids = rows[0].split()
    require(len(uids) <= 20 and all(re.fullmatch(rb'[1-9][0-9]*', u) and int(u) <= 4294967295 for u in uids), 'Unbounded or invalid Sent matches.')
    for uid in uids:
        # A conflicting same-ID message is a reconciliation problem; fail closed.
        sent_fetch(client, int(uid), item['raw'])
    require(len(uids) <= 1, 'Duplicate existing Sent copies; operator review required.')
    return int(uids[0]) if uids else None


def file_sent_copy(config, item, reconcile=False):
    """No SMTP path, no retries. Caller durably claims BEFORE any IMAP I/O."""
    result = {'state': 'uncertain' if reconcile else 'failed', 'retry_allowed': False,
              'mime_sha256': item['manifest']['mime_sha256']}
    appending = False
    try:
        require(digest(item['raw']) == item['manifest']['mime_sha256'])
        pin = item['manifest']['sent_filing']
        require(config.sent_copy and config.sent_copy.enabled and pin['policy'] == config.sent_copy.scope())
        folder = pin['folder']
        with sent_connection(config) as client:
            # Verify the exact pinned target exists; never rediscover a different destination.
            require(choose_sent(client, folder) == folder)
            validity = sent_select(client, folder)
            require(validity == pin['uidvalidity'], 'Pinned mailbox identity changed.')
            uid = find_sent(client, item)
            if uid is not None:
                result.update(state='saved', folder=folder, uidvalidity=validity, uid=uid, reconciled=True)
                return result
            if reconcile:
                return result  # Absence is not proof an interrupted APPEND never completed.
            appending = True
            typ, _ = client.append(folder_wire(folder), '(\\Seen)', None, item['raw'])
            if typ in ('NO', 'BAD'):
                result['state'] = 'failed'
                return result
            require(typ == 'OK', 'Unknown APPEND result.')
            kind, values = client.response('APPENDUID')
            require(kind == 'APPENDUID' and values and re.fullmatch(rb'[1-9][0-9]* [1-9][0-9]*', values[0]), 'Missing APPENDUID.')
            returned_validity, uid = map(int, values[0].split())
            require(returned_validity == validity and uid <= 4294967295, 'Mailbox identity changed.')
            sent_fetch(client, uid, item['raw'])
            result.update(state='saved', folder=folder, uidvalidity=validity, uid=uid, reconciled=False)
    except Exception:
        # Never expose IMAP responses, credentials, email bodies or exception text.
        result['state'] = 'uncertain' if appending or reconcile else 'failed'
    return result


@dataclass(frozen=True)
class SentConfig:
    """Separate IMAP credential; resolved destinations never come from MCP arguments."""
    host: str
    username: str
    password_file: Path
    port: int = 993
    enabled: bool = False
    folder: str | None = None

    def validate(self):
        require(type(self.enabled) is bool and isinstance(self.host, str)
                and re.fullmatch(r'[A-Za-z0-9.-]{1,253}', self.host), 'Invalid Sent configuration.')
        require(type(self.port) is int and 1 <= self.port <= 65535)
        address(self.username)
        require(isinstance(self.password_file, Path) and self.password_file.is_absolute())
        if self.folder is not None:
            folder_wire(self.folder)

    def scope(self):
        return {'host': self.host, 'port': self.port, 'username': self.username,
                'credential_reference': digest(str(self.password_file).encode()),
                'folder_override': self.folder}


def folder_wire(folder):
    """Canonical IMAP modified UTF-7, quoted as one protocol argument."""
    text(folder, 256)
    require(folder and not any(ord(c) < 32 or ord(c) == 127 for c in folder), 'Unsafe Sent folder.')
    chunks, buffered = [], []
    def flush():
        if buffered:
            chunks.append('&' + base64.b64encode(''.join(buffered).encode('utf-16be')).decode().rstrip('=').replace('/', ',') + '-')
            buffered.clear()
    for c in folder:
        if 32 <= ord(c) <= 126:
            flush()
            chunks.append('&-' if c == '&' else c)
        else:
            buffered.append(c)
    flush()
    encoded = ''.join(chunks)
    return '"' + encoded.replace('\\', '\\\\').replace('"', '\\"') + '"'


def folder_name(wire):
    def decode(match):
        value = match.group(1)
        return '&' if not value else base64.b64decode(value.replace(',', '/') + '=' * (-len(value) % 4), validate=True).decode('utf-16be')
    value = re.sub(r'&([A-Za-z0-9+,]*)-', decode, wire.decode('ascii'))
    folder_wire(value)
    return value


@dataclass(frozen=True)
class SenderConfig:
    identity: str
    smtp_host: str
    smtp_port: int
    tls: str
    smtp_username: str
    password_file: Path
    state_dir: Path
    socket_path: Path
    client_uid: int
    enabled: bool = False
    sent_copy: SentConfig | None = None

    @classmethod
    def load(cls, path, read_only=False):
        obj = json.loads(private_file(path))
        enabled = obj.pop('enabled', False)
        require(type(enabled) is bool and (enabled or read_only), 'Sending is disabled.')
        require(obj.pop('mode', None) == 'secure', 'Only Secure Send Mode exists.')
        obj.setdefault('sent_copy', None)
        sent = obj['sent_copy']
        if sent is not None:
            require(isinstance(sent, dict) and set(sent) <= set(SentConfig.__dataclass_fields__), 'Invalid Sent configuration.')
            sent = dict(sent)
            sent['password_file'] = Path(sent['password_file'])
            obj['sent_copy'] = SentConfig(**sent)
        require(set(obj) == set(cls.__dataclass_fields__) - {'enabled'}, 'Unknown or missing sender configuration.')
        obj = dict(obj)
        for field in ('password_file', 'state_dir', 'socket_path'):
            obj[field] = Path(obj[field])
        cfg = cls(**obj, enabled=enabled)
        cfg.validate()
        return cfg

    def validate(self):
        require(type(self.enabled) is bool, 'Invalid sending setting.')
        if self.sent_copy is not None:
            require(isinstance(self.sent_copy, SentConfig))
            self.sent_copy.validate()
            require(self.sent_copy.username == self.identity, 'Sent mailbox must match sending identity.')
            require(self.sent_copy.password_file != self.password_file, 'Separate IMAP credential required.')
        address(self.identity)
        text(self.smtp_username, 254)
        require(isinstance(self.smtp_host, str) and re.fullmatch(r'[A-Za-z0-9.-]{1,253}', self.smtp_host))
        require(type(self.smtp_port) is int and 1 <= self.smtp_port <= 65535)
        require(self.tls in ('implicit', 'starttls'), 'Verified TLS is mandatory.')
        require(all(p.is_absolute() for p in (self.password_file, self.state_dir, self.socket_path)))
        require(type(self.client_uid) is int and self.client_uid > 0 and self.client_uid != os.geteuid(),
                'MCP and sender identities must differ.')
        require(os.geteuid() > 0, 'Do not run the trusted sender as root.')

    def scope(self):
        scope = {'operation': 'smtp-send', 'mode': 'secure', 'identity': self.identity,
                'envelope_sender': self.identity, 'smtp_host': self.smtp_host,
                'smtp_port': self.smtp_port, 'tls': self.tls, 'smtp_username': self.smtp_username,
                'credential_reference': digest(str(self.password_file).encode('utf-8')), 'client_uid': self.client_uid}
        if self.sent_copy and self.sent_copy.enabled:
            scope['sent_copy'] = self.sent_copy.scope()
        return scope


def attachment(value):
    require(isinstance(value, dict) and set(value) == {'filename', 'content_type', 'data_base64'})
    name, kind, packed = value['filename'], value['content_type'], value['data_base64']
    require(isinstance(name, str) and 0 < len(name) <= 128 and name.isascii())
    require(all(32 <= ord(c) < 127 for c in name) and not any(c in name for c in '/\\:') and not name.startswith('.'))
    require(kind in TYPES and Path(name).suffix.lower() in TYPES[kind], 'Unsupported attachment type.')
    require(isinstance(packed, str) and len(packed) <= 4 * ((MAX_ATTACHMENT + 2) // 3))
    try:
        data = base64.b64decode(packed, validate=True)
    except (ValueError, TypeError):
        raise SendError('Invalid attachment encoding.') from None
    require(0 < len(data) <= MAX_ATTACHMENT)
    signatures = {'application/pdf': b'%PDF-', 'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff'}
    if kind in signatures:
        require(data.startswith(signatures[kind]), 'Attachment signature mismatch.')
    else:
        decoded = data.decode('utf-8')
        text(decoded, MAX_ATTACHMENT, multiline=True)
    return name, kind, data


def message_view(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_MIME)
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    require(not msg.defects and not msg.get_all('Bcc'), 'Unsafe staged MIME.')
    require(all(len(msg.get_all(h, [])) <= 1 for h in ('From', 'To', 'Cc', 'Subject', 'Date', 'Message-ID', 'In-Reply-To', 'References')))
    parts = list(msg.iter_parts()) if msg.is_multipart() else [msg]
    require(1 <= len(parts) <= 6 and parts[0].get_content_type() == 'text/plain' and not parts[0].is_multipart())
    body = parts[0].get_content().replace('\r\n', '\n')
    text(body, 20001, multiline=True)
    files = []
    for part in parts[1:]:
        require(not part.is_multipart() and not part.defects and part.get_content_disposition() == 'attachment')
        data = part.get_payload(decode=True)
        name, kind, data = attachment({'filename': part.get_filename(), 'content_type': part.get_content_type(),
                                      'data_base64': base64.b64encode(data).decode('ascii')})
        files.append({'filename': name, 'content_type': kind, 'size_bytes': len(data), 'sha256': digest(data)})
    return {**{name: str(msg.get(name, '')) for name in ('From', 'To', 'Cc', 'Subject', 'Date', 'Message-ID', 'In-Reply-To', 'References')},
            'body': body, 'attachments': files}


def prepare_message(config, arguments):
    require(isinstance(arguments, dict) and set(arguments) <= {'to', 'cc', 'bcc', 'subject', 'body', 'attachments', 'reply'})
    to, cc, bcc = recipients(arguments.get('to'), arguments.get('cc'), arguments.get('bcc'))
    subject = text(arguments.get('subject'), 200)
    body = text(arguments.get('body'), 20000, multiline=True)
    files = arguments.get('attachments', [])
    require(isinstance(files, list) and len(files) <= 5)
    decoded = [attachment(v) for v in files]
    require(sum(len(v[2]) for v in decoded) <= MAX_ATTACHMENTS_TOTAL)
    require(len({v[0].casefold() for v in decoded}) == len(decoded), 'Duplicate attachment names.')
    reply = arguments.get('reply')
    if reply is not None:
        require(isinstance(reply, dict) and set(reply) == {'source', 'headers_base64', 'context'})
        require(isinstance(reply['source'], dict) and set(reply['source']) == {'mailbox', 'uid', 'uidvalidity', 'sha256'})
        text(reply['source']['mailbox'], 256)
        require(all(type(reply['source'][k]) is int and 0 < reply['source'][k] <= 4294967295 for k in ('uid', 'uidvalidity')))
        require(isinstance(reply['source']['sha256'], str) and ID.fullmatch(reply['source']['sha256']))
        require(isinstance(reply['context'], dict) and len(canonical(reply['context'])) <= 65536)
        require(isinstance(reply['headers_base64'], str) and len(reply['headers_base64']) <= 16384)
        original = base64.b64decode(reply['headers_base64'], validate=True)
        raw = reply_bytes(SimpleNamespace(account=config.identity), original, to, subject, body, cc, bcc)
        msg = BytesParser(policy=policy.SMTP).parsebytes(raw)
        if 'Bcc' in msg:
            del msg['Bcc']
    else:
        msg = EmailMessage(policy=policy.SMTP)
        msg['From'], msg['To'], msg['Subject'] = config.identity, ', '.join(to), subject
        if cc:
            msg['Cc'] = ', '.join(cc)
        msg['Date'] = format_datetime(datetime.now(timezone.utc))
        msg['Message-ID'] = '<' + secrets.token_hex(24) + '@' + config.identity.rsplit('@', 1)[1] + '>'
        msg.set_content(body, subtype='plain', charset='utf-8', cte='quoted-printable')
    for name, kind, data in decoded:
        main, sub = kind.split('/')
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name, cte='base64')
    raw = msg.as_bytes(policy=policy.SMTP)
    require(len(raw) <= MAX_MIME, 'Serialized send message exceeds 1 MiB.')
    view = message_view(raw)
    manifest = {'version': 1, 'expires_at': time.time() + TTL, 'scope': config.scope(),
                'recipients': {'to': to, 'cc': cc, 'bcc': bcc}, 'preview': view,
                'reply_context': reply, 'mime_sha256': digest(raw), 'sent_copy': 'not-written'}
    if config.sent_copy and config.sent_copy.enabled:
        manifest['sent_filing'] = sent_destination(config)
    return manifest, raw


class SendStore:
    """Sender-owned records. Attempt receipts are NEVER purged by staging expiry."""
    def __init__(self, config):
        self.config = config

    @contextmanager
    def db(self):
        directory = self.config.state_dir
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o700, 'Unsafe sender state directory.')
        path = directory / 'sends.sqlite3'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            i = os.fstat(fd)
            require(stat.S_ISREG(i.st_mode) and i.st_uid == os.geteuid() and stat.S_IMODE(i.st_mode) == 0o600)
        finally:
            os.close(fd)
        db = sqlite3.connect(path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS sends (id TEXT PRIMARY KEY, manifest BLOB NOT NULL, raw BLOB NOT NULL, fingerprint TEXT NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL, actor BLOB, result BLOB)')
            db.execute('CREATE TABLE IF NOT EXISTS sent_copies (send_id TEXT PRIMARY KEY, state TEXT NOT NULL, result BLOB)')
            db.commit()
            yield db
        finally:
            db.close()

    def put(self, manifest, raw):
        key = secrets.token_hex(32)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("DELETE FROM sends WHERE state='pending' AND expires<?", (time.time(),))
            require(db.execute('SELECT count(*) FROM sends').fetchone()[0] < MAX_RECORDS, 'Sender storage limit reached; operator maintenance required.')
            require(db.execute("SELECT count(*) FROM sends WHERE state='pending'").fetchone()[0] < 32, 'Pending send limit reached.')
            packed = canonical(manifest)
            db.execute('INSERT INTO sends VALUES (?,?,?,?,?,?,?,?)', (key, packed, raw, digest(packed), manifest['expires_at'], 'pending', None, None))
            db.commit()
        return key

    def get(self, key):
        require(isinstance(key, str) and ID.fullmatch(key), 'Invalid send ID.')
        with self.db() as db:
            row = db.execute('SELECT * FROM sends WHERE id=?', (key,)).fetchone()
        require(row is not None, 'Send request not found.')
        item = dict(row)
        manifest = json.loads(item['manifest'])
        require(canonical(manifest) == item['manifest'] and digest(item['manifest']) == item['fingerprint'], 'Send integrity failure.')
        require(digest(item['raw']) == manifest['mime_sha256'] and message_view(item['raw']) == manifest['preview'], 'Send integrity failure.')
        require(manifest['expires_at'] == item['expires'], 'Send integrity failure.')
        item['manifest'] = manifest
        return item

    def eligible(self, item):
        require(self.config.enabled, 'Sending is disabled.')
        require(item['manifest']['scope'] == self.config.scope(), 'Send configuration changed; prepare a new review.')
        if 'sent_filing' in item['manifest']:
            require(item['manifest']['sent_filing'] == sent_destination(self.config), 'Sent destination changed; prepare a new review.')

    def claim(self, key, fingerprint):
        # Approval and durable single-use claim are one transaction; no MCP operation can call this.
        item = self.get(key)
        self.eligible(item)
        require(fingerprint == item['fingerprint'], 'Reviewed content changed.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE sends SET state='attempting', actor=? WHERE id=? AND state='pending' AND fingerprint=? AND expires>?",
                                 (canonical({'method': 'trusted-terminal', 'uid': os.geteuid(), 'at': time.time()}), key, fingerprint, time.time())).rowcount
            require(changed == 1, 'Send expired, rejected, or already attempted.')
            db.commit()
        return item

    def finish(self, key, result):
        with self.db() as db:
            changed = db.execute("UPDATE sends SET state=?,result=? WHERE id=? AND state='attempting'", (result['status'], canonical(result), key)).rowcount
            require(changed == 1, 'Send receipt could not be recorded.')
            db.commit()

    def filing(self, key):
        with self.db() as db:
            row = db.execute('SELECT state,result FROM sent_copies WHERE send_id=?', (key,)).fetchone()
        if row is None:
            return None
        require(row['state'] in ('attempting', 'saved', 'failed', 'uncertain'), 'Invalid filing state.')
        result = json.loads(row['result']) if row['result'] else {}
        require(isinstance(result, dict) and (not result or (result.get('state') == row['state']
                and result.get('retry_allowed') is False
                and result.get('mime_sha256') == self.get(key)['manifest']['mime_sha256'])), 'Invalid filing receipt.')
        require(row['state'] == 'attempting' or result, 'Missing filing receipt.')
        return {'state': row['state'], **result}

    def claim_filing(self, key):
        item = self.get(key)
        require(item['state'] == 'accepted' and item['result'] is not None
                and json.loads(item['result'])['status'] == 'accepted', 'SMTP acceptance not recorded.')
        require('sent_filing' in item['manifest'], 'Sent copy was not approved.')
        require(item['manifest']['scope'] == self.config.scope(), 'Configuration changed; filing blocked.')
        require(item['manifest']['sent_filing'] == sent_destination(self.config), 'Sent destination changed.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            n = db.execute("INSERT OR IGNORE INTO sent_copies VALUES (?,'attempting',NULL)", (key,)).rowcount
            require(n == 1, 'Filing already claimed; reconcile without appending.')
            db.commit()
        return item

    def finish_filing(self, key, result):
        require(result['state'] in ('saved', 'failed', 'uncertain') and result['retry_allowed'] is False
                and result['mime_sha256'] == self.get(key)['manifest']['mime_sha256'], 'Invalid filing result.')
        with self.db() as db:
            n = db.execute("UPDATE sent_copies SET state=?,result=? WHERE send_id=? AND state IN ('attempting','uncertain')",
                           (result['state'], canonical(result), key)).rowcount
            require(n == 1, 'Filing receipt update rejected.')
            db.commit()

    def reject(self, key):
        self.get(key)
        with self.db() as db:
            changed = db.execute("UPDATE sends SET state='rejected' WHERE id=? AND state='pending'", (key,)).rowcount
            require(changed == 1, 'Send is no longer pending.')
            db.commit()


class SendService:
    def __init__(self, config):
        config.validate()
        self.config, self.store = config, SendStore(config)

    def prepare(self, arguments):
        require(self.config.enabled, 'Sending is disabled.')
        manifest, raw = prepare_message(self.config, arguments)
        key = self.store.put(manifest, raw)
        return {'send_id': key, 'fingerprint': digest(canonical(manifest)), 'manifest': manifest,
                'status': 'pending_independent_approval', 'notice': 'No email sent. Approval is only through the trusted operator interface.'}

    def status(self, key, trusted=False):
        item = self.store.get(key)
        scope = item['manifest']['scope']
        # Historical operator reads survive all config changes. IPC never accepts
        # trusted=True: a new mailbox identity/client UID must not inherit receipts.
        if not trusted:
            require(scope.get('identity') == self.config.identity and scope.get('client_uid') == self.config.client_uid,
                    'Receipt belongs to a different owner; use the trusted operator interface.')
        status = item['state']
        if status == 'attempting':
            status = 'uncertain'
        if status == 'pending' and item['expires'] <= time.time():
            status = 'expired'
        result = {'status': status, 'retry_allowed': False, 'sent_copy': 'not-written',
                  'mime_sha256': item['manifest']['mime_sha256'],
                  'configuration_matches': scope == self.config.scope(), 'sending_enabled': self.config.enabled}
        filing = self.store.filing(key)
        if filing:
            result['sent_copy'] = 'uncertain' if filing['state'] == 'attempting' else filing['state']
            result['sent_copy_receipt'] = filing
        elif status == 'accepted' and 'sent_filing' in item['manifest']:
            result['sent_copy'] = 'pending'
        if trusted:
            receipt = json.loads(item['result']) if item['result'] else None
            require(receipt is None or (isinstance(receipt, dict) and receipt.get('status') == item['state']),
                    'Invalid historical receipt.')
            result.update(approved_scope=scope, receipt=receipt)
        return result

    def approve_and_send(self, key, fingerprint):
        item = self.store.claim(key, fingerprint)
        result = submit(self.config, item)
        try:
            self.store.finish(key, result)
        except Exception:
            # Durable 'attempting' survives, and is always reported uncertain.
            return {'status': 'uncertain', 'retry_allowed': False, 'sent_copy': 'not-written'}
        if result['status'] == 'accepted' and 'sent_filing' in item['manifest']:
            try:
                self.file_sent(key)
            except Exception:
                pass  # SMTP acceptance is final; filing can never call submit().
            return self.status(key, trusted=True)
        return result

    def file_sent(self, key):
        item = self.store.claim_filing(key)
        result = file_sent_copy(self.config, item)
        self.store.finish_filing(key, result)
        return result

    def reconcile_sent(self, key):
        item = self.store.get(key)
        require(item['state'] == 'accepted' and 'sent_filing' in item['manifest'])
        require(item['manifest']['scope'] == self.config.scope(), 'Configuration changed; reconciliation blocked.')
        prior = self.store.filing(key)
        require(prior and prior['state'] in ('attempting', 'uncertain'), 'No ambiguous filing to reconcile.')
        result = file_sent_copy(self.config, item, reconcile=True)
        self.store.finish_filing(key, result)
        return result


def submit(config, item):
    """One SMTP transaction. DATA is never issued after any recipient refusal."""
    client = None
    phase = 'pre-data'
    result = {'status': 'failed', 'retry_allowed': False, 'sent_copy': 'not-written',
              'mime_sha256': item['manifest']['mime_sha256']}
    try:
        require(config.enabled, 'Sending is disabled.')
        secret = private_file(config.password_file).decode('utf-8').rstrip('\r\n')
        require(secret and len(secret) <= 4096 and not any(c in secret for c in '\r\n\x00'))
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if config.tls == 'implicit':
            client = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30, context=context)
        else:
            client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
            require(client.ehlo()[0] == 250)
            require(client.has_extn('starttls'), 'TLS is mandatory.')
            client.starttls(context=context)
        require(client.ehlo()[0] == 250)
        client.login(config.smtp_username, secret)
        secret = None
        # Slow authentication cannot extend approval validity.
        require(item['expires'] > time.time(), 'Send approval expired before submission.')
        require(digest(item['raw']) == item['manifest']['mime_sha256'])
        require(client.mail(config.identity)[0] == 250)
        envelope = item['manifest']['recipients']
        for recipient in envelope['to'] + envelope['cc'] + envelope['bcc']:
            require(client.rcpt(recipient)[0] in (250, 251))
        require(item['expires'] > time.time(), 'Send approval expired before DATA.')
        phase = 'data'
        code, _ = client.data(item['raw'])
        if code == 250:
            result['status'] = 'accepted'  # Submission acceptance, NOT final delivery.
        elif 400 <= code <= 599:
            result['status'] = 'failed'
        else:
            result['status'] = 'uncertain'
    except smtplib.SMTPDataError:
        result['status'] = 'failed'  # Explicit rejection, still no automatic retry.
    except Exception:
        result['status'] = 'uncertain' if phase == 'data' else 'failed'
    finally:
        if client is not None:
            try:
                client.close()  # QUIT failure cannot turn a known acceptance into failure.
            except Exception:
                pass
    return result


def dispatch(service, operation, arguments):
    require(isinstance(arguments, dict))
    if operation == 'prepare':
        return service.prepare(arguments)
    if operation == 'status':
        require(set(arguments) == {'send_id'})
        return service.status(arguments['send_id'])
    raise SendError('Operation is not exposed to MCP.')


def handle_connection(service, config, connection, seconds=IPC_SECONDS):
    # One absolute monotonic deadline covers header, body, response and error path.
    # Never reset the budget for an incomplete frame or a rejected request.
    deadline = time.monotonic() + seconds
    try:
        require(peer_uid(connection) == config.client_uid, 'Unauthorized IPC identity.')
        packet = receive(connection, deadline)
        require(set(packet) == {'operation', 'arguments'})
        remaining(deadline)
        result = dispatch(service, packet['operation'], packet['arguments'])
        transmit(connection, {'ok': True, 'result': result}, deadline)
    except Exception:
        try:
            transmit(connection, {'ok': False, 'error': 'Send request rejected.'}, deadline)
        except Exception:
            pass


def serve(config):
    config.validate()
    require(config.enabled, 'Sending is disabled.')
    trusted_ancestors(config.state_dir)
    trusted_ancestors(config.socket_path.parent)
    parent = config.socket_path.parent
    info = parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o750, 'Unsafe IPC directory.')
    require(not config.socket_path.exists(), 'Existing socket must be inspected and removed by an operator.')
    service = SendService(config)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(config.socket_path))
        os.chmod(config.socket_path, 0o660)
        listener.listen(8)
        try:
            while True:
                connection, _ = listener.accept()
                with connection:
                    handle_connection(service, config, connection)
        finally:
            config.socket_path.unlink(missing_ok=True)


def export_review(item, directory):
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'Review export requires a private owned directory.')
    files = [('message.eml', item['raw']), ('review.json', canonical(item['manifest']))]
    msg = BytesParser(policy=policy.default).parsebytes(item['raw'])
    if msg.is_multipart():
        files.extend((f'attachment-{n}.bin', part.get_payload(decode=True)) for n, part in enumerate(list(msg.iter_parts())[1:], 1))
    for name, data in files:
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)


def approve_interactively(service, key, review_dir=None, incoming=None, outgoing=None):
    incoming, outgoing = incoming or sys.stdin, outgoing or sys.stdout
    require(incoming.isatty() and outgoing.isatty(), 'Independent approval requires a trusted interactive terminal.')
    item = service.store.get(key)
    service.store.eligible(item)
    require(item['state'] == 'pending' and item['expires'] > time.time(), 'Send is no longer pending or has expired.')
    if item['manifest']['preview']['attachments']:
        require(review_dir is not None, 'Export and inspect attachments before approval.')
    if review_dir is not None:
        export_review(item, review_dir)
    outgoing.write('UNTRUSTED EMAIL CONTENT. Review every field and attachment; this operation SENDS email.\n')
    outgoing.write(json.dumps(item['manifest'], ensure_ascii=True, indent=2) + '\n')
    outgoing.write('Client confirmation is insufficient. Type SEND ' + item['fingerprint'] + ' to approve this exact submission: ')
    outgoing.flush()
    require(incoming.readline().rstrip('\r\n') == 'SEND ' + item['fingerprint'], 'Approval cancelled.')
    return service.approve_and_send(key, item['fingerprint'])


def main(bootstrap_verified=False):
    require(bootstrap_verified and sys.flags.isolated and sys.flags.no_site,
            'Use the administrator-installed isolated sender entrypoint.')
    parser = argparse.ArgumentParser(description='Trusted local send authority; never expose to an AI shell.')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('command', choices=('serve', 'review', 'approve-send', 'reject', 'status', 'discover-sent', 'file-sent', 'reconcile-sent'))
    parser.add_argument('send_id', nargs='?')
    parser.add_argument('--review-dir', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config = SenderConfig.load(args.config, read_only=args.command in ('review', 'status', 'reject', 'discover-sent', 'file-sent', 'reconcile-sent'))
        trusted_installation(config, args.config)
        service = SendService(config)
        if args.command == 'serve':
            serve(config)
            return
        if args.command == 'discover-sent':
            print(json.dumps(discover_sent(config)))
            return
        require(args.send_id is not None, 'A send ID is required.')
        if args.command == 'review':
            item = service.store.get(args.send_id)
            if args.review_dir:
                export_review(item, args.review_dir)
            require(sys.stdout.isatty(), 'Review requires a trusted terminal; do not write message content to logs.')
            print(json.dumps({'fingerprint': item['fingerprint'], 'manifest': item['manifest']}, indent=2, ensure_ascii=True))
        elif args.command == 'approve-send':
            print(json.dumps(approve_interactively(service, args.send_id, args.review_dir)))
        elif args.command == 'file-sent':
            print(json.dumps(service.file_sent(args.send_id)))
        elif args.command == 'reconcile-sent':
            print(json.dumps(service.reconcile_sent(args.send_id)))
        elif args.command == 'reject':
            service.store.reject(args.send_id)
            print('{"status":"rejected"}')
        else:
            print(json.dumps(service.status(args.send_id, trusted=True)))
    except Exception:
        print('Trusted send operation failed or was cancelled; inspect status before any further action.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    raise SystemExit('Use the administrator-installed isolated sender entrypoint.')
