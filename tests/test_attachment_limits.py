import base64
import hashlib
from email.message import EmailMessage
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s
from test_enhancements import fixture
from test_server import Fake


class AttachmentBoundaryTests(unittest.TestCase):
    def selected(self, raw, index=1):
        fake=Fake()
        fake.raw=raw
        fake.size=len(raw)
        with patch.object(s,'password',return_value='fixture-only'), patch.object(s,'ReadOnlyIMAP',return_value=fake):
            choices=s.list_attachments('INBOX',20,123)
            choice=choices['attachments'][index-1]
            return s.retrieve_attachment('INBOX',20,123,choice['attachment_id'])

    def test_maximum_size_allowed(self):
        data=b'a'*s.MAX_ATTACHMENT
        result=self.selected(fixture(data))
        self.assertEqual(result['size_bytes'],s.MAX_ATTACHMENT)
        self.assertEqual(base64.b64decode(result['data']),data)
        self.assertEqual(result['sha256'],hashlib.sha256(data).hexdigest())

    def test_selects_only_second_attachment(self):
        msg=EmailMessage();msg.set_content('Body')
        msg.add_attachment(b'FIRST MUST STAY PRIVATE',maintype='text',subtype='plain',filename='one.txt')
        msg.add_attachment(b'Selected second',maintype='text',subtype='plain',filename='two.txt')
        result=self.selected(msg.as_bytes(),2)
        self.assertEqual(base64.b64decode(result['data']),b'Selected second')
        self.assertEqual(result['filename'],'two.txt')

    def test_allowed_mime_pairs(self):
        for data,kind,name in [(b'%PDF-1.4\nsynthetic', 'application/pdf','fixture.pdf'),
                               (b'\x89PNG\r\n\x1a\nsynthetic','image/png','fixture.png'),
                               (b'\xff\xd8\xffsynthetic','image/jpeg','fixture.jpeg'),
                               (b'a,b\n1,2','text/csv','fixture.csv')]:
            with self.subTest(kind=kind):
                self.assertEqual(base64.b64decode(self.selected(fixture(data,kind,name))['data']),data)

    def test_bad_mime_rejected(self):
        raw=b'MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=x\r\n\r\nNo matching boundary.'
        with self.assertRaises(s.MailError):s.attachment_parts(raw)

    def test_attachment_count_limit(self):
        msg=EmailMessage();msg.set_content('Body')
        for i in range(51):msg.add_attachment(b'hello',maintype='text',subtype='plain',filename=f'{i}.txt')
        with self.assertRaises(s.MailError):s.attachment_parts(msg.as_bytes())

    def test_malformed_base64_rejected(self):
        raw=fixture().replace(b'aGVsbG8=',b'aGVsbG8@@@=')
        part=s.attachment_parts(raw)[0]
        with self.assertRaises(s.MailError):s.attachment_data(part)

    def test_unexpected_parser_error_redacted(self):
        fake=Fake();fake.raw=fixture();fake.size=len(fake.raw)
        with patch.object(s,'password',return_value='fixture-only'), patch.object(s,'ReadOnlyIMAP',return_value=fake), patch.object(s,'attachment_parts',side_effect=ValueError('private content')):
            with self.assertRaises(s.MailError) as caught:s.list_attachments('INBOX',20,123)
        self.assertNotIn('private content',str(caught.exception))

    def test_attached_message_blocked(self):
        outer=EmailMessage();outer.set_content('body')
        nested=EmailMessage();nested.set_content('Nested private mail')
        outer.add_attachment(nested,filename='mail.eml')
        part=s.attachment_parts(outer.as_bytes())[0]
        with self.assertRaises(s.MailError):s.attachment_data(part)

    def test_depth_limit(self):
        msg=EmailMessage();msg.set_content('leaf')
        for _ in range(22):
            parent=EmailMessage();parent.make_mixed();parent.attach(msg);msg=parent
        with self.assertRaises(s.MailError):s.attachment_parts(msg.as_bytes())

    def test_selection_arguments_validated_before_login(self):
        selection='a'*64+':1'
        with patch.object(s,'password') as password:
            for args in [('INBOX\r\nDELETE X',20,123),('INBOX',0,123),('INBOX',20,0),('INBOX',True,123)]:
                with self.subTest(args=args),self.assertRaises(s.MailError):s.retrieve_attachment(*args,selection)
            password.assert_not_called()

class AttachmentSDKTests(unittest.TestCase):
    def test_attachment_schema_and_synthetic_calls(self):
        import asyncio
        async def run():
            app=s.create_server()
            tools={t.name:t for t in await app.list_tools()}
            self.assertEqual(set(tools['retrieve_attachment'].inputSchema['required']),{'mailbox','uid','uidvalidity','attachment_id'})
            self.assertEqual(set(tools['list_attachments'].inputSchema['required']),{'mailbox','uid','uidvalidity'})
            self.assertTrue(tools['retrieve_attachment'].annotations.readOnlyHint)
            fake=Fake();fake.raw=fixture();fake.size=len(fake.raw)
            selection=hashlib.sha256(fake.raw).hexdigest()+':1'
            with patch.object(s,'password',return_value='fixture-only'),patch.object(s,'ReadOnlyIMAP',return_value=fake):
                listing=await app.call_tool('list_attachments',{'mailbox':'INBOX','uid':20,'uidvalidity':123})
                result=await app.call_tool('retrieve_attachment',{'mailbox':'INBOX','uid':20,'uidvalidity':123,'attachment_id':selection})
            self.assertIn('note.txt',str(listing))
            self.assertIn('aGVsbG8=',str(result))
        asyncio.run(run())
