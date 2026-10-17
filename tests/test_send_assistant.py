"""Synthetic messages/mock SMTP only. Never connects to a mailbox or SMTP host."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

import send_assistant as s
import send_client as c
import server as reader
from draft_assistant import DraftError, digest


class Terminal(io.StringIO):
    def isatty(self):
        return True


class FakeSMTP:
    def __init__(self, failure=None):
        self.failure, self.calls, self.raw = failure, [], None
        self.envelope = []

    def step(self, name, result=(250, b'synthetic')):
        self.calls.append(name)
        if self.failure == name:
            raise OSError('SYNTHETIC PRIVATE SERVER REPLY')
        return result

    def ehlo(self):
        return self.step('ehlo')

    def has_extn(self, name):
        self.calls.append('extension-' + name)
        return self.failure != 'no-starttls'

    def starttls(self, context):
        self.context = context
        return self.step('starttls', (220, b'synthetic'))

    def login(self, username, secret):
        assert secret == 'synthetic-only-not-a-credential'
        return self.step('login', (235, b'synthetic'))

    def mail(self, identity):
        self.identity = identity
        return self.step('mail', (550 if self.failure == 'sender-refused' else 250, b'synthetic'))

    def rcpt(self, recipient):
        self.envelope.append(recipient)
        refused = self.failure == 'recipient-refused' and len(self.envelope) == 2
        return self.step('rcpt', (550 if refused else 250, b'synthetic'))

    def data(self, raw):
        self.raw = raw
        if self.failure == 'data-rejected':
            self.calls.append('data')
            raise s.smtplib.SMTPDataError(554, b'SYNTHETIC PRIVATE SERVER REPLY')
        code = 451 if self.failure == 'data-negative' else 299 if self.failure == 'data-unexpected' else 250
        return self.step('data', (code, b'synthetic'))

    def close(self):
        return self.step('close')


class SendTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.directory.chmod(0o700)
        self.config = s.SenderConfig('sender@example.com', 'smtp.example.com', 465, 'implicit',
                                    'sender@example.com', self.directory / 'synthetic.secret',
                                    self.directory, self.directory / 'sender.sock', os.geteuid() + 1)
        self.config.password_file.write_text('synthetic-only-not-a-credential')
        self.config.password_file.chmod(0o600)
        self.service = s.SendService(self.config)
        self.arguments = {'to': ['to@example.com'], 'cc': ['cc@example.com'], 'bcc': ['bcc@example.com'],
                          'subject': 'Synthetic reply', 'body': 'Synthetic message only.\nSecond line.'}
        self.fake = FakeSMTP()
        ssl_patch = patch.object(s.smtplib, 'SMTP_SSL', return_value=self.fake)
        plain_patch = patch.object(s.smtplib, 'SMTP', return_value=self.fake)
        self.ssl_factory, self.plain_factory = ssl_patch.start(), plain_patch.start()
        self.addCleanup(ssl_patch.stop)
        self.addCleanup(plain_patch.stop)

    def prepare(self, **updates):
        return self.service.prepare({**self.arguments, **updates})

    def send(self, item):
        return self.service.approve_and_send(item['send_id'], item['fingerprint'])

    def test_prepare_status_and_reject_never_connect(self):
        item = self.prepare()
        self.assertEqual(self.service.status(item['send_id'])['status'], 'pending')
        self.service.store.reject(item['send_id'])
        self.assertEqual(self.service.status(item['send_id'])['status'], 'rejected')
        with self.assertRaises(c.SendError): self.send(item)
        self.ssl_factory.assert_not_called()
        self.plain_factory.assert_not_called()

    def test_frozen_bytes_all_recipients_and_no_bcc_disclosure(self):
        item = self.prepare()
        raw = self.service.store.get(item['send_id'])['raw']
        result = self.send(item)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['mime_sha256'], digest(raw))
        self.assertEqual(self.fake.raw, raw)
        self.assertEqual(self.fake.envelope, ['to@example.com', 'cc@example.com', 'bcc@example.com'])
        self.assertNotIn(b'Bcc:', raw)
        self.assertEqual(item['manifest']['recipients']['bcc'], ['bcc@example.com'])
        self.assertEqual(result['sent_copy'], 'not-written')

    def test_tls_certificate_hostname_validation_and_floor(self):
        self.send(self.prepare())
        context = self.ssl_factory.call_args.kwargs['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_starttls_auth_order_and_no_downgrade(self):
        self.service = s.SendService(replace(self.config, tls='starttls', smtp_port=587))
        self.assertEqual(self.send(self.prepare())['status'], 'accepted')
        self.assertEqual(self.fake.calls[:5], ['ehlo', 'extension-starttls', 'starttls', 'ehlo', 'login'])
        self.assertTrue(self.fake.context.check_hostname)
        self.ssl_factory.assert_not_called()
        for failure in ('no-starttls', 'starttls'):
            self.fake = FakeSMTP(failure); self.plain_factory.return_value = self.fake
            self.assertEqual(self.send(self.prepare())['status'], 'failed')
            self.assertNotIn('login', self.fake.calls)
            self.assertNotIn('data', self.fake.calls)

    def test_terminal_requires_exact_fingerprint_and_real_tty(self):
        item = self.prepare()
        for incoming in (Terminal('yes\n'), io.StringIO('SEND ' + item['fingerprint'] + '\n')):
            with self.assertRaises(c.SendError):
                s.approve_interactively(self.service, item['send_id'], incoming=incoming, outgoing=Terminal())
        self.ssl_factory.assert_not_called()
        output = Terminal()
        result = s.approve_interactively(self.service, item['send_id'],
                                        incoming=Terminal('SEND ' + item['fingerprint'] + '\n'), outgoing=output)
        self.assertEqual(result['status'], 'accepted')
        for expected in ('to@example.com', 'cc@example.com', 'bcc@example.com', 'Synthetic message', 'smtp.example.com'):
            self.assertIn(expected, output.getvalue())

    def test_wrong_fingerprint_and_expired_approval_block_network(self):
        item = self.prepare()
        with self.assertRaises(c.SendError): self.service.approve_and_send(item['send_id'], '0' * 64)
        with patch.object(s.time, 'time', return_value=time.time() + s.TTL + 1):
            self.assertEqual(self.service.status(item['send_id'])['status'], 'expired')
            with self.assertRaises(c.SendError): self.send(item)
            with self.assertRaises(c.SendError):
                s.approve_interactively(self.service, item['send_id'], incoming=Terminal(), outgoing=Terminal())
        self.ssl_factory.assert_not_called()

    def test_expiry_during_authentication_or_recipient_checks(self):
        for stage in ('login', 'rcpt'):
            with self.subTest(stage=stage):
                self.fake = FakeSMTP(); self.ssl_factory.return_value = self.fake
                item = self.prepare(); original = getattr(self.fake, stage)
                with patch.object(s.time, 'time', return_value=time.time()) as clock:
                    def slow(*args):
                        value = original(*args)
                        clock.return_value = item['manifest']['expires_at'] + 1
                        return value
                    with patch.object(self.fake, stage, side_effect=slow):
                        self.assertEqual(self.send(item)['status'], 'failed')
                self.assertNotIn('data', self.fake.calls)

    def test_expiry_during_interactive_review_is_rechecked(self):
        item = self.prepare()
        with patch.object(s.time, 'time', return_value=time.time()) as clock:
            class SlowTerminal(Terminal):
                def readline(inner):
                    clock.return_value = item['manifest']['expires_at'] + 1
                    return 'SEND ' + item['fingerprint'] + '\n'
            with self.assertRaises(c.SendError):
                s.approve_interactively(self.service, item['send_id'], incoming=SlowTerminal(), outgoing=Terminal())
        self.ssl_factory.assert_not_called()

    def test_replay_and_parallel_claims(self):
        item = self.prepare()
        def claim(_):
            try:
                return bool(self.service.store.claim(item['send_id'], item['fingerprint']))
            except c.SendError:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(claim, range(6))), 1)
        self.assertEqual(self.service.status(item['send_id'])['status'], 'uncertain')
        with self.assertRaises(c.SendError): self.send(item)
        self.ssl_factory.assert_not_called()
        item = self.prepare(); self.send(item)
        with self.assertRaises(c.SendError): self.send(item)
        self.assertEqual(self.fake.calls.count('data'), 1)

    def test_crash_receipt_survives_process_restart_and_expiry(self):
        item = self.prepare(); self.service.store.claim(item['send_id'], item['fingerprint'])
        restarted = s.SendService(self.config)
        with patch.object(s.time, 'time', return_value=time.time() + s.TTL + 1):
            restarted.prepare(self.arguments)
            self.assertEqual(restarted.status(item['send_id'])['status'], 'uncertain')
            with self.assertRaises(c.SendError): restarted.approve_and_send(item['send_id'], item['fingerprint'])

    def test_uncertain_data_never_retries_or_leaks_reply(self):
        self.fake.failure = 'data'
        item = self.prepare(); result = self.send(item)
        self.assertEqual(result['status'], 'uncertain')
        self.assertFalse(result['retry_allowed'])
        with self.assertRaises(c.SendError): self.send(item)
        self.assertEqual(self.fake.calls.count('data'), 1)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_receipt_disk_failure_keeps_durable_attempt(self):
        item = self.prepare()
        with patch.object(self.service.store, 'finish', side_effect=OSError('synthetic storage failure')):
            self.assertEqual(self.send(item)['status'], 'uncertain')
        self.assertEqual(s.SendService(self.config).status(item['send_id'])['status'], 'uncertain')
        with self.assertRaises(c.SendError): self.send(item)
        self.assertEqual(self.fake.calls.count('data'), 1)

    def test_pre_data_failures_and_partial_rcpt_never_submit(self):
        for failure in ('ehlo', 'login', 'mail', 'sender-refused', 'rcpt', 'recipient-refused'):
            with self.subTest(failure=failure):
                self.fake = FakeSMTP(failure); self.ssl_factory.return_value = self.fake
                item = self.prepare()
                self.assertEqual(self.send(item)['status'], 'failed')
                self.assertNotIn('data', self.fake.calls)
                with self.assertRaises(c.SendError): self.send(item)
        for failure in (ssl.SSLCertVerificationError('synthetic'), OSError('synthetic')):
            with patch.object(s.smtplib, 'SMTP_SSL', side_effect=failure):
                self.assertEqual(self.send(self.prepare())['status'], 'failed')

    def test_negative_or_unknown_data_replies(self):
        for failure, expected in [('data-rejected', 'failed'), ('data-negative', 'failed'), ('data-unexpected', 'uncertain')]:
            with self.subTest(failure=failure):
                self.fake = FakeSMTP(failure); self.ssl_factory.return_value = self.fake
                item = self.prepare(); self.assertEqual(self.send(item)['status'], expected)
                with self.assertRaises(c.SendError): self.send(item)

    def test_disconnect_on_close_does_not_erase_known_acceptance(self):
        self.fake.failure = 'close'
        self.assertEqual(self.send(self.prepare())['status'], 'accepted')

    def test_identity_destination_and_authentication_scope_bound(self):
        item = self.prepare()
        for cfg in (replace(self.config, identity='other@example.com'), replace(self.config, smtp_host='other.example.com'),
                    replace(self.config, smtp_port=587), replace(self.config, smtp_username='other@example.com'),
                    replace(self.config, tls='starttls'), replace(self.config, client_uid=98765)):
            with self.subTest(cfg=cfg.scope()), self.assertRaises(c.SendError):
                s.SendService(cfg).approve_and_send(item['send_id'], item['fingerprint'])
        self.ssl_factory.assert_not_called()

    def test_tampered_mime_manifest_and_expiry(self):
        for column, value in [('raw', b'altered'), ('manifest', b'{}'), ('fingerprint', '0' * 64), ('expires', 0)]:
            item = self.prepare()
            with self.service.store.db() as db:
                db.execute('UPDATE sends SET ' + column + '=? WHERE id=?', (value, item['send_id'])); db.commit()
            with self.assertRaises((c.SendError, KeyError)): self.send(item)
        self.ssl_factory.assert_not_called()

    def test_recipient_and_content_injection_rejected(self):
        cases = [{'to': []}, {'to': ['bad\r\nBcc: bad@example.com']}, {'to': ['same@example.com'], 'cc': ['same@example.com']},
                 {'subject': 'bad\r\nX: yes'}, {'body': 'bad\x1b[31m'}, {'body': 'bad\u202e'}, {'subject': ''},
                 {'from': 'other@example.com'}, {'approved': True}, {'to': ['a@example.com'] * 21}]
        for case in cases:
            with self.subTest(keys=list(case)), self.assertRaises((c.SendError, DraftError)): self.prepare(**case)
        self.ssl_factory.assert_not_called()

    def test_reply_headers_preserved_and_invalid_parent_refused(self):
        parent = b'Message-ID: <parent@example.com>\r\nReferences: <older@example.com>\r\n\r\n'
        reply = {'source': {'mailbox': 'INBOX', 'uid': 12, 'uidvalidity': 34, 'sha256': digest(parent)},
                 'headers_base64': base64.b64encode(parent).decode(), 'context': {'body': 'Synthetic parent'}}
        item = self.prepare(reply=reply)
        self.assertEqual(item['manifest']['preview']['In-Reply-To'], '<parent@example.com>')
        self.assertEqual(item['manifest']['preview']['References'], '<older@example.com> <parent@example.com>')
        self.send(item)
        self.assertIn(b'In-Reply-To: <parent@example.com>', self.fake.raw)
        reply['headers_base64'] = base64.b64encode(b'Message-ID: invalid\r\n\r\n').decode()
        with self.assertRaises(DraftError): self.prepare(reply=reply)

    def test_attachment_bytes_bound_and_private_review_export_required(self):
        data = b'Synthetic attachment only.\n'
        files = [{'filename': 'example.txt', 'content_type': 'text/plain', 'data_base64': base64.b64encode(data).decode()}]
        item = self.prepare(attachments=files)
        self.assertEqual(item['manifest']['preview']['attachments'][0]['sha256'], digest(data))
        with self.assertRaises(c.SendError):
            s.approve_interactively(self.service, item['send_id'], incoming=Terminal(), outgoing=Terminal())
        export = self.directory / 'review'; export.mkdir(mode=0o700)
        s.approve_interactively(self.service, item['send_id'], review_dir=export,
                               incoming=Terminal('SEND ' + item['fingerprint'] + '\n'), outgoing=Terminal())
        self.assertEqual((export / 'attachment-1.bin').read_bytes(), data)
        self.assertEqual((export / 'message.eml').read_bytes(), self.fake.raw)
        self.assertEqual((export / 'review.json').stat().st_mode & 0o777, 0o600)

    def test_attachment_types_paths_signatures_encoding_and_limits(self):
        valid = {'filename': 'example.txt', 'content_type': 'text/plain', 'data_base64': base64.b64encode(b'synthetic').decode()}
        cases = [{**valid, 'filename': '../example.txt'}, {**valid, 'filename': '.hidden.txt'},
                 {**valid, 'filename': 'bad\n.txt'}, {**valid, 'filename': 'example.exe'}, {**valid, 'content_type': 'text/html'},
                 {**valid, 'data_base64': '%%%bad'}, {**valid, 'data_base64': base64.b64encode(b'x' * (s.MAX_ATTACHMENT + 1)).decode()},
                 {**valid, 'filename': 'example.pdf', 'content_type': 'application/pdf'},
                 {**valid, 'path': '/synthetic'}, {**valid, 'url': 'https://example.com/file'}]
        for case in cases:
            with self.assertRaises((c.SendError, DraftError)): self.prepare(attachments=[case])
        with self.assertRaises(c.SendError): self.prepare(attachments=[valid] * 6)
        with self.assertRaises(c.SendError): self.prepare(attachments=[valid, valid])
        with self.assertRaises(c.SendError):
            self.prepare(attachments=[{**valid, 'filename': f'{n}.txt', 'data_base64': base64.b64encode(b'x' * s.MAX_ATTACHMENT).decode()} for n in range(3)])

    def test_review_export_never_follows_links_or_overwrites(self):
        item = self.service.store.get(self.prepare()['send_id'])
        export = self.directory / 'export'; export.mkdir(mode=0o700)
        target = self.directory / 'unchanged'; target.write_text('synthetic')
        (export / 'message.eml').symlink_to(target)
        with self.assertRaises(OSError): s.export_review(item, export)
        self.assertEqual(target.read_text(), 'synthetic')

    def test_state_and_credential_permissions_and_symlinks(self):
        self.directory.chmod(0o750)
        with self.assertRaises(c.SendError): self.prepare()
        self.directory.chmod(0o700)
        target = self.directory / 'target'; target.write_text('synthetic')
        (self.directory / 'sends.sqlite3').symlink_to(target)
        with self.assertRaises(OSError): self.prepare()
        (self.directory / 'sends.sqlite3').unlink()
        self.config.password_file.chmod(0o644)
        self.assertEqual(self.send(self.prepare())['status'], 'failed')
        self.config.password_file.unlink(); self.config.password_file.symlink_to(target)
        self.assertEqual(self.send(self.prepare())['status'], 'failed')
        self.assertNotIn('data', self.fake.calls)

    def test_attempted_receipts_are_never_purged_to_make_room(self):
        with patch.object(s, 'MAX_RECORDS', 1):
            item = self.prepare(); self.send(item)
            with patch.object(s.time, 'time', return_value=time.time() + s.TTL + 1):
                with self.assertRaises(c.SendError): self.prepare()
                self.assertEqual(self.service.status(item['send_id'])['status'], 'accepted')

    def test_pending_limit_and_expired_pending_cleanup(self):
        for _ in range(32):
            self.prepare()
        with self.assertRaises(c.SendError): self.prepare()
        with patch.object(s.time, 'time', return_value=time.time() + s.TTL + 1):
            self.assertEqual(self.prepare()['status'], 'pending_independent_approval')

    def test_credentials_are_not_read_by_preparation_or_status(self):
        with patch.object(s, 'private_file', side_effect=AssertionError('No credential access during preparation')):
            item = self.prepare()
            self.assertEqual(self.service.status(item['send_id'])['status'], 'pending')
        self.assertNotIn(str(self.config.password_file), json.dumps(item))

    def test_credential_failure_consumes_claim_without_network(self):
        item = self.prepare()
        with patch.object(s, 'private_file', side_effect=OSError('synthetic')):
            self.assertEqual(self.send(item)['status'], 'failed')
        self.ssl_factory.assert_not_called()
        with self.assertRaises(c.SendError): self.send(item)

    def test_terminal_control_characters_stay_escaped_in_reply_context(self):
        parent = b'Message-ID: <parent@example.com>\r\n\r\n'
        reply = {'source': {'mailbox': 'INBOX', 'uid': 12, 'uidvalidity': 34, 'sha256': digest(parent)},
                 'headers_base64': base64.b64encode(parent).decode(), 'context': {'body': 'untrusted \x1b[31m'}}
        item = self.prepare(reply=reply)
        out = Terminal()
        with self.assertRaises(c.SendError):
            s.approve_interactively(self.service, item['send_id'], incoming=Terminal('cancel\n'), outgoing=out)
        self.assertNotIn('\x1b', out.getvalue())
        self.assertIn('\\u001b', out.getvalue())

    def test_ipc_never_exposes_approval_sending_or_configuration(self):
        for name in ('approve', 'send', 'approve-send', 'save', 'configure', 'export', 'reject'):
            with self.assertRaises(c.SendError): s.dispatch(self.service, name, {'approved': True})
        with self.assertRaises(c.SendError): s.dispatch(self.service, 'status', {'send_id': '0' * 64, 'approved': True})
        self.ssl_factory.assert_not_called()

    def test_private_configuration_opt_in_no_basic_mode(self):
        obj = {k: str(v) if isinstance(v, Path) else v for k, v in vars(self.config).items()}
        path = self.directory / 'sender.json'
        for changes in ({}, {'enabled': False, 'mode': 'secure'}, {'enabled': True, 'mode': 'basic'}):
            path.write_text(json.dumps({**obj, **changes})); path.chmod(0o600)
            with self.assertRaises(c.SendError): s.SenderConfig.load(path)
        path.write_text(json.dumps({**obj, 'enabled': True, 'mode': 'secure'}))
        self.assertEqual(s.SenderConfig.load(path), self.config)
        for cfg in (replace(self.config, tls='none'), replace(self.config, smtp_port=0), replace(self.config, client_uid=os.geteuid())):
            with self.assertRaises(c.SendError): cfg.validate()


class SendProtocolTests(unittest.TestCase):
    def test_frame_roundtrip(self):
        a, b = socket.socketpair()
        with a, b:
            c.transmit(a, {'operation': 'status', 'arguments': {'send_id': 'synthetic'}})
            self.assertEqual(c.receive(b)['operation'], 'status')

    def test_oversize_invalid_and_truncated_frames(self):
        for packet in [struct.pack('!I', c.MAX_FRAME + 1), struct.pack('!I', 0), struct.pack('!I', 2) + b'[]',
                       struct.pack('!I', 3) + b'bad', struct.pack('!I', 2) + b'{']:
            a, b = socket.socketpair()
            with a, b:
                a.sendall(packet); a.shutdown(socket.SHUT_WR)
                with self.assertRaises(c.SendError): c.receive(b)

    def test_kernel_peer_identity_or_fail_closed(self):
        a, b = socket.socketpair()
        with a, b:
            if hasattr(socket, 'SO_PEERCRED'):
                self.assertEqual(c.peer_uid(a), os.geteuid())
            else:
                with self.assertRaises(c.SendError): c.peer_uid(a)

    def test_client_opt_in_distinct_identity_and_no_basic_mode(self):
        with patch.dict(os.environ, {}, clear=True): self.assertIsNone(c.ClientConfig.load())
        values = {'INBOXTETHER_SEND_ASSISTANT': '1', 'INBOXTETHER_SEND_MODE': 'secure',
                  'INBOXTETHER_SEND_SOCKET': '/run/inboxtether-send/request.sock', 'INBOXTETHER_SEND_UID': str(os.geteuid() + 1)}
        with patch.dict(os.environ, values, clear=True): self.assertIsNotNone(c.ClientConfig.load())
        for change in ({'INBOXTETHER_SEND_MODE': 'basic'}, {'INBOXTETHER_SEND_UID': str(os.geteuid())},
                       {'INBOXTETHER_SEND_UID': '0'}, {'INBOXTETHER_SEND_SOCKET': 'relative'}, {'INBOXTETHER_SEND_ASSISTANT': 'yes'}):
            with patch.dict(os.environ, {**values, **change}, clear=True), self.assertRaises(c.SendError): c.ClientConfig.load()

    def test_client_denies_non_socket_and_disallowed_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'not-socket'; path.write_text('synthetic')
            cfg = c.ClientConfig(path, os.geteuid() + 1)
            with self.assertRaises(c.SendError): c.request('prepare', {}, cfg)
            with self.assertRaises(c.SendError): c.request('approve', {}, cfg)

    def test_reader_default_and_no_mcp_send_approve_operation(self):
        async def names():
            return {t.name for t in await reader.create_server().list_tools()}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(asyncio.run(names()), {'list_mailboxes', 'search_messages', 'read_message', 'list_attachments', 'retrieve_attachment'})
        env = {'INBOXTETHER_SEND_ASSISTANT': '1', 'INBOXTETHER_SEND_UID': str(os.geteuid() + 1),
               'INBOXTETHER_SEND_SOCKET': '/run/inboxtether-send/request.sock'}
        with patch.dict(os.environ, env, clear=True):
            tools = asyncio.run(names())
            self.assertIn('prepare_send_message', tools)
            self.assertIn('send_request_status', tools)
            self.assertFalse(tools & {'send', 'send_email', 'approve_send'})

    def test_send_preparation_coexists_with_both_existing_draft_modes(self):
        async def names():
            return {t.name for t in await reader.create_server().list_tools()}
        env = {'INBOXTETHER_SEND_ASSISTANT': '1', 'INBOXTETHER_SEND_UID': str(os.geteuid() + 1),
               'INBOXTETHER_SEND_SOCKET': '/run/inboxtether-send/request.sock',
               'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_DRAFTS_FOLDER': 'Drafts',
               'INBOXTETHER_DRAFT_STATE_DIR': '/var/lib/inboxtether-drafts',
               'INBOXTETHER_BASIC_ACK': 'I_ACCEPT_CLIENT_CONTROLLED_APPROVAL'}
        for mode, save in [('basic', 'save_draft'), ('secure', 'save_approved_draft')]:
            with patch.dict(os.environ, {**env, 'INBOXTETHER_DRAFT_MODE': mode}, clear=True):
                tools = asyncio.run(names())
                self.assertEqual(len(tools), 9)
                self.assertTrue({'prepare_reply_draft', save, 'prepare_send_message', 'send_request_status'} <= tools)

    def test_mcp_bridge_only_prepare_status_and_complete_reply_identity(self):
        env = {'INBOXTETHER_SEND_ASSISTANT': '1', 'INBOXTETHER_SEND_UID': str(os.geteuid() + 1),
               'INBOXTETHER_SEND_SOCKET': '/run/inboxtether-send/request.sock'}
        with patch.dict(os.environ, env, clear=True), patch.object(c, 'request', return_value={'synthetic': True}) as request:
            reader.prepare_send_message(['to@example.com'], 'Synthetic', 'Synthetic body')
            self.assertEqual(request.call_args.args[0], 'prepare')
            reader.send_request_status('0' * 64)
            self.assertEqual(request.call_args.args[0], 'status')
            with self.assertRaises(reader.MailError):
                reader.prepare_send_message(['to@example.com'], 'Synthetic', 'Synthetic body', mailbox='INBOX')
