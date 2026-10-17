"""Regression: UIDPLUS may be advertised only after LOGIN."""
import imaplib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as r
import draft_assistant as d

class CapabilityRefreshTests(unittest.TestCase):
    def client(self, cls):
        client = object.__new__(cls)
        client.capabilities = ('IMAP4REV1', 'STALE')
        return client

    def test_reader_and_writer_refresh_after_login(self):
        for cls in (r.ReadOnlyIMAP, r.DraftAppendIMAP):
            with self.subTest(cls=cls.__name__):
                client = self.client(cls)
                calls = []
                def login(*args):
                    calls.append('LOGIN')
                    return 'OK', [b'authenticated']
                def capability():
                    calls.append('CAPABILITY')
                    return 'OK', [b'IMAP4rev1 uidplus']
                with patch.object(imaplib.IMAP4_SSL, 'login', side_effect=login), patch.object(client, 'capability', side_effect=capability):
                    self.assertEqual(client.login('user@example.com', 'synthetic'), ('OK', [b'authenticated']))
                self.assertEqual(calls, ['LOGIN', 'CAPABILITY'])
                self.assertEqual(client.capabilities, ('IMAP4REV1', 'UIDPLUS'))

    def test_failed_login_never_queries_or_keeps_stale_cache(self):
        client = self.client(r.ReadOnlyIMAP)
        with patch.object(imaplib.IMAP4_SSL, 'login', side_effect=imaplib.IMAP4.error('fixture')), patch.object(client, 'capability') as query:
            with self.assertRaises(imaplib.IMAP4.error):
                client.login('user@example.com', 'synthetic')
            query.assert_not_called()
        self.assertEqual(client.capabilities, ())

    def test_failed_or_malformed_refresh_fails_closed_without_server_details(self):
        for response in [('NO', [b'private-response']), ('OK', [None]), ('OK', []), ('OK', [b'']), ('OK', [b' ']), ('OK', [b'\xff'])]:
            with self.subTest(response=response):
                client = self.client(r.DraftAppendIMAP)
                with patch.object(imaplib.IMAP4_SSL, 'login', return_value=('OK', [])), patch.object(client, 'capability', return_value=response):
                    with self.assertRaises(r.MailError) as caught:
                        client.login('user@example.com', 'synthetic')
                self.assertNotIn('private-response', str(caught.exception))
                self.assertEqual(client.capabilities, ())

    def test_refresh_replaces_stale_uidplus(self):
        client = self.client(r.DraftAppendIMAP)
        client.capabilities = ('IMAP4REV1', 'UIDPLUS')
        with patch.object(imaplib.IMAP4_SSL, 'login', return_value=('OK', [])), patch.object(client, 'capability', return_value=('OK', [b'IMAP4rev1'])):
            client.login('user@example.com', 'synthetic')
        self.assertNotIn('UIDPLUS', client.capabilities)

    def test_basic_and_secure_prepare_check_fresh_authenticated_capabilities(self):
        for mode in ('basic', 'secure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                path.chmod(0o700)
                client = self.client(r.ReadOnlyIMAP)
                client.shutdown = lambda: None
                def listing(*args):
                    self.assertIn('UIDPLUS', client.capabilities)
                    return 'OK', [b'(\\Drafts) "/" "Drafts"']
                client.list = listing
                client.select = lambda *args, **kwargs: ('OK', [b'0'])
                client.response = lambda name: (name, [b'321'])
                service = d.DraftService(r, d.Config(r.HOST, r.ACCOUNT, 'Drafts', path, mode=mode))
                with patch.object(r, 'ReadOnlyIMAP', return_value=client), patch.object(r, 'password', return_value='synthetic'), patch.object(imaplib.IMAP4_SSL, 'login', return_value=('OK', [])), patch.object(client, 'capability', return_value=('OK', [b'IMAP4rev1 UIDPLUS'])), patch.object(r, 'fetch_message', return_value=b'Message-ID: <parent@example.com>\r\n\r\nFixture.'):
                    result = service.prepare('INBOX', 1, 123, ['recipient@example.com'], 'Re: Synthetic', 'Synthetic reply.')
                self.assertEqual(result['mode'], mode)
                self.assertEqual(service.store.get(result['draft_id'])['state'], 'pending')

    def test_writer_refresh_failure_closes_and_unlocks_before_append(self):
        client = self.client(r.DraftAppendIMAP)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory).chmod(0o700)
            service = d.DraftService(r, d.Config(r.HOST, r.ACCOUNT, 'Drafts', Path(directory)))
            with patch.object(r, 'DraftAppendIMAP', return_value=client), patch.object(r, 'password', return_value='synthetic'), patch.object(imaplib.IMAP4_SSL, 'login', return_value=('OK', [])), patch.object(client, 'capability', return_value=('NO', [b'private-response'])), patch.object(client, 'shutdown') as close, patch.object(client, 'append') as append:
                with self.assertRaises(r.MailError):
                    with service.writer():
                        self.fail('Writer yielded after failed capability discovery.')
                close.assert_called_once()
                append.assert_not_called()
            self.assertFalse(r.LOCK.locked())
