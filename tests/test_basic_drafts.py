"""Basic Mode delegates authority to the client, never proves a human approved."""
import asyncio
import copy
from dataclasses import replace
import json
import time
import unittest
from unittest.mock import patch

import draft_assistant as d
import server as r
from test_draft_assistant import DraftFixture


class BasicDraftTests(DraftFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.config = replace(self.config, mode='basic')
        self.service.config = self.config
        self.service.store = d.Store(self.config)

    def test_explicit_enablement_and_no_fallback(self):
        env = {'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_DRAFT_MODE': 'basic',
               'INBOXTETHER_DRAFT_STATE_DIR': str(self.directory), 'INBOXTETHER_DRAFTS_FOLDER': 'Drafts'}
        with patch.dict('os.environ', env, clear=True), self.assertRaises(d.DraftError):
            d.Config.load()
        env['INBOXTETHER_BASIC_ACK'] = 'I_ACCEPT_CLIENT_CONTROLLED_APPROVAL'
        with patch.dict('os.environ', env, clear=True):
            self.assertEqual(d.Config.load().mode, 'basic')
        for changes in ({'INBOXTETHER_DRAFT_MODE': 'unknown'}, {'INBOXTETHER_BROWSER_APPROVAL': '1'}):
            with patch.dict('os.environ', {**env, **changes}, clear=True), self.assertRaises(d.DraftError):
                d.Config.load()
        with patch.dict('os.environ', {'INBOXTETHER_DRAFT_MODE': 'basic'}, clear=True):
            self.assertIsNone(d.Config.load())

    def test_full_confirmation_exact_save_and_nonhuman_receipt(self):
        result = self.prepare()
        confirmation = result['confirmation']
        self.assertEqual(result['mode'], 'basic')
        for name in ('From', 'To', 'Cc', 'Bcc', 'Subject', 'body', 'In-Reply-To', 'References'):
            self.assertIn(name, confirmation['message'])
        self.assertEqual(confirmation['destination']['folder'], 'Drafts')
        saved = self.service.save_basic(result['draft_id'], confirmation)
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['sha256'], result['mime_sha256'])
        self.assertIn(b'In-Reply-To: <parent@example.com>', self.fake.saved)
        self.assertEqual(self.service.save_basic(result['draft_id'], confirmation), saved)
        self.assertEqual(self.fake.append_count, 1)
        with self.service.store.db() as db:
            actor = json.loads(db.execute('SELECT actor FROM decisions').fetchone()[0])
        self.assertEqual(actor, {'method': 'client-controlled-basic', 'human_verified': False})

    def test_all_confirmation_fields_are_bound(self):
        result = self.prepare()
        candidates = []
        for name in result['confirmation']['message']:
            changed = copy.deepcopy(result['confirmation']); changed['message'][name] += 'changed'; candidates.append(changed)
        for name in result['confirmation']['destination']:
            changed = copy.deepcopy(result['confirmation']); changed['destination'][name] += 'changed'; candidates.append(changed)
        for name in ('fingerprint', 'mime_sha256', 'expires_at', 'drafts_uidvalidity'):
            changed = copy.deepcopy(result['confirmation']); changed.pop(name); candidates.append(changed)
        for confirmation in candidates + [{}, {'approved': True}]:
            with self.assertRaises(d.DraftError):
                self.service.save_basic(result['draft_id'], confirmation)
        self.assertEqual(self.service.store.get(result['draft_id'])['state'], 'pending')
        self.assertEqual(self.fake.append_count, 0)

    def test_secure_basic_cross_mode_refused(self):
        result = self.prepare()
        with self.assertRaises(d.DraftError): self.service.save(result['draft_id'])
        secure = d.Store(replace(self.config, mode='secure'))
        with self.assertRaises(d.DraftError): secure.get(result['draft_id'])
        self.service.config = replace(self.config, mode='secure')
        with self.assertRaises(d.DraftError): self.service.save_basic(result['draft_id'], result['confirmation'])
        self.assertEqual(self.fake.append_count, 0)

    def test_expired_and_tampered_draft_refused(self):
        result = self.prepare()
        with patch.object(d.time, 'time', return_value=time.time()+d.TTL+1), self.assertRaises(d.DraftError):
            self.service.save_basic(result['draft_id'], result['confirmation'])
        with self.service.store.db() as db:
            db.execute('UPDATE drafts SET raw=?', (b'tampered',)); db.commit()
        with self.assertRaises(d.DraftError): self.service.save_basic(result['draft_id'], result['confirmation'])
        self.assertEqual(self.fake.append_count, 0)

    def test_uncertain_append_and_readback_never_retry(self):
        for flag in ('raise_append', 'rewrite'):
            with self.subTest(flag=flag):
                result = self.prepare(); setattr(self.fake, flag, True)
                before = self.fake.append_count
                saved = self.service.save_basic(result['draft_id'], result['confirmation'])
                self.assertEqual(saved['status'], 'uncertain')
                self.assertFalse(saved['retry_allowed'])
                self.service.save_basic(result['draft_id'], result['confirmation'])
                self.assertEqual(self.fake.append_count, before+1)
                setattr(self.fake, flag, False)

    def test_validation_source_and_destination_guards(self):
        for changes in ({'to': ['invalid']}, {'subject': 'bad\r\nheader'}, {'body': 'bad\x00'}):
            with self.assertRaises(d.DraftError): self.prepare(**changes)
        result = self.prepare()
        with patch.object(r, 'fetch_message', return_value=b'changed'), self.assertRaises(d.DraftError):
            self.service.save_basic(result['draft_id'], result['confirmation'])
        self.fake.validity += 1
        with self.assertRaises(d.DraftError): self.service.save_basic(result['draft_id'], result['confirmation'])
        self.assertEqual(self.fake.append_count, 0)

    def test_tools_are_exclusive_and_reader_unchanged(self):
        async def check():
            with patch.object(d.Config, 'load', return_value=self.config):
                tools = {t.name: t for t in await r.create_server().list_tools()}
            self.assertEqual(len(tools), 7)
            self.assertIn('save_draft', tools); self.assertNotIn('save_approved_draft', tools)
            self.assertEqual(set(tools['save_draft'].inputSchema['required']), {'draft_id', 'confirmation'})
            self.assertFalse(tools['save_draft'].annotations.readOnlyHint)
            self.assertTrue(tools['read_message'].annotations.readOnlyHint)
            with patch.object(d.Config, 'load', return_value=replace(self.config, mode='secure')):
                names = {t.name for t in await r.create_server().list_tools()}
            self.assertIn('save_approved_draft', names); self.assertNotIn('save_draft', names)
        asyncio.run(check())

    def test_rejection_and_cross_draft_confirmation_refused(self):
        first, second = self.prepare(), self.prepare(body='Different message')
        with self.assertRaises(d.DraftError): self.service.save_basic(first['draft_id'], second['confirmation'])
        self.service.store.decide(first['draft_id'], first['approval_fingerprint'], 'rejected', {'method': 'terminal'})
        with self.assertRaises(d.DraftError): self.service.save_basic(first['draft_id'], first['confirmation'])
        self.assertEqual(self.fake.append_count, 0)

    def test_concurrent_requests_cannot_duplicate_append(self):
        from concurrent.futures import ThreadPoolExecutor
        result = self.prepare()
        def save():
            try: return self.service.save_basic(result['draft_id'], result['confirmation'])
            except d.DraftError: return {'status': 'refused'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: save(), range(2)))
        self.assertEqual(self.fake.append_count, 1)
        self.assertTrue(any(x['status'] == 'saved' for x in results))

    def test_actual_mcp_basic_tool_schema_and_invalid_call(self):
        import sys
        from pathlib import Path
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def run():
            params = StdioServerParameters(command=sys.executable, args=[str(Path(r.__file__).resolve())], env={
                'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_DRAFT_MODE': 'basic',
                'INBOXTETHER_BASIC_ACK': 'I_ACCEPT_CLIENT_CONTROLLED_APPROVAL',
                'INBOXTETHER_DRAFTS_FOLDER': 'Drafts', 'INBOXTETHER_DRAFT_STATE_DIR': str(self.directory)})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = {t.name: t for t in (await session.list_tools()).tools}
                    self.assertIn('save_draft', tools); self.assertNotIn('save_approved_draft', tools)
                    result = await session.call_tool('save_draft', {'draft_id': '0'*64, 'confirmation': {}})
                    self.assertTrue(result.isError)
        asyncio.run(run())
