"""Required format coverage; all messages/attachments are fabricated."""
from email.message import EmailMessage
from email import policy as email_policy
import socket
import unittest
from unittest.mock import patch

from organizer.content import MimeView, TextSection, from_raw
from organizer.imap_adapter import GuardedIMAP, IMAPMailbox
from organizer.model import Message, OrganizerError
from organizer.structure import metadata, parse, sections
from format_support import Harness
from test_organizer import policy


def formatted(uid=1, category='Industry', *, html=None, attachment=False, customer=False, plain=None):
    message = EmailMessage(policy=email_policy.SMTP)
    message['From'] = 'customer@example.com' if customer else 'news@example.com'
    message['Authentication-Results']='mx.example.com; dmarc=pass header.from=example.com; dkim=pass header.d=example.com'
    message['To'] = 'owner@example.com'
    message['Subject'] = category + ' bulletin'
    message['Message-ID'] = f'<format-{uid}@example.com>'
    message['Date'] = 'Mon, 19 Oct 2026 12:00:00 +0000'
    if plain is not None: message.set_content(plain)
    elif html is None: message.set_content('Routine information.')
    if html is not None:
        if message.get_content_type() == 'text/plain' and message.get_payload(): message.add_alternative(html, subtype='html')
        else: message.set_content(html, subtype='html')
    if attachment:
        message.add_attachment(b'%PDF-1.7\nATTACHMENT-CANARY-NOT-A-DOCUMENT', maintype='application', subtype='pdf', filename='invoice.pdf')
    return Message(uid, message.as_bytes())


class FormatTests(Harness):
    def test_absent_optional_address_fields_do_not_disable_customer_registry(self):
        result=self.policy.classify(formatted(customer=True,html='<p>Routine information.</p>',attachment=True))
        self.assertTrue(result['customer']);self.assertIsNone(result['category'])

    def test_every_cc_occurrence_is_checked_for_customers(self):
        from test_organizer import mail
        msg=mail(extra='Cc: supplier@example.org\r\nCc: customer@example.com\r\n')
        result=self.policy.classify(msg)
        self.assertTrue(result['customer']);self.assertIsNone(result['category'])

    def test_known_customer_copied_on_vendor_mail_overrides_rule(self):
        from test_organizer import mail
        result=self.policy.classify(mail(extra='Cc: customer@example.com\r\n'))
        self.assertTrue(result['customer']);self.assertIsNone(result['category'])

    def test_visible_bcc_customer_and_sender_are_protected(self):
        from test_organizer import mail
        for header in ('Bcc','Sender'):
            result=self.policy.classify(mail(extra=header+': customer@example.com\r\n'))
            self.assertTrue(result['customer']);self.assertIsNone(result['category'])

    def test_html_newsletter_with_remote_image_no_network(self):
        message = formatted(html='<html><body><p>Routine industry information.</p><img src="https://example.com/pixel"></body></html>')
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            result = self.policy.classify(message)
        self.assertEqual(result['category'], 'Industry'); self.assertIn('Routine', result['text'])
        self.assertNotIn('<img', result['text']); self.assertNotIn('https://', result['text'])

    def test_supplier_invoice_pdf_metadata_only(self):
        message = formatted(category='Suppliers', attachment=True)
        result = self.policy.classify(message)
        self.assertEqual(result['category'], 'Suppliers')
        self.assertEqual(result['attachments'][0]['filename'], 'invoice.pdf')
        self.assertNotIn('ATTACHMENT-CANARY', result['text'])

    def test_html_order_confirmation_with_attachment(self):
        result = self.policy.classify(formatted(category='Orders', html='<html><body><p>Your vendor shipment has left.</p></body></html>', attachment=True))
        self.assertEqual(result['category'], 'Orders')

    def test_customer_attachment_overrides_every_category(self):
        for category in ('Industry', 'Marketing', 'Orders', 'Review', 'Suppliers'):
            result = self.policy.classify(formatted(category=category, html='<p>Routine notice.</p>', attachment=True, customer=True))
            self.assertTrue(result['customer']); self.assertIsNone(result['category'])

    def test_customer_only_in_html_alternative_is_protected(self):
        result = self.policy.classify(formatted(plain='Routine vendor information.', html='<html><body><p>A customer needs a transfer.</p></body></html>'))
        self.assertTrue(result['customer']); self.assertIsNone(result['category'])

    def test_customer_word_split_across_tags_or_zero_width_is_protected(self):
        for text in ('A cus<span>t</span>omer inquiry.', 'A custo\u200bmer inquiry.'):
            with self.subTest(text=text): self.assertTrue(self.policy.classify(formatted(html='<p>'+text+' order request</p>'))['customer'])

    def test_customer_attachment_filename_is_protection_evidence(self):
        msg = EmailMessage(policy=email_policy.SMTP)
        msg['From']='news@example.com';msg['Subject']='Orders bulletin';msg.set_content('Routine information.')
        msg.add_attachment(b'opaque',maintype='application',subtype='pdf',filename='customer-order.pdf')
        result = self.policy.classify(Message(1,msg.as_bytes()))
        self.assertTrue(result['customer']);self.assertIsNone(result['category'])

    def test_malformed_html_is_kept(self):
        for html in ('<html><body><p>Unclosed', '<div><b>Mismatch</div>', '<p>unfinished <', '<!-- missing end'):
            with self.subTest(html=html): self.assertIsNone(self.policy.classify(formatted(html=html))['category'])

    def test_active_html_is_kept_without_execution(self):
        for html in ('<script>doBadThings()</script><p>Routine</p>', '<p onclick="bad()">Routine</p>',
                     '<iframe src="https://example.com"></iframe>', '<a href="javascript:bad()">Routine</a>',
                     '<meta http-equiv="refresh" content="0;url=https://example.com"><p>Routine</p>'):
            with self.subTest(html=html): self.assertIsNone(self.policy.classify(formatted(html=html))['category'])

    def test_unterminated_markup_is_bounded_without_tag_stripping_regex(self):
        import time
        started=time.monotonic()
        result=self.policy.classify(formatted(html='<div>'+('<'*2000)))
        self.assertIsNone(result['category']);self.assertLess(time.monotonic()-started,2)

    def test_css_is_never_loaded_or_evaluated(self):
        message = formatted(html='<html><head><style>@import url(https://example.com/track);</style></head><body><p>Routine information.</p></body></html>')
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
            result = self.policy.classify(message)
        self.assertEqual(result['category'], 'Industry');self.assertNotIn('@import',result['text'])

    def test_encrypted_or_nested_messages_stay(self):
        for content_type in ('multipart/encrypted; boundary=x', 'application/pkcs7-mime', 'message/rfc822'):
            raw=('From: news@example.com\r\nSubject: Industry bulletin\r\nContent-Type: '+content_type+'\r\n\r\nopaque').encode()
            with self.subTest(content_type=content_type):self.assertIsNone(self.policy.classify(Message(1,raw))['category'])
        self.assertIsNone(self.policy.classify(formatted(plain='-----BEGIN PGP MESSAGE-----\nopaque'))['category'])

    def test_unsupported_charset_and_encoding_stay(self):
        for charset,encoding,payload in [('not-a-charset','8BIT',b'data'),('utf-8','BASE64',b'!!invalid!!'),('utf-8','QUOTED-PRINTABLE',b'=GG')]:
            view=MimeView(b'From: news@example.com\r\nSubject: Industry bulletin\r\n\r\n',
                          (TextSection('1','text/plain',charset,encoding,payload),),(), 'a'*64,100)
            self.assertIsNone(self.policy.classify(Message(1,view.headers,view=view))['category'])

    def test_format_message_read_flags_unchanged(self):
        from dataclasses import replace
        for flags in ((),('\\Seen',),('\\Answered','$Forwarded')):
            message=replace(formatted(html='<p>Routine information.</p>',attachment=True),flags=flags)
            before=message.evidence();self.policy.classify(message);self.assertEqual(message.evidence(),before)

    def test_approval_and_receipts_unchanged_for_html(self):
        self.box.boxes['INBOX'][1]=formatted(html='<html><body><p>Routine information.</p></body></html>',attachment=True)
        batch=self.frozen()
        with self.assertRaises(OrganizerError):self.org.execute(batch['batch_id'],1)
        import os
        self.org.decide(batch['batch_id'],batch['fingerprint'],True,{'method':'trusted-terminal','uid':os.geteuid()})
        self.assertEqual(self.org.execute(batch['batch_id'],1)['state'],'completed')

    def test_attachment_decoder_is_never_called(self):
        message=formatted(attachment=True)
        from email.message import Message as EmailPart
        original=EmailPart.get_payload
        def guard(part,*args,**kwargs):
            if kwargs.get('decode') and part.get_content_disposition()=='attachment':raise AssertionError('attachment decode prohibited')
            return original(part,*args,**kwargs)
        with patch.object(EmailPart,'get_payload',guard):
            self.assertEqual(self.policy.classify(message)['category'],'Industry')


class StructureTests(unittest.TestCase):
    def test_attachment_text_section_not_in_fetchable_set(self):
        tree=parse(b'(("TEXT" "HTML" ("CHARSET" "UTF-8") NIL NIL "7BIT" 20 1 NIL NIL)("APPLICATION" "PDF" ("NAME" "invoice.pdf") NIL NIL "BASE64" 999999 NIL ("ATTACHMENT" ("FILENAME" "invoice.pdf"))) "MIXED")')[0]
        text,attachments,blocked=sections(tree)
        self.assertEqual([t['section'] for t in text],['1']);self.assertEqual(attachments[0]['section'],'2');self.assertFalse(blocked)

    def test_nested_multipart_attachment_not_traversed(self):
        tree=parse(b'(("TEXT" "PLAIN" NIL NIL NIL "7BIT" 12 1) "MIXED" NIL ("ATTACHMENT" ("FILENAME" "nested")))')[0]
        self.assertTrue(sections(tree)[2]);self.assertEqual(sections(tree)[0],[])

    def test_bad_literals_depth_duplicate_params_and_encryption_refused(self):
        for data in (b'({123})', b'("unterminated)', b'('*40+b'NIL'+b')'*40):
            with self.subTest(data=data),self.assertRaises(ValueError):parse(data)
        tree=parse(b'("TEXT" "PLAIN" ("CHARSET" "UTF-8" "CHARSET" "ASCII") NIL NIL "7BIT" 1 1)')[0]
        with self.assertRaises(ValueError):sections(tree)

    def test_nontext_attachment_fetch_and_full_body_are_not_generally_allowed(self):
        client=object.__new__(GuardedIMAP);client._text_sections={'1'}
        for item in ('(UID BODY.PEEK[2]<0.131073>)','(UID BODY.PEEK[])','(UID BODY[])','(UID BODY.PEEK[]<0.262144>)'):
            with self.subTest(item=item),self.assertRaises(OrganizerError):client._command('UID','FETCH','1',item)
