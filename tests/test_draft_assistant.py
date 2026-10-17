import asyncio
from contextlib import contextmanager
import io
import imaplib
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as r
import draft_assistant as d

PARENT = b'Message-ID: <parent@example.com>\r\nReferences: <root@example.com>\r\nSubject: Parent\r\n\r\nUntrusted original.'


class DraftFake:
    def __init__(self):
        self.capabilities = ('IMAP4REV1', 'UIDPLUS')
        self.validity = 321
        self.rows = [b'(\\Drafts) "/" "Drafts"']
        self.calls = []
        self.saved = None
        self.append_count = 0
        self.append_uid = b'321 777'
        self.raise_append = False
        self.rewrite = False
        self.closed = False

    def list(self, *args):
        self.calls.append(('LIST', *args))
        return 'OK', self.rows

    def select(self, mailbox, readonly=False):
        assert readonly
        self.calls.append(('EXAMINE', mailbox))
        return 'OK', [b'0']

    def response(self, name):
        return name, [str(self.validity).encode() if name == 'UIDVALIDITY' else self.append_uid]

    def permit_exact_append(self, folder, raw):
        self.permit = (folder, raw)

    def append(self, mailbox, flags, date, raw):
        assert (mailbox, flags, date, raw) == ('"Drafts"', '(\\Draft)', None, self.permit[1])
        self.append_count += 1
        self.calls.append(('APPEND', mailbox, flags))
        self.saved = raw
        if self.raise_append:
            raise TimeoutError('private server data')
        return 'OK', []

    def uid(self, *args):
        assert args == ('FETCH', '777', '(UID BODY.PEEK[])')
        self.calls.append(('UID', *args))
        raw = self.saved + b'x' if self.rewrite else self.saved
        return 'OK', [(b'1 (UID 777 BODY[] {' + str(len(raw)).encode() + b'}', raw), b')']

    def login(self, *args):
        return 'OK', []

    def shutdown(self):
        self.closed = True


class DraftFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.config = d.Config(r.HOST, r.ACCOUNT, 'Drafts', self.directory)
        self.service = d.DraftService(r, self.config)
        self.fake = DraftFake()

        @contextmanager
        def connection():
            yield self.fake
        self.connection = connection
        for p in (patch.object(r, 'fetch_message', return_value=PARENT),
                  patch.object(r, 'connection', connection),
                  patch.object(self.service, 'writer', connection)):
            p.start()
            self.addCleanup(p.stop)

    def prepare(self, **changes):
        args = dict(mailbox='INBOX', uid=20, uidvalidity=123, to=['recipient@example.com'],
                    subject='Re: Parent', body='Reviewed reply.\n', cc=['copy@example.com'], bcc=['blind@example.com'])
        args.update(changes)
        return self.service.prepare(**args)

    def approved(self):
        result = self.prepare()
        self.service.store.approve(result['draft_id'], result['approval_fingerprint'])
        return result


class DraftTests(DraftFixture, unittest.TestCase):
    def test_preparation_never_appends_and_preserves_threading(self):
        result = self.prepare()
        self.assertEqual(self.fake.append_count, 0)
        self.assertEqual(result['state'], 'pending_operator_review')
        p = result['preview']
        self.assertEqual(p['In-Reply-To'], '<parent@example.com>')
        self.assertEqual(p['References'], '<root@example.com> <parent@example.com>')
        self.assertEqual(p['Bcc'], 'blind@example.com')
        self.assertEqual(p['body'], 'Reviewed reply.\r\n')
        self.assertEqual((self.directory/'approvals.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_unapproved_model_call_cannot_write(self):
        result = self.prepare()
        with self.assertRaises(d.DraftError):
            self.service.save(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_exact_save_and_replay_is_one_append(self):
        result = self.approved()
        first = self.service.save(result['draft_id'])
        self.assertEqual(first['status'], 'saved')
        self.assertEqual(first['sha256'], result['mime_sha256'])
        self.assertEqual(self.service.save(result['draft_id']), first)
        self.assertEqual(self.fake.append_count, 1)
        self.assertTrue(all(c[0] in ('LIST', 'EXAMINE', 'APPEND', 'UID') for c in self.fake.calls))

    def test_edit_requires_new_review(self):
        first = self.approved()
        second = self.prepare(body='Changed reply')
        self.assertNotEqual(first['approval_fingerprint'], second['approval_fingerprint'])
        with self.assertRaises(d.DraftError):
            self.service.save(second['draft_id'])

    def test_wrong_fingerprint_not_approved(self):
        result = self.prepare()
        with self.assertRaises(d.DraftError):
            self.service.store.approve(result['draft_id'], '0'*64)

    def test_expiry_prevents_approval_or_write(self):
        result = self.approved()
        with patch.object(d.time, 'time', return_value=time.time()+d.TTL+1), self.assertRaises(d.DraftError):
            self.service.save(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_review_expiry_race_and_expiry_tampering(self):
        result = self.prepare()
        with patch.object(d.time, 'time', return_value=time.time()+d.TTL+1), self.assertRaises(d.DraftError):
            self.service.store.approve(result['draft_id'], result['approval_fingerprint'])
        with self.service.store.db() as db:
            db.execute('UPDATE drafts SET expires=expires+100 WHERE id=?', (result['draft_id'],))
            db.commit()
        with self.assertRaises(d.DraftError):
            self.service.store.get(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_wrong_saved_uid_or_append_identity_is_uncertain(self):
        result = self.approved()
        self.fake.append_uid = b'999 777'
        saved = self.service.save(result['draft_id'])
        self.assertEqual(saved['status'], 'uncertain')
        self.assertEqual(self.service.save(result['draft_id']), saved)
        self.assertEqual(self.fake.append_count, 1)

    def test_safe_wrapper_redacts_unexpected_state_errors(self):
        with patch.object(d.DraftService, 'save', side_effect=RuntimeError('synthetic secret content')):
            with patch.dict('os.environ', {'INBOXTETHER_DRAFT_ASSISTANT': '1',
                       'INBOXTETHER_DRAFTS_FOLDER': 'Drafts',
                       'INBOXTETHER_DRAFT_STATE_DIR': str(self.directory)}):
                with self.assertRaises(r.MailError) as raised:
                    r.save_approved_draft('0'*64)
        self.assertNotIn('synthetic secret content', str(raised.exception))

    def test_changed_source_or_target_identity_prevents_write(self):
        result = self.approved()
        with patch.object(r, 'fetch_message', return_value=PARENT+b'changed'), self.assertRaises(d.DraftError):
            self.service.save(result['draft_id'])
        self.fake.validity = 999
        with self.assertRaises(d.DraftError):
            self.service.save(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_changed_configuration_invalidates_receipt(self):
        result = self.approved()
        other = d.Store(d.Config(r.HOST, 'other@example.com', 'Drafts', self.directory))
        with self.assertRaises(d.DraftError):
            other.get(result['draft_id'])

    def test_tampered_bytes_cannot_match_approval(self):
        result = self.approved()
        with self.service.store.db() as db:
            db.execute('UPDATE drafts SET raw=? WHERE id=?', (b'tampered', result['draft_id']))
            db.commit()
        with self.assertRaises(d.DraftError):
            self.service.save(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_ambiguous_append_and_server_rewrite_never_retry(self):
        for failure in ('timeout', 'rewrite', 'appenduid'):
            result = self.approved()
            self.fake.raise_append = failure == 'timeout'
            self.fake.rewrite = failure == 'rewrite'
            self.fake.append_uid = None if failure == 'appenduid' else b'321 777'
            before = self.fake.append_count
            saved = self.service.save(result['draft_id'])
            self.assertEqual(saved['status'], 'uncertain')
            self.assertNotIn('private server data', str(saved))
            self.assertEqual(self.service.save(result['draft_id']), saved)
            self.assertEqual(self.fake.append_count, before+1)

    def test_crash_after_claim_blocks_replay(self):
        result = self.approved()
        self.service.store.claim(result['draft_id'], result['approval_fingerprint'])
        self.assertEqual(self.service.save(result['draft_id'])['status'], 'uncertain')
        self.assertEqual(self.fake.append_count, 0)

    def test_atomic_approval_claim_race(self):
        result = self.approved()
        outcomes = []
        barrier = threading.Barrier(2)
        def claim():
            barrier.wait()
            try:
                d.Store(self.config).claim(result['draft_id'], result['approval_fingerprint'])
                outcomes.append('claimed')
            except d.DraftError:
                outcomes.append('denied')
        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertCountEqual(outcomes, ['claimed', 'denied'])

    def test_bad_recipients_headers_and_body_before_network(self):
        for changes in ({'to': []}, {'to': ['Name <a@example.com>']}, {'to': ['a@example.com\r\nBcc: b@example.com']},
                        {'to': ['a@' + '-example.com']}, {'to': ['a@example.com'], 'cc': ['A@example.com']},
                        {'subject': 'x\nBcc: bad'}, {'subject': '\u202eevil'}, {'body': 'a\x00b'},
                        {'body': ''}, {'body': 'x'*20001}, {'cc': ''}, {'bcc': 0}):
            with self.subTest(changes=changes), self.assertRaises(d.DraftError):
                self.prepare(**changes)
        r.fetch_message.assert_not_called()

    def test_parent_threading_validation(self):
        for raw in (b'\r\nmissing', b'Message-ID: bad\r\n\r\n',
                    b'Message-ID: <a@example.com>\r\nMessage-ID: <b@example.com>\r\n\r\n',
                    b'Message-ID: <a@example.com>\r\nReferences: bad\r\n\r\n'):
            with patch.object(r, 'fetch_message', return_value=raw), self.assertRaises(d.DraftError):
                self.prepare()

    def test_missing_special_use_or_uidplus_denies_preparation(self):
        for rows in ([b'() "/" "Drafts"'], [b'(\\Drafts) "/" "Other"'], [],
                     [b'(\\Drafts \\Noselect) "/" "Drafts"']):
            self.fake.rows = rows
            with self.assertRaises(d.DraftError):
                self.prepare()
        self.fake.rows = [b'(\\Drafts) "/" "Drafts"']
        self.fake.capabilities = ()
        with self.assertRaises(d.DraftError):
            self.prepare()

    def test_state_permissions_and_symlink_rejected(self):
        result = self.prepare()
        self.directory.chmod(0o755)
        with self.assertRaises(d.DraftError):
            self.service.store.get(result['draft_id'])
        self.directory.chmod(0o700)
        dbpath = self.directory/'approvals.sqlite3'
        dbpath.chmod(0o644)
        with self.assertRaises(d.DraftError):
            self.service.store.get(result['draft_id'])
        dbpath.chmod(0o600)
        dbpath.rename(self.directory/'original.sqlite3')
        dbpath.symlink_to(self.directory/'original.sqlite3')
        with self.assertRaises(OSError):
            self.service.store.get(result['draft_id'])

    def test_staging_bound(self):
        with patch.object(d, 'MAX_PENDING', 1):
            self.prepare()
            with self.assertRaises(d.DraftError):
                self.prepare()

    def test_operator_terminal_only_and_exact_confirmation(self):
        result = self.prepare()
        with self.assertRaises(d.DraftError):
            d.approve_interactively(self.service, result['draft_id'], io.StringIO('yes\n'), io.StringIO())
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        with self.assertRaises(d.DraftError):
            d.approve_interactively(self.service, result['draft_id'], Terminal('yes\n'), Terminal())
        output = Terminal()
        d.approve_interactively(self.service, result['draft_id'],
                                Terminal('APPROVE '+result['approval_fingerprint']+'\n'), output)
        self.assertIn('blind@example.com', output.getvalue())
        self.assertIn('Reviewed reply.', output.getvalue())
        self.assertEqual(self.service.store.get(result['draft_id'])['state'], 'approved')
        self.assertEqual(self.fake.append_count, 0)

    def test_writer_closes_and_keeps_credential_errors_private(self):
        # Exercise real writer lifecycle with a fake wire client, not a mailbox.
        with patch.object(r, 'DraftAppendIMAP', return_value=self.fake), patch.object(r, 'password', return_value='synthetic'):
            with d.DraftService(r, self.config).writer():
                self.assertTrue(r.LOCK.locked())
        self.assertTrue(self.fake.closed)
        self.assertFalse(r.LOCK.locked())


class DraftGuardTests(unittest.TestCase):
    def test_append_adapter_never_allows_other_mutations(self):
        client = object.__new__(r.DraftAppendIMAP)
        for command in ('STORE', 'MOVE', 'COPY', 'DELETE', 'SELECT', 'EXPUNGE', 'CLOSE', 'APPEND'):
            with self.subTest(command=command), self.assertRaises(r.MailError):
                client._command(command, '1')
        for command in ('STORE', 'MOVE', 'COPY', 'EXPUNGE'):
            with self.assertRaises(r.MailError):
                client._command('UID', command, '1')

    def test_one_use_exact_folder_flags_and_literal(self):
        for folder, flags, literal in [('"Other"', '(\\Draft)', b'exact'),
                                       ('"Drafts"', '(\\Seen)', b'exact'),
                                       ('"Drafts"', '(\\Draft)', b'changed')]:
            client = object.__new__(r.DraftAppendIMAP)
            client.permit_exact_append('Drafts', b'exact')
            client.literal = literal
            with patch.object(imaplib.IMAP4, '_command') as wire, self.assertRaises(r.MailError):
                client._command('APPEND', folder, flags, None)
            wire.assert_not_called()
        client = object.__new__(r.DraftAppendIMAP)
        client.permit_exact_append('Drafts', b'exact')
        client.literal = b'exact'
        with patch.object(imaplib.IMAP4, '_command', return_value=b'tag') as wire:
            self.assertEqual(client._command('APPEND', '"Drafts"', '(\\Draft)', None), b'tag')
            with self.assertRaises(r.MailError):
                client._command('APPEND', '"Drafts"', '(\\Draft)', None)
            wire.assert_called_once()

    def test_default_disabled_and_invalid_optin(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(d.Config.load())
            with self.assertRaises(d.DraftError):
                d.DraftService(r)
        with patch.dict('os.environ', {'INBOXTETHER_DRAFT_ASSISTANT': 'yes'}), self.assertRaises(d.DraftError):
            d.Config.load()

    def test_optin_configuration_folder_is_fixed_and_validated(self):
        env = {'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_DRAFT_STATE_DIR': '/var/lib/inboxtether-mcp/drafts'}
        for folder in ('INBOX', 'Trash', '*', 'Drafts\r\nDELETE', '"Drafts"', ''):
            with patch.dict('os.environ', {**env, 'INBOXTETHER_DRAFTS_FOLDER': folder}), self.assertRaises(d.DraftError):
                d.Config.load()

    def test_real_mcp_optin_has_no_remote_approval_or_unapproved_save(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                Path(directory).chmod(0o700)
                params = StdioServerParameters(command=sys.executable,
                    args=[str(Path(r.__file__).resolve())], env={
                        'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_DRAFTS_FOLDER': 'Drafts',
                        'INBOXTETHER_DRAFT_STATE_DIR': directory})
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        names = {t.name for t in (await session.list_tools()).tools}
                        self.assertEqual(len(names), 7)
                        self.assertFalse(any('approve' == n or n.startswith('approve_') for n in names))
                        result = await session.call_tool('save_approved_draft', {'draft_id': '0'*64})
                        self.assertTrue(result.isError)
                        result = await session.call_tool('prepare_reply_draft', {
                            'mailbox': 'INBOX', 'uid': 1, 'uidvalidity': 123, 'to': [],
                            'subject': 'Synthetic', 'body': 'Synthetic'})
                        self.assertTrue(result.isError)
        asyncio.run(run())

    def test_optin_schema_and_default_five_reader_tools(self):
        async def run():
            with patch.dict('os.environ', {'INBOXTETHER_DRAFT_ASSISTANT': '0'}):
                self.assertEqual(len(await r.create_server().list_tools()), 5)
            with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {
                    'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_DRAFTS_FOLDER': 'Drafts',
                    'INBOXTETHER_DRAFT_STATE_DIR': directory}):
                tools = {t.name: t for t in await r.create_server().list_tools()}
                self.assertEqual(len(tools), 7)
                self.assertEqual(set(tools['save_approved_draft'].inputSchema['properties']), {'draft_id'})
                self.assertFalse(tools['save_approved_draft'].annotations.readOnlyHint)
                self.assertFalse(tools['prepare_reply_draft'].annotations.readOnlyHint)
                self.assertTrue(tools['read_message'].annotations.readOnlyHint)
        asyncio.run(run())


class DraftWireTests(DraftFixture, unittest.TestCase):
    def test_real_append_literal_and_verification_no_old_mail_mutation(self):
        result = self.approved()
        local, peer = socket.socketpair()
        transcript, literals, failures = [], [], []
        def serve():
            try:
                with peer, peer.makefile('rwb', buffering=0) as wire:
                    wire.write(b'* OK synthetic\r\n')
                    saved = None
                    while line := wire.readline():
                        tag, command = line.rstrip(b'\r\n').split(b' ', 1)
                        transcript.append(command)
                        if command == b'CAPABILITY':
                            wire.write(b'* CAPABILITY IMAP4rev1 UIDPLUS\r\n')
                        elif command.startswith(b'LOGIN '):
                            pass
                        elif command == b'LIST "" "Drafts"':
                            wire.write(b'* LIST (\\Drafts) "/" "Drafts"\r\n')
                        elif command == b'EXAMINE "Drafts"':
                            wire.write(b'* 0 EXISTS\r\n* OK [UIDVALIDITY 321] valid\r\n')
                        elif command.startswith(b'APPEND "Drafts" (\\Draft) {'):
                            size = int(command.rsplit(b'{', 1)[1][:-1])
                            wire.write(b'+ ready\r\n')
                            saved = wire.read(size)
                            self.assertEqual(wire.read(2), b'\r\n')
                            literals.append(saved)
                            wire.write(tag+b' OK [APPENDUID 321 777] appended\r\n')
                            continue
                        elif command == b'UID FETCH 777 (UID BODY.PEEK[])':
                            wire.write(b'* 1 FETCH (UID 777 BODY[] {'+str(len(saved)).encode()+b'}\r\n'+saved+b')\r\n')
                        else:
                            raise AssertionError('Unexpected wire command')
                        wire.write(tag+b' OK completed\r\n')
            except BaseException as error:
                failures.append(error)
        peer.settimeout(3)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with patch.object(r.DraftAppendIMAP, '_create_socket', return_value=local), patch.object(r, 'password', return_value='fixture-only'):
                saved = d.DraftService(r, self.config).save(result['draft_id'])
            self.assertEqual(saved['status'], 'saved')
        finally:
            local.close()
            thread.join(timeout=4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(literals), 1)
        self.assertEqual(d.digest(literals[0]), result['mime_sha256'])
        self.assertFalse(any(c.startswith((b'STORE', b'UID STORE', b'MOVE', b'COPY', b'DELETE', b'CLOSE', b'EXPUNGE', b'SELECT')) for c in transcript))
