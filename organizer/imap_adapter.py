"""Opt-in IMAP adapter. Separate from Reader/Draft; native one-UID MOVE only."""
from contextlib import contextmanager
from dataclasses import replace
import imaplib
import ipaddress
import socket
import os
from pathlib import Path
import re
import ssl
import stat
import time
import hashlib

from .model import CATEGORIES, MAX_RAW, MAX_RUN, Message, OrganizerError, integer, persistent, require
from .service import MessageUnsupported
from .content import (MAX_HEADER, MAX_PART, MAX_TEXT_BYTES, MAX_MESSAGE_SIZE, MimeView,
                      TextSection, ContentRefused)
from .structure import metadata as parse_metadata, sections as describe_sections

METADATA = '(UID FLAGS INTERNALDATE RFC822.SIZE BODYSTRUCTURE)'
HEADER = '(UID BODY.PEEK[HEADER]<0.65537>)'
BODY = '(UID BODY.PEEK[])'  # negative-test sentinel; never generally permitted
CHUNK = 262144


def quoted(name):
    require(name in ('INBOX', *CATEGORIES), 'Folder outside organizer scope.')
    return '"' + name + '"'


def checked(response):
    require(response[0] == 'OK', 'Mailbox operation rejected; reconcile if attempted.')
    return response[1]


class GuardedIMAP(imaplib.IMAP4_SSL):
    """Reject mutations at dispatch, including non-PEEK fetches and general SELECT."""
    ALLOWED = {'CAPABILITY', 'LOGIN', 'LIST', 'EXAMINE', 'MYRIGHTS', 'UID', 'SELECT'}

    def __init__(self, *args, connect_ip=None, **kwargs):
        if connect_ip is not None:
            ipaddress.ip_address(connect_ip)
        self._connect_ip = connect_ip
        super().__init__(*args, **kwargs)

    def login(self, user, password):
        result = super().login(user, password)
        self.capabilities = ()
        rows = checked(self.capability())
        require(rows and all(isinstance(r, bytes) for r in rows), 'Authenticated capabilities unavailable.')
        self.capabilities = tuple(b' '.join(rows).decode('ascii').upper().split())
        return result

    def _command(self, name, *args):
        require(name in self.ALLOWED, 'IMAP command prohibited.')
        names = getattr(self, '_namespace_names', {n: quoted(n) for n in ('INBOX', *CATEGORIES)})
        if name in ('EXAMINE', 'MYRIGHTS'):
            require(len(args) == 1 and args[0] in names.values(), 'Folder prohibited.')
        elif name == 'LIST':
            require(len(args)==2 and args[0]=='""' and args[1] in names.values(), 'Mailbox listing prohibited.')
        elif name == 'SELECT':
            permit = getattr(self, '_select_permit', False)
            self._select_permit = False
            require(permit in names and args == (names[permit],), 'Read-write selection prohibited.')
        elif name == 'UID':
            require(bool(args), 'UID command prohibited.')
            if args[0] == 'MOVE':
                permit = getattr(self, '_move_permit', None)
                self._move_permit = None  # consume before entering the network layer
                require(permit is not None and args == ('MOVE', *permit), 'Unapproved move prohibited.')
            elif args[0] == 'FETCH':
                require(len(args) == 3 and re.fullmatch(r'[1-9][0-9]{0,9}', args[1]), 'Invalid FETCH identity.')
                item = args[2]
                permitted = item in (METADATA, HEADER)
                text = re.fullmatch(r'\(UID BODY\.PEEK\[([1-9][0-9]*(?:\.[1-9][0-9]*)*)\]<0\.' + str(MAX_PART+1) + r'>\)', item)
                if text:
                    permitted = text[1] in getattr(self, '_text_sections', set())
                raw_permit = getattr(self, '_raw_permit', None)
                self._raw_permit = None
                if raw_permit is not None and args == ('FETCH', *raw_permit):
                    permitted = True
                require(permitted, 'Marking, attachment or unsupported FETCH prohibited.')
            elif args[0] == 'SEARCH':
                require(len(args) == 4 and args[1] is None and args[2] == 'UID'
                        and re.fullmatch(r'[1-9][0-9]{0,9}:[1-9][0-9]{0,9}', args[3]), 'Unsupported search.')
            else:
                require(False, 'UID operation prohibited.')
        return super()._command(name, *args)

    def _create_socket(self, timeout):
        target = getattr(self, '_connect_ip', None)
        if target is None:
            return super()._create_socket(timeout)
        # Connect only to the pinned IP; retain self.host for TLS identity/SNI.
        require(not getattr(self, '_tls_established', False), 'Socket reuse prohibited.')
        raw = socket.create_connection((target, self.port), timeout)
        try:
            result = self.ssl_context.wrap_socket(raw, server_hostname=self.host)
            self._tls_established = True
            return result
        except BaseException:
            raw.close()
            raise

    def read(self, size):
        require(type(size) is int and 0 <= size <= MAX_RAW, 'Wire literal exceeds safety limit.')
        require(getattr(self, '_wire_bytes', 0) + size <= 8_388_608, 'Wire budget exceeded.')
        result = super().read(size)
        self._wire_bytes = getattr(self, '_wire_bytes', 0) + len(result)
        return result

    def readline(self):
        result = super().readline()
        self._wire_bytes = getattr(self, '_wire_bytes', 0) + len(result)
        require(self._wire_bytes <= 8_388_608, 'Wire budget exceeded.')
        return result


class IMAPMailbox:
    def __init__(self, host, account, password_file, *, live_enabled=False, client_factory=GuardedIMAP, login_account=None, namespace=None, connect_ip=None, corrective_enabled=False, port=993):
        require(live_enabled is True, 'Live IMAP adapter is disabled.')
        require(isinstance(host, str) and re.fullmatch(r'[A-Za-z0-9.-]+', host), 'Invalid fixed IMAP host.')
        require(isinstance(account, str) and 0 < len(account) <= 320 and not any(ord(c) < 32 for c in account), 'Invalid account.')
        require(type(corrective_enabled) is bool, 'Explicit corrective adapter setting required.')
        self.corrective_enabled=corrective_enabled
        require(type(port) is int and 1 <= port <= 65535, 'Invalid secure IMAP port.')
        self.port = port
        self.host, self.account, self.password_file, self.client_factory = host, account, Path(password_file), client_factory
        self.namespace = namespace
        self.namespace_sha256 = namespace.fingerprint if namespace is not None else ''
        if connect_ip is not None:
            require(type(connect_ip) is str, 'Fixed IP required.')
            try: ipaddress.ip_address(connect_ip)
            except ValueError: require(False, 'Fixed IP required.')
        self.connect_ip = connect_ip
        self.login_account = account if login_account is None else login_account
        require(type(self.login_account) is str and 0 < len(self.login_account) <= 320 and not any(ord(c)<32 for c in self.login_account), 'Invalid principal.')

    @contextmanager
    def connection(self):
        client = None
        fd = os.open(self.password_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe Organizer credential file.')
            raw = os.read(fd, 4097)
            require(0 < len(raw) <= 4096, 'Invalid Organizer credential.')
            secret = raw.decode('utf-8').rstrip('\r\n')
            require(bool(secret) and not any(c in secret for c in '\r\n\x00'), 'Invalid Organizer credential.')
            options = {'ssl_context':ssl.create_default_context(), 'timeout':15}
            if self.connect_ip is not None: options['connect_ip'] = self.connect_ip
            client = self.client_factory(self.host, self.port, **options)
            if self.namespace is not None:
                client._namespace_names = {n:'"'+self.namespace.path(n)+'"' for n in ('INBOX', *CATEGORIES)}
                client._namespace_validities = {n:self.namespace.identity(n) for n in ('INBOX', *CATEGORIES)}
            client._corrective_rights=self.corrective_enabled
            checked(client.login(self.login_account, secret))
            secret = None
            require({'MOVE', 'UIDPLUS', 'ACL'} <= set(client.capabilities), 'Required authenticated capabilities unavailable.')
            yield client
        except MessageUnsupported:
            raise
        except Exception:
            raise OrganizerError('Mailbox operation failed; no automatic retry after a move claim.') from None
        finally:
            os.close(fd)
            if client is not None:
                try:
                    client.shutdown()  # never CLOSE, LOGOUT side effects, or explicit EXPUNGE
                except Exception:
                    pass

    @staticmethod
    def _identity(client, name, expected=None, writable=False):
        wire = IMAPMailbox._wire(client, name)
        pinned = getattr(client, '_namespace_validities', {}).get(name)
        require(pinned is None or expected is None or pinned==expected, 'Configured mailbox identity mismatch.')
        checked(client.select(wire, readonly=not writable))
        _, rows = client.response('UIDVALIDITY')
        require(rows and len(rows) == 1 and isinstance(rows[0], bytes)
                and re.fullmatch(rb'[1-9][0-9]{0,9}', rows[0]), 'UIDVALIDITY unavailable.')
        uv = integer(int(rows[0]))
        require((expected is None or expected == uv) and (pinned is None or pinned==uv), 'Mailbox identity changed.')
        return uv

    @staticmethod
    def _wire(client, name):
        require(name in ('INBOX', *CATEGORIES), 'Folder outside organizer scope.')
        return getattr(client, '_namespace_names', {}).get(name, quoted(name))

    @staticmethod
    def _next_uid(client):
        _, rows = client.response('UIDNEXT')
        require(rows and len(rows) == 1 and isinstance(rows[0], bytes)
                and re.fullmatch(rb'[1-9][0-9]{0,9}', rows[0]), 'UIDNEXT unavailable.')
        return integer(int(rows[0]))

    @staticmethod
    def _rights(client, name, required):
        wire = IMAPMailbox._wire(client, name)
        rows = checked(client.myrights(wire))
        require(rows and len(rows) == 1 and isinstance(rows[0], bytes), 'Effective rights unavailable.')
        # Fixed ASCII names; refuse extensions/ambiguous mailbox responses.
        literal = re.escape(wire[1:-1].encode('ascii'))
        match = re.fullmatch(rb'(?:"' + literal + rb'"|' + literal + rb') ([A-Za-z0-9]*)', rows[0])
        require(match is not None and set(required) <= set(match[1].decode('ascii').lower()), 'Insufficient effective IMAP rights.')
        if getattr(client, '_namespace_validities', None) is not None:
            actual=set(match[1].decode('ascii').lower())
            corrective=getattr(client,'_corrective_rights',False)
            allowed=set(required) | (set('lriswted') if corrective else ({'d'} if set('te')<=set(required) else set()))
            require(actual<=allowed, 'Excess effective namespace rights; owner review required.')

    def inbox_identity(self):
        with self.connection() as c:
            uv = self._identity(c, 'INBOX')
            return uv, self._next_uid(c)

    def folder(self, name):
        require(name in CATEGORIES, 'Invalid category.')
        with self.connection() as c:
            # EXAMINE cannot create a missing folder; require exact SELECTABLE name.
            return self._identity(c, name)

    @staticmethod
    def _uids(client, low, high):
        if low > high:
            return []
        integer(low); integer(high)
        rows = checked(client.uid('SEARCH', None, 'UID', f'{low}:{high}'))
        require(rows and all(isinstance(row, bytes) for row in rows), 'Invalid UID search response.')
        data = b' '.join(rows)
        require(len(data) <= 1_100_000 and re.fullmatch(rb'(?:[1-9][0-9]{0,9}(?: +[1-9][0-9]{0,9})*)?', data), 'UID inventory exceeds bounds.')
        result = sorted(set(int(n) for n in data.split()))
        require(len(result) <= MAX_RUN and all(low <= n <= high for n in result), 'UID inventory exceeds bounds.')
        return result

    def uids(self, low, high):
        with self.connection() as c:
            self._identity(c, 'INBOX')
            return self._uids(c, low, high)

    @staticmethod
    def _literal(client, uid, item, section, expected_size=None, offset=0):
        rows = checked(client.uid('FETCH', str(uid), item))
        meta = b' '.join(r[0] if isinstance(r, tuple) else r for r in rows if isinstance(r, (bytes, tuple)))
        ids = re.findall(rb'\bUID ([0-9]+)\b', meta)
        payloads = [r[1] for r in rows if isinstance(r, tuple) and len(r) == 2]
        require(ids and all(n == str(uid).encode() for n in ids) and len(payloads) == 1
                and isinstance(payloads[0], bytes), 'Section response identity mismatch.')
        offset_marker = (rb'<' + str(offset).encode() + rb'>' if section == '' or offset > 0
                         else rb'(?:<0>)?')
        marker = rb'BODY\[' + re.escape(section.encode()) + rb'\]' + offset_marker + rb' \{([0-9]+)\}$'
        matched = [re.search(marker, r[0]) for r in rows if isinstance(r, tuple)]
        require(len(matched) == 1 and matched[0] is not None and int(matched[0][1]) == len(payloads[0]),
                'Unexpected section or literal response.')
        require(expected_size is None or len(payloads[0]) == expected_size, 'Section size changed.')
        return payloads[0]

    @staticmethod
    def _fetch(client, uid):
        integer(uid)
        rows = checked(client.uid('FETCH', str(uid), METADATA))
        if rows == [None] or rows == []:
            return None
        require(len(rows) == 1 and isinstance(rows[0], bytes), 'Unsupported metadata response.')
        try:
            info = parse_metadata(rows[0])
            require(set(info) == {'UID', 'FLAGS', 'INTERNALDATE', 'RFC822.SIZE', 'BODYSTRUCTURE'}, 'Unexpected metadata fields.')
            require(info['UID'] == uid and type(info['UID']) is int, 'Metadata identity mismatch.')
            size = info['RFC822.SIZE']
            if not type(size) is int or not 0 <= size <= MAX_MESSAGE_SIZE:
                raise MessageUnsupported('Message exceeds classification limit.')
            require(isinstance(info['FLAGS'], list) and isinstance(info['INTERNALDATE'], str), 'Unsupported metadata.')
            flags = tuple(info['FLAGS']); persistent(flags)
            texts, attachments, blocked = describe_sections(info['BODYSTRUCTURE'])
            if sum(t['size'] for t in texts) > MAX_TEXT_BYTES:
                raise MessageUnsupported('Text exceeds classification limit.')
            client._text_sections = {t['section'] for t in texts}
            headers = IMAPMailbox._literal(client, uid, HEADER, 'HEADER')
            require(len(headers) <= MAX_HEADER, 'Headers exceed safety limit.')
            sections = []
            if not blocked:
                for text in texts:
                    payload = IMAPMailbox._literal(client, uid,
                        '(UID BODY.PEEK[' + text['section'] + ']<0.' + str(MAX_PART+1) + '>)', text['section'], text['size'])
                    sections.append(TextSection(text['section'], text['content_type'], text['charset'], text['encoding'], payload))
            from .model import digest
            view = MimeView(headers, tuple(sections), tuple(attachments), digest(info['BODYSTRUCTURE']), size, blocked)
            return Message(uid, headers, flags, info['INTERNALDATE'], view)
        except (ContentRefused, UnicodeError):
            raise MessageUnsupported('MIME structure unsupported; keep in Inbox.') from None

    @staticmethod
    def _raw_digest(client, uid, size):
        require(type(size) is int and 0 <= size <= MAX_MESSAGE_SIZE, 'Verification size exceeds bound.')
        result = hashlib.sha256()
        for offset in range(0, size, CHUNK):
            count = min(CHUNK, size - offset)
            item = '(UID BODY.PEEK[]<' + str(offset) + '.' + str(count) + '>)'
            client._raw_permit = (str(uid), item)
            result.update(IMAPMailbox._literal(client, uid, item, '', count, offset))
        return result.hexdigest()

    def fetch(self, folder, uidvalidity, uid):
        with self.connection() as c:
            self._identity(c, folder, uidvalidity)
            message = self._fetch(c, uid)
            return replace(message, source_uidvalidity=uidvalidity) if message else None

    def raw_digest(self, folder, uidvalidity, uid, size):
        # Only called by independently approved move verification, never classification IPC.
        with self.connection() as c:
            self._identity(c, folder, uidvalidity)
            return self._raw_digest(c, uid, size)

    def move(self, source_uv, uid, destination, destination_uv, *, evidence, expires_at, on_prepared):
        require(destination in CATEGORIES, 'Invalid move destination.')
        return self.move_from('INBOX',source_uv,uid,destination,destination_uv,
                              evidence=evidence,expires_at=expires_at,on_prepared=on_prepared)

    def move_from(self, source, source_uv, uid, destination, destination_uv, *, evidence, expires_at, on_prepared):
        integer(uid)
        require(source in ('INBOX', *CATEGORIES) and destination in ('INBOX', *CATEGORIES)
                and source!=destination, 'Invalid corrective folder scope.')
        require((source=='INBOX' and destination in CATEGORIES) or getattr(self,'corrective_enabled',False), 'Corrective adapter disabled.')
        with self.connection() as c:
            self._identity(c, destination, destination_uv)
            # s/w on DESTINATION are required to retain existing Seen/keywords, not to STORE.
            self._rights(c, destination, 'lrisw')
            self._identity(c, source, source_uv)
            self._rights(c, source, 'lrte')
            c._select_permit = source
            self._identity(c, source, source_uv, writable=True)
            current = self._fetch(c, uid)
            require(current is not None and all(current.evidence()[k] == evidence[k]
                                                for k in ('uid', 'sha256', 'size', 'flags', 'internaldate')),
                    'Move source changed during preflight.')
            on_prepared(self._raw_digest(c, uid, evidence['size']))
            require(time.time() < expires_at, 'Move approval expired during preflight.')
            c._move_permit = (str(uid), self._wire(c,destination))
            checked(c.uid('MOVE', str(uid), self._wire(c,destination)))
            _, rows = c.response('COPYUID')
            require(rows and len(rows) == 1 and isinstance(rows[0], bytes), 'Missing MOVE mapping.')
            match = re.fullmatch(rb'([1-9][0-9]{0,9}) ([1-9][0-9]{0,9}) ([1-9][0-9]{0,9})', rows[0])
            require(match is not None and int(match[2]) == uid and int(match[1]) == destination_uv, 'Invalid MOVE mapping.')
            return integer(int(match[1])), integer(int(match[3]))

    def find_exact(self, folder, uv, evidence):
        # Bounded reconciliation; use fresh connections so cumulative wire budgets stay bounded.
        with self.connection() as c:
            self._identity(c, folder, uv)
            upper = self._next_uid(c) - 1
            uids = self._uids(c, 1, upper) if upper else []
        require(len(uids) <= 500, 'Reconciliation scope too large; private owner investigation required.')
        matches = []
        for uid in uids:
            try:
                msg = self.fetch(folder, uv, uid)
            except MessageUnsupported:
                continue
            if msg and msg.evidence()['sha256'] == evidence['sha256']:
                matches.append({'uid': uid, 'uidvalidity': uv, 'persistent_metadata_matches':
                                all(msg.evidence()[k] == evidence[k] for k in ('size', 'flags', 'internaldate'))})
        return matches
