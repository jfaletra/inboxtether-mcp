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
from send_client import SendError, peer_uid, receive, require, transmit

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
    for path in (config.state_dir, config.password_file.parent, config.socket_path.parent, config_path.absolute().parent):
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

    @classmethod
    def load(cls, path):
        obj = json.loads(private_file(path))
        require(obj.pop('enabled', False) is True, 'Sending is disabled.')
        require(obj.pop('mode', None) == 'secure', 'Only Secure Send Mode exists.')
        require(set(obj) == set(cls.__dataclass_fields__), 'Unknown or missing sender configuration.')
        obj = dict(obj)
        for field in ('password_file', 'state_dir', 'socket_path'):
            obj[field] = Path(obj[field])
        cfg = cls(**obj)
        cfg.validate()
        return cfg

    def validate(self):
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
        return {'operation': 'smtp-send', 'mode': 'secure', 'identity': self.identity,
                'envelope_sender': self.identity, 'smtp_host': self.smtp_host,
                'smtp_port': self.smtp_port, 'tls': self.tls, 'smtp_username': self.smtp_username,
                'credential_reference': digest(str(self.password_file).encode('utf-8')), 'client_uid': self.client_uid}


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
        require(manifest['expires_at'] == item['expires'] and manifest['scope'] == self.config.scope(), 'Send configuration changed.')
        item['manifest'] = manifest
        return item

    def claim(self, key, fingerprint):
        # Approval and durable single-use claim are one transaction; no MCP operation can call this.
        item = self.get(key)
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
        manifest, raw = prepare_message(self.config, arguments)
        key = self.store.put(manifest, raw)
        return {'send_id': key, 'fingerprint': digest(canonical(manifest)), 'manifest': manifest,
                'status': 'pending_independent_approval', 'notice': 'No email sent. Approval is only through the trusted operator interface.'}

    def status(self, key):
        item = self.store.get(key)
        status = item['state']
        if status == 'attempting':
            status = 'uncertain'  # Includes worker still running; never claim delivery or retry.
        if status == 'pending' and item['expires'] <= time.time():
            status = 'expired'
        return {'status': status, 'retry_allowed': False, 'sent_copy': 'not-written',
                'mime_sha256': item['manifest']['mime_sha256']}

    def approve_and_send(self, key, fingerprint):
        item = self.store.claim(key, fingerprint)
        result = submit(self.config, item)
        try:
            self.store.finish(key, result)
        except Exception:
            # Durable 'attempting' survives, and is always reported uncertain.
            return {'status': 'uncertain', 'retry_allowed': False, 'sent_copy': 'not-written'}
        return result


def submit(config, item):
    """One SMTP transaction. DATA is never issued after any recipient refusal."""
    client = None
    phase = 'pre-data'
    result = {'status': 'failed', 'retry_allowed': False, 'sent_copy': 'not-written',
              'mime_sha256': item['manifest']['mime_sha256']}
    try:
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


def serve(config):
    config.validate()
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
                    connection.settimeout(5)
                    try:
                        require(peer_uid(connection) == config.client_uid, 'Unauthorized IPC identity.')
                        packet = receive(connection)
                        require(set(packet) == {'operation', 'arguments'})
                        result = dispatch(service, packet['operation'], packet['arguments'])
                        transmit(connection, {'ok': True, 'result': result})
                    except Exception:
                        # No server replies, message content, credentials, or identifiers logged.
                        try:
                            transmit(connection, {'ok': False, 'error': 'Send request rejected.'})
                        except Exception:
                            pass
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


def main():
    parser = argparse.ArgumentParser(description='Trusted local send authority; never expose to an AI shell.')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('command', choices=('serve', 'review', 'approve-send', 'reject', 'status'))
    parser.add_argument('send_id', nargs='?')
    parser.add_argument('--review-dir', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config = SenderConfig.load(args.config)
        trusted_installation(config, args.config)
        service = SendService(config)
        if args.command == 'serve':
            serve(config)
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
        elif args.command == 'reject':
            service.store.reject(args.send_id)
            print('{"status":"rejected"}')
        else:
            print(json.dumps(service.status(args.send_id)))
    except Exception:
        print('Trusted send operation failed or was cancelled; inspect status before any further action.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
