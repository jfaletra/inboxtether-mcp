"""Synthetic MIME interoperability checks; these do not certify a client UI."""
import json
import quopri
import unittest
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from unittest.mock import patch

from test_draft_assistant import DraftFixture
import draft_assistant as d


def lf(text):
    return text.replace('\r\n', '\n')


class DraftMimeFormattingTests(DraftFixture, unittest.TestCase):
    def staged(self, body):
        result = self.prepare(body=body)
        item = self.service.store.get(result['draft_id'])
        return result, item['raw'], BytesParser(policy=policy.default).parsebytes(item['raw'])

    def test_multiline_without_trailing_newline_preserves_every_break(self):
        body = 'Hello,\n\nFirst paragraph.\nSecond line.\n\nRegards,\nSynthetic User'
        result, raw, msg = self.staged(body)
        self.assertEqual(lf(msg.get_content()), body + '\n')
        self.assertEqual(lf(result['preview']['body']), body + '\n')
        self.assertEqual(self.fake.append_count, 0)

    def test_json_argument_roundtrip_keeps_real_paragraph_and_signature_breaks(self):
        body = "Hello,\n\nFirst paragraph.\n\nSecond paragraph.\n\nThanks,\nSynthetic User\nExample Project"
        arguments = json.loads(json.dumps({'body': body}))
        _, _, msg = self.staged(arguments['body'])
        self.assertEqual(lf(msg.get_content()), body + '\n')
        self.assertEqual(lf(msg.get_content()).count('\n\n'), 3)

    def test_literal_backslash_sequences_are_not_silently_expanded(self):
        body = r'First paragraph.\n\nSecond paragraph.'
        _, _, msg = self.staged(body)
        self.assertEqual(lf(msg.get_content()), body + '\n')

    def test_crlf_input_is_rejected_not_silently_rewritten(self):
        # Tool input uses LF; SMTP serialization supplies CRLF before approval.
        # Preserve validation rather than accepting arbitrary CR controls.
        with self.assertRaises(d.DraftError):
            self.staged('First\r\n\r\nSecond')

    def test_existing_trailing_and_blank_lines_are_preserved(self):
        for body in ('One\n\nTwo\n', 'One\n\nTwo\n\n', 'One\n\n\nTwo'):
            with self.subTest(body=repr(body)):
                _, _, msg = self.staged(body)
                self.assertEqual(lf(msg.get_content()), body if body.endswith('\n') else body + '\n')

    def test_standard_plain_text_mime_headers(self):
        _, raw, msg = self.staged('First\n\nSecond')
        self.assertEqual(msg.get_content_type(), 'text/plain')
        self.assertEqual(msg.get_content_charset(), 'utf-8')
        self.assertEqual(msg['Content-Transfer-Encoding'], 'quoted-printable')
        self.assertEqual(msg['MIME-Version'], '1.0')
        self.assertIsNone(msg.get_param('format'))
        self.assertFalse(msg.is_multipart())
        self.assertEqual(msg.defects, [])

    def test_serialized_mime_uses_only_crlf_and_legal_line_lengths(self):
        _, raw, msg = self.staged(('Long synthetic line ' * 50) + '\n\nLast paragraph.')
        self.assertNotRegex(raw, rb'(?<!\r)\n|\r(?!\n)')
        self.assertTrue(raw.endswith(b'\r\n'))
        self.assertLessEqual(max(map(len, raw.split(b'\r\n'))), 998)
        encoded_body = raw.split(b'\r\n\r\n', 1)[1]
        self.assertLessEqual(max(map(len, encoded_body.split(b'\r\n'))), 76)
        self.assertIn(b'=\r\n', encoded_body)

    def test_quoted_printable_soft_wraps_do_not_replace_paragraph_breaks(self):
        body = ('A deliberately long synthetic sentence. ' * 12) + '\n\nSeparate paragraph.'
        _, raw, msg = self.staged(body)
        encoded = raw.split(b'\r\n\r\n', 1)[1]
        decoded = quopri.decodestring(encoded).decode('utf-8')
        self.assertEqual(lf(decoded), body + '\n')
        self.assertIn('\r\n\r\n', decoded)

    def test_unicode_and_trailing_whitespace_roundtrip(self):
        body = 'Café — synthetic reply ✓\n\nLine with trailing spaces  \nNext\tline'
        _, _, msg = self.staged(body)
        self.assertEqual(lf(msg.get_content()), body + '\n')

    def test_multiple_standard_parser_policies_decode_identically(self):
        body = 'Greeting\n\nParagraph one.\nParagraph two.\n\nSignature'
        _, raw, _ = self.staged(body)
        for parser_policy in (policy.default, policy.SMTP, policy.compat32):
            with self.subTest(policy=repr(parser_policy)):
                parsed = BytesParser(policy=parser_policy).parsebytes(raw)
                decoded = parsed.get_payload(decode=True).decode(parsed.get_content_charset())
                self.assertEqual(lf(decoded), body + '\n')
                self.assertEqual(parsed.defects, [])

    def test_html_looking_body_remains_inert_plain_text(self):
        body = 'Literal <b>text</b>\n\n<img src="https://example.invalid/pixel">'
        _, _, msg = self.staged(body)
        self.assertEqual(msg.get_content_type(), 'text/plain')
        self.assertEqual(lf(msg.get_content()), body + '\n')
        self.assertEqual(len(list(msg.walk())), 1)

    def test_encoding_fix_keeps_original_header_bytes_and_decoded_body(self):
        body = ('Unicode café and a long synthetic line. ' * 12) + '\n\nSignature  \nExample User'
        arguments = (self.config, b'Message-ID: <parent@example.com>\r\n\r\nSynthetic',
                     ['one@example.com', 'two@example.com'],
                     'A long synthetic subject with Unicode café and words ' * 3,
                     body, ['copy@example.com'], None)
        # Compare the original v1.2.0 SMTP policy with the correction, using the
        # same identities/date. No network, staging or client UI is involved.
        with patch.object(d, 'format_datetime', return_value='Sat, 17 Oct 2026 12:00:00 +0000'), \
                patch.object(d.secrets, 'token_hex', return_value='a' * 48):
            corrected = d.reply_bytes(*arguments)
            with patch.object(d, 'EmailMessage', side_effect=lambda **kw: EmailMessage(policy=policy.SMTP)):
                baseline = d.reply_bytes(*arguments)
        old_headers, old_encoded = baseline.split(b'\r\n\r\n', 1)
        new_headers, new_encoded = corrected.split(b'\r\n\r\n', 1)
        self.assertEqual(new_headers, old_headers)
        self.assertNotEqual(new_encoded, old_encoded)
        self.assertEqual(quopri.decodestring(new_encoded), quopri.decodestring(old_encoded))
        self.assertEqual(lf(quopri.decodestring(new_encoded).decode()), body + '\n')
        self.assertLessEqual(max(map(len, new_encoded.split(b'\r\n'))), 76)

    def test_mock_imap_save_preserves_exact_approved_multiline_bytes(self):
        result, raw, msg = self.staged('Hello\n\nFirst paragraph.\n\nSecond paragraph.\nSignature')
        self.service.store.approve(result['draft_id'], result['approval_fingerprint'])
        saved = self.service.save(result['draft_id'])
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(self.fake.append_count, 1)
        self.assertEqual(self.fake.saved, raw)
        self.assertEqual(BytesParser(policy=policy.default).parsebytes(self.fake.saved).get_content(), msg.get_content())


if __name__ == '__main__':
    unittest.main()
