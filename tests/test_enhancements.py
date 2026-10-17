import base64
from contextlib import contextmanager
from email.message import EmailMessage
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s
from test_server import Fake, RAW


def fixture(data=b'hello', kind='text/plain', filename='note.txt'):
    msg = EmailMessage()
    msg['Subject'] = 'Synthetic attachment fixture'
    msg.set_content('Visible message body')
    major, minor = kind.split('/')
    msg.add_attachment(data, maintype=major, subtype=minor, filename=filename)
    return msg.as_bytes()


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.fake.raw = fixture()
        self.fake.size = len(self.fake.raw)
        for p in (patch.object(s, 'password', return_value='fixture-only'),
                  patch.object(s, 'ReadOnlyIMAP', return_value=self.fake)):
            p.start()
            self.addCleanup(p.stop)

    def choose(self):
        return s.list_attachments('INBOX', 20, 123)['attachments'][0]['attachment_id']

    def test_list_then_selected_retrieval(self):
        choices = s.list_attachments('INBOX', 20, 123)
        self.assertNotIn('data', choices)
        self.assertTrue(all('data' not in item for item in choices['attachments']))
        part = choices['attachments'][0]
        self.assertTrue(part['retrievable'])
        result = s.retrieve_attachment('INBOX', 20, 123, part['attachment_id'])
        self.assertEqual(base64.b64decode(result['data']), b'hello')
        self.assertEqual(result['size_bytes'], 5)
        self.assertIn('Untrusted', result['notice'])
        self.assertTrue(self.fake.closed)
        self.assertTrue(all(call[0] in ('LOGIN', 'EXAMINE', 'UID') for call in self.fake.calls))

    def test_read_message_never_returns_attachment_data(self):
        result = s.read_message('INBOX', 20, 123)
        self.assertNotIn('hello', result['text'])
        self.assertNotIn('data', result['attachments'][0])

    def test_missing_selection_rejected_before_network(self):
        for selection in ('', '1', '../file', 'a'*64+':0', 'a'*64+':100', None):
            with self.subTest(selection=selection), self.assertRaises(s.MailError):
                s.retrieve_attachment('INBOX', 20, 123, selection)
        self.assertEqual(self.fake.calls, [])

    def test_stale_selection(self):
        selection = self.choose()
        self.fake.raw = fixture(b'changed')
        self.fake.size = len(self.fake.raw)
        with self.assertRaisesRegex(s.MailError, 'stale'):
            s.retrieve_attachment('INBOX', 20, 123, selection)

    def test_uidvalidity_mismatch_prevents_fetch(self):
        with self.assertRaises(s.MailError):
            s.list_attachments('INBOX', 20, 124)
        self.assertFalse(any(c[:2] == ('UID', 'FETCH') for c in self.fake.calls))

    def test_size_cap(self):
        self.fake.raw = fixture(b'a'*(s.MAX_ATTACHMENT + 1))
        self.fake.size = len(self.fake.raw)
        part = s.list_attachments('INBOX', 20, 123)['attachments'][0]
        self.assertFalse(part['retrievable'])
        with self.assertRaises(s.MailError):
            s.retrieve_attachment('INBOX', 20, 123, part['attachment_id'])

    def test_message_cap_prevents_body_fetch(self):
        self.fake.size = s.MAX_MESSAGE + 1
        with self.assertRaises(s.MailError):
            s.list_attachments('INBOX', 20, 123)
        self.assertFalse(any(c[-1] == '(UID BODY.PEEK[])' for c in self.fake.calls))

    def test_types_paths_signatures_and_binary_text(self):
        cases = [(b'<script>x</script>', 'text/html', 'x.html'),
                 (b'PKzip', 'application/zip', 'x.zip'),
                 (b'MZexe', 'application/pdf', 'x.pdf'),
                 (b'fake', 'image/png', 'x.png'),
                 (b'fake', 'image/jpeg', 'x.jpg'),
                 (b'hi', 'text/plain', '../x.txt'),
                 (b'hi', 'text/plain', 'x.exe'),
                 (b'hi', 'text/plain', 'C:\\x.txt'),
                 (b'\x00binary', 'text/plain', 'x.txt'),
                 (b'\xff', 'text/plain', 'x.txt')]
        for data, kind, name in cases:
            with self.subTest(kind=kind, name=name):
                self.fake.raw = fixture(data, kind, name)
                self.fake.size = len(self.fake.raw)
                part = s.list_attachments('INBOX', 20, 123)['attachments'][0]
                self.assertFalse(part['retrievable'])
                with self.assertRaises(s.MailError):
                    s.retrieve_attachment('INBOX', 20, 123, part['attachment_id'])

    def test_empty_and_nonexistent_attachment(self):
        selection = self.choose()
        with self.assertRaises(s.MailError):
            s.retrieve_attachment('INBOX', 20, 123, selection.split(':')[0]+':2')
        self.fake.raw = RAW
        self.fake.size = len(RAW)
        self.assertEqual(s.list_attachments('INBOX', 20, 123)['attachments'], [])


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        for p in (patch.object(s, 'password', return_value='fixture-only'),
                  patch.object(s, 'ReadOnlyIMAP', return_value=self.fake)):
            p.start()
            self.addCleanup(p.stop)

    def test_additive_shape_and_no_body(self):
        result = s.search_messages(limit=2)
        self.assertEqual(result['uids'], [20, 2])
        self.assertEqual([m['uid'] for m in result['messages']], result['uids'])
        self.assertEqual(result['messages'][0]['subject'], 'Hello')
        self.assertIn('sender@example.com', result['messages'][0]['sender'])
        self.assertIn('2026', result['messages'][0]['date'])
        self.assertTrue(all(m['uidvalidity'] == 123 for m in result['messages']))
        self.assertNotIn('(UID BODY.PEEK[])', [c[-1] for c in self.fake.calls])

    def test_no_matches_no_header_fetch(self):
        self.fake.search = b''
        result = s.search_messages()
        self.assertEqual(result['messages'], [])
        self.assertFalse(any(c[:2] == ('UID', 'FETCH') for c in self.fake.calls))

    def test_header_mismatch_missing_and_oversize(self):
        for rows in ([b'1 (UID 999)'], [b'1 (UID 20)'],
                     [(b'1 (UID 20 BODY[HEADER.FIELDS (FROM SUBJECT DATE)]<0> {16385}', b'x'*16385), b')']):
            def uid(*args):
                return ('OK', [b'20']) if args[0] == 'SEARCH' else ('OK', rows)
            with patch.object(self.fake, 'uid', side_effect=uid), self.assertRaises(s.MailError):
                s.search_messages()

    def test_missing_headers_and_uid_after_literal(self):
        def uid(*args):
            if args[0] == 'SEARCH':
                return 'OK', [b'20']
            return 'OK', [(b'1 (BODY[HEADER.FIELDS (FROM SUBJECT DATE)]<0> {2}', b'\r\n'), b' UID 20)']
        with patch.object(self.fake, 'uid', side_effect=uid):
            result = s.search_messages()
        self.assertEqual(result['messages'][0]['sender'], '')
        self.assertEqual(result['messages'][0]['subject'], '')


if __name__ == '__main__':
    unittest.main()
