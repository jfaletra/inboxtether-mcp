"""Synthetic-only optional alternative security tests; never contact a mailbox."""
from dataclasses import replace
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from html.parser import HTMLParser
import io
import json
import os
import time
import unittest
from unittest.mock import patch

import draft_assistant as d
import approval_web as w
from test_draft_assistant import DraftFixture


class RenderedText(HTMLParser):
    """Extract only text and explicit breaks within the generated body wrapper."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.text = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))
        if tag == 'div':
            self.inside = True
        elif tag == 'br' and self.inside:
            self.text.append('\r\n')

    def handle_endtag(self, tag):
        if tag == 'div':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.text.append(data)


class HtmlDraftTests(DraftFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.config = replace(self.config, html_alternative=True)
        self.service.config = self.config
        self.service.store = d.Store(self.config)

    def staged(self, **kw):
        result = self.prepare(**kw)
        item = self.service.store.get(result['draft_id'])
        msg = BytesParser(policy=policy.default).parsebytes(item['raw'])
        return result, item, msg

    def test_option_defaults_off_and_rejects_invalid_values(self):
        env = {'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_DRAFTS_FOLDER': 'Drafts',
               'INBOXTETHER_DRAFT_STATE_DIR': str(self.directory)}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(d.Config.load().html_alternative)
            with patch.dict(os.environ, {'INBOXTETHER_DRAFT_HTML_ALTERNATIVE': '1'}):
                self.assertTrue(d.Config.load().html_alternative)
            for invalid in ('true', 'yes', '', '2'):
                with patch.dict(os.environ, {'INBOXTETHER_DRAFT_HTML_ALTERNATIVE': invalid}), self.assertRaises(d.DraftError):
                    d.Config.load()
        with patch.dict(os.environ, {'INBOXTETHER_DRAFT_HTML_ALTERNATIVE': '1'}, clear=True):
            self.assertIsNone(d.Config.load())

    def test_plain_composer_does_not_inherit_implicit_html_option(self):
        from types import SimpleNamespace
        with patch.dict(os.environ, {'INBOXTETHER_DRAFT_HTML_ALTERNATIVE': '1'}):
            raw = d.reply_bytes(SimpleNamespace(account='sender@example.com'),
                                b'Message-ID: <parent@example.com>\r\n\r\nSynthetic',
                                ['recipient@example.com'], 'Re: Synthetic', 'One\n\nTwo', None, None)
        self.assertFalse(BytesParser(policy=policy.default).parsebytes(raw).is_multipart())

    def test_default_plain_mime_and_legacy_approval_remain_usable(self):
        plain = replace(self.config, html_alternative=False)
        self.service.config = plain
        self.service.store = d.Store(plain)
        result, item, msg = self.staged(body='First\n\nSignature')
        self.assertFalse(msg.is_multipart())
        self.assertNotIn('body_format', item['manifest']['scope'])
        self.assertNotIn('html_body', result['preview'])
        self.service.store.approve(result['draft_id'], result['approval_fingerprint'])
        self.assertEqual(self.service.save(result['draft_id'])['status'], 'saved')

    def test_plain_bytes_equal_plain_only_composer_after_decoding(self):
        body = 'Café ✓\n\nFirst paragraph.\n\n\nSecond paragraph.\n\nRegards,\nSynthetic User'
        _, item, msg = self.staged(body=body)
        plain = replace(self.config, html_alternative=False)
        raw = d.reply_bytes(plain, b'Message-ID: <parent@example.com>\r\n\r\nSynthetic',
                            ['recipient@example.com'], 'Re: Parent', body, None, None)
        original = BytesParser(policy=policy.default).parsebytes(raw)
        parts = list(msg.iter_parts())
        self.assertEqual([p.get_content_type() for p in parts], ['text/plain', 'text/html'])
        self.assertEqual(parts[0].get_payload(decode=True), original.get_payload(decode=True))
        self.assertEqual(item['manifest']['preview']['body'], parts[0].get_content())
        renderer = RenderedText()
        renderer.feed(parts[1].get_content())
        self.assertEqual(''.join(renderer.text), parts[0].get_content())

    def test_escaping_never_creates_active_tags_attributes_or_remote_content(self):
        body = '<script>alert("x")</script>\n\n<img src="https://example.com/pixel" onerror="x">\n& < > " \' <a href="javascript:x">literal</a>'
        result, _, msg = self.staged(body=body)
        html = list(msg.iter_parts())[1].get_content()
        parser = RenderedText()
        parser.feed(html)
        self.assertTrue(all(tag in {'html', 'body', 'div', 'br'} and not attrs for tag, attrs in parser.tags))
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('<a ', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertEqual(''.join(parser.text), result['preview']['body'])

    def test_blank_trailing_lines_tabs_and_signature_preserved(self):
        for body in ('First\n\n\nSecond\n\nSignature\nTwo', 'First  \n\tSecond\n\n', 'One\n'):
            with self.subTest(body=repr(body)):
                result, _, msg = self.staged(body=body)
                expected = (body if body.endswith('\n') else body+'\n').replace('\n', '\r\n')
                self.assertEqual(result['preview']['body'], expected)
                parser = RenderedText(); parser.feed(list(msg.iter_parts())[1].get_content())
                self.assertEqual(''.join(parser.text), expected)

    def test_format_renderer_and_both_parts_bound_to_full_approval(self):
        result, item, _ = self.staged()
        m = item['manifest']
        self.assertEqual(m['scope']['body_format'], 'plain-html')
        self.assertEqual(m['scope']['renderer_version'], d.HTML_RENDERER_VERSION)
        self.assertEqual(result['preview']['renderer_version'], d.HTML_RENDERER_VERSION)
        self.assertEqual(result['mime_sha256'], d.digest(item['raw']))
        self.assertEqual(result['approval_fingerprint'], d.digest(d.canonical(m)))
        self.assertEqual(self.service.confirmation(item)['message']['html_body'], result['preview']['html_body'])
        with self.assertRaises(d.DraftError):
            self.service.save(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_exact_save_replay_and_threading_use_complete_mime(self):
        result, item, msg = self.staged()
        self.assertEqual(str(msg['In-Reply-To']), '<parent@example.com>')
        self.assertEqual(str(msg['References']), '<root@example.com> <parent@example.com>')
        self.service.store.approve(result['draft_id'], result['approval_fingerprint'])
        saved = self.service.save(result['draft_id'])
        self.assertEqual(saved['sha256'], d.digest(item['raw']))
        self.assertEqual(self.fake.saved, item['raw'])
        self.assertEqual(self.service.save(result['draft_id']), saved)
        self.assertEqual(self.fake.append_count, 1)

    def test_basic_confirmation_includes_html_and_rejects_altered_alternative(self):
        self.config = replace(self.config, mode='basic')
        self.service.config = self.config; self.service.store = d.Store(self.config)
        result, item, _ = self.staged()
        confirmation = self.service.confirmation(item)
        changed = json.loads(json.dumps(confirmation)); changed['message']['html_body'] += 'x'
        with self.assertRaises(d.DraftError):
            self.service.save_basic(result['draft_id'], changed)
        self.assertEqual(self.fake.append_count, 0)
        self.assertEqual(self.service.save_basic(result['draft_id'], confirmation)['status'], 'saved')

    def test_expiry_and_configuration_change_never_fall_back(self):
        result, _, _ = self.staged()
        with patch.object(d.time, 'time', return_value=time.time()+d.TTL+1), self.assertRaises(d.DraftError):
            self.service.store.get(result['draft_id'])
        with self.assertRaises(d.DraftError):
            d.Store(replace(self.config, html_alternative=False)).get(result['draft_id'])
        with patch.object(d, 'HTML_RENDERER_VERSION', 'future-renderer'), self.assertRaises(d.DraftError):
            self.service.store.get(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_tampering_either_part_is_rejected_before_save(self):
        result, item, msg = self.staged()
        for index in (0, 1):
            changed = BytesParser(policy=policy.default).parsebytes(item['raw'])
            parts = list(changed.iter_parts())
            kind = ('plain', 'html')[index]
            parts[index].set_content('changed', subtype=kind, charset='utf-8', cte='quoted-printable')
            with self.assertRaises(d.DraftError):
                d.preview(changed.as_bytes(policy=policy.SMTP), True)
        with self.service.store.db() as db:
            db.execute('UPDATE drafts SET raw=? WHERE id=?', (item['raw']+b'x', result['draft_id'])); db.commit()
        with self.assertRaises(d.DraftError):self.service.store.get(result['draft_id'])
        self.assertEqual(self.fake.append_count, 0)

    def test_only_exact_two_leaf_structure_and_generated_headers_allowed(self):
        _, item, _ = self.staged()
        def parse():return BytesParser(policy=policy.default).parsebytes(item['raw'])
        variants=[]
        m=parse();m.set_type('multipart/mixed');variants.append(m)
        m=parse();m.set_payload(list(reversed(list(m.iter_parts()))));variants.append(m)
        m=parse();m.set_payload(list(m.iter_parts())[:1]);variants.append(m)
        m=parse();m.attach(EmailMessage());variants.append(m)
        m=parse();list(m.iter_parts())[1]['Content-Location']='https://example.com/pixel';variants.append(m)
        m=parse();list(m.iter_parts())[0]['Content-Disposition']='attachment; filename="x.txt"';variants.append(m)
        m=parse();list(m.iter_parts())[1].make_alternative();variants.append(m)
        m=parse();m._headers.append(('Content-Type', 'multipart/alternative; boundary=duplicate'));variants.append(m)
        m=parse();del m['From'];variants.append(m)
        for message in variants:
            with self.subTest(headers=list(message.keys())), self.assertRaises(d.DraftError):
                d.preview(message.as_bytes(policy=policy.SMTP), True)
        with self.assertRaises(d.DraftError):d.preview(item['raw'])

    def test_malformed_boundaries_encoding_charset_and_active_html_rejected(self):
        _, item, _ = self.staged()
        msg=BytesParser(policy=policy.default).parsebytes(item['raw'])
        boundary=msg.get_boundary().encode()
        variants=[item['raw'].replace(b'--'+boundary+b'--', b'--missing--'),
                  item['raw'].replace(b'charset="utf-8"', b'charset="ascii"'),
                  item['raw'].replace(b'quoted-printable', b'base64', 1),
                  item['raw'].replace(b'<br>', b'<img src="x">', 1)]
        for raw in variants:
            with self.assertRaises(d.DraftError):d.preview(raw, True)

    def test_uncertain_append_is_never_retried(self):
        result, item, _ = self.staged()
        self.service.store.approve(result['draft_id'], result['approval_fingerprint'])
        self.fake.raise_append = True
        first = self.service.save(result['draft_id'])
        self.assertEqual(first['status'], 'uncertain')
        self.assertFalse(first['retry_allowed'])
        self.assertEqual(self.service.save(result['draft_id']), first)
        self.assertEqual(self.fake.append_count, 1)

    def test_concurrent_approval_consumption_has_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        result, item, _ = self.staged()
        self.service.store.approve(result['draft_id'], result['approval_fingerprint'])
        def claim(_):
            try:
                self.service.store.claim(result['draft_id'], result['approval_fingerprint'])
                return True
            except d.DraftError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(claim, range(2))), [False, True])
        self.assertEqual(self.fake.append_count, 0)

    def test_encoded_limits_and_expanded_html_size_are_bounded(self):
        _, item, msg = self.staged(body=('Unicode café & <literal> '*35)+'\n\nSignature')
        self.assertNotRegex(item['raw'], rb'(?<!\r)\n|\r(?!\n)')
        for part in msg.iter_parts():
            self.assertEqual(part['Content-Transfer-Encoding'], 'quoted-printable')
            self.assertLessEqual(max(map(len,part.get_payload().split('\r\n'))),76)
        with self.assertRaises(d.DraftError):self.prepare(body='<'*19000)

    def test_browser_review_never_executes_generated_html(self):
        _, item, _ = self.staged(body='<img src="https://example.com/private">\n\nLine')
        class Tokens:
            def issue(self,*a):return 'synthetic-csrf'
        response=w.review_page(item,{'issuer':'https://identity.example.com','subject':'owner'},'nonce',Tokens())
        page=response.body.decode()
        self.assertIn('plain text + generated HTML',page)
        self.assertIn('Generated HTML source (not executed)',page)
        self.assertNotIn('<html><body><div>',page)
        self.assertNotIn('<img src="https://example.com/private">',page)
