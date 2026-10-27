"""Synthetic HTTP/OIDC/Unix-IPC approval tests; no mailbox or identity-provider calls."""
import asyncio
from dataclasses import replace
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import approval_broker as b
import approval_web as w
import draft_assistant as d
from test_draft_assistant import DraftFixture

ORIGIN = 'https://review.example.com'
ISSUER = 'https://identity.example.com'
SUBJECT = 'owner-subject'
AUDIENCE = 'inboxtether-review'
PRINCIPAL = {'issuer': ISSUER, 'subject': SUBJECT}


class BrowserFixture(DraftFixture):
    @classmethod
    def setUpClass(cls):
        cls.signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        super().setUp()
        previous = logging.getLogger('httpx').level
        logging.getLogger('httpx').setLevel(logging.WARNING)
        self.addCleanup(logging.getLogger('httpx').setLevel, previous)
        self.config = replace(self.config, approval_owner=(ISSUER, SUBJECT), review_origin=ORIGIN)
        self.service.config = self.config
        self.service.store = d.Store(self.config)
        self.broker = b.Broker(self.config, os.geteuid())  # Same-UID fixture only; production launcher refuses it.
        self.web_config = w.WebConfig(ORIGIN, ISSUER, AUDIENCE, SUBJECT, ISSUER+'/keys',
                                      self.directory/'broker.sock', self.directory/'web.sock', secrets.token_bytes(32))
        self.verifier = w.OIDCVerifier(self.web_config)
        self.verifier.keys = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=self.signing.public_key()))
        broker = self.broker
        class LocalTransport:
            def call(self, operation, key, principal, **fields):
                return broker.dispatch({'operation': operation, 'draft_id': key, 'principal': principal, **fields}, os.geteuid())
        self.transport = LocalTransport()
        self.app = w.create_app(self.web_config, self.verifier, self.transport)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN)
        self.authorization = 'Bearer '+self.token()
        self.client.headers['authorization'] = self.authorization

    def token(self, **changes):
        claims = {'iss': ISSUER, 'sub': SUBJECT, 'aud': AUDIENCE, 'iat': int(time.time())-1,
                  'exp': int(time.time())+1800}
        claims.update(changes)
        return jwt.encode(claims, self.signing, algorithm='RS256', headers={'kid': 'fixture'})

    def form(self, response, decision='approved'):
        match = re.search('name="decision" value="'+decision+'".*?name="csrf" value="([^"]+)"', response.text)
        self.assertIsNotNone(match)
        return {'decision': decision, 'csrf': match[1]}

    async def post(self, key, form, **kwargs):
        headers = {'origin': ORIGIN, 'content-type': 'application/x-www-form-urlencoded'}
        headers.update(kwargs.pop('headers', {}))
        return await self.client.post('/review/'+key, content=urlencode(form), headers=headers, **kwargs)


class BrowserTests(BrowserFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_complete_review_explicit_approval_then_exact_save(self):
        result = self.prepare(body='Hello <script>alert(1)</script>\nFull reply.', cc=['copy@example.com'])
        key = result['draft_id']
        self.assertEqual(result['review_url'], ORIGIN+'/review/'+key)
        response = await self.client.get('/review/'+key)
        self.assertEqual(response.status_code, 200)
        for value in ('recipient@example.com', 'blind@example.com', 'copy@example.com', 'Re: Parent',
                      'Full reply.', 'Untrusted original.', 'Drafts', 'INBOX', '123', '321'):
            self.assertIn(value, response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertNotIn('<script>', response.text)
        self.assertNotIn('\\u000d', response.text)
        self.assertEqual(self.service.store.get(key)['state'], 'pending')
        self.assertEqual(self.fake.append_count, 0)
        response = await self.post(key, self.form(response))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Approval recorded', response.text)
        self.assertEqual(self.fake.append_count, 0)  # Portal cannot touch IMAP.
        saved = self.service.save(key)
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['sha256'], result['mime_sha256'])
        self.assertEqual(self.fake.append_count, 1)
        with self.service.store.db() as db:
            row = db.execute('SELECT actor FROM decisions WHERE draft_id=?', (key,)).fetchone()
        self.assertEqual(json.loads(row[0]), {'method': 'browser-oidc-session', **PRINCIPAL})

    async def test_changed_stored_content_cannot_be_approved(self):
        key = self.prepare()['draft_id']
        form = self.form(await self.client.get('/review/'+key))
        with self.service.store.db() as db:
            db.execute('UPDATE drafts SET raw=? WHERE id=?', (b'changed', key)); db.commit()
        self.assertEqual((await self.post(key, form)).status_code, 409)
        self.assertEqual(self.fake.append_count, 0)

    async def test_real_worker_private_socket_and_http_review(self):
        import uvicorn
        runtime = self.directory/'web-runtime'; runtime.mkdir(mode=0o750)
        path = runtime/'web.sock'
        with w.private_listener(path) as listener:
            worker = uvicorn.Server(uvicorn.Config(self.app, proxy_headers=False, access_log=False,
                                                   log_level='critical', server_header=False))
            task = asyncio.create_task(worker.serve(sockets=[listener]))
            try:
                for _ in range(100):
                    if worker.started: break
                    await asyncio.sleep(.01)
                self.assertTrue(worker.started)
                async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(path)),
                        base_url='http://review.example.com', headers={'authorization': self.authorization}) as client:
                    # Private proxy-to-worker IPC is HTTP; the public browser hop is HTTPS.
                    key = self.prepare()['draft_id']
                    response = await client.get('/review/'+key)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('Untrusted original.', response.text)
                self.assertEqual(path.stat().st_mode & 0o777, 0o660)
            finally:
                worker.should_exit = True
                await asyncio.wait_for(task, timeout=3)

    async def test_security_headers_and_cookie(self):
        key = self.prepare()['draft_id']
        response = await self.client.get('/review/'+key)
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertIn("script-src 'none'", response.headers['content-security-policy'])
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        cookie = response.headers['set-cookie']
        for field in ('__Host-', 'Secure', 'HttpOnly', 'SameSite=strict', 'Path=/'):
            self.assertIn(field, cookie)
        self.assertNotIn('Domain=', cookie)
        self.assertNotIn(self.authorization, response.text)
        self.assertNotIn(self.authorization[7:], str(response.headers))

    async def test_forged_identity_headers_cannot_read(self):
        key = self.prepare()['draft_id']
        self.client.headers.pop('authorization')
        with patch.object(self.transport, 'call') as backend:
            response = await self.client.get('/review/'+key, headers={'x-forwarded-user': SUBJECT, 'x-auth-request-user': SUBJECT})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('recipient@example.com', response.text)
            backend.assert_not_called()

    async def test_wrong_identity_audience_signature_expiry_and_missing_claims(self):
        key = self.prepare()['draft_id']
        tokens = [self.token(sub='other-subject'), self.token(iss='https://other.example.com'),
                  self.token(aud='other-client'), self.token(exp=int(time.time())-1),
                  self.token(iat=int(time.time())+100), self.token(sub=None),
                  self.token(aud=[AUDIENCE]), self.token(azp='other-client'),
                  jwt.encode({'iss': ISSUER, 'sub': SUBJECT, 'aud': AUDIENCE}, self.signing, algorithm='RS256'),
                  jwt.encode({'iss': ISSUER, 'sub': SUBJECT, 'aud': AUDIENCE}, 'synthetic-fixture-key'*2, algorithm='HS256')]
        forged = self.token().split('.')
        forged[2] = 'A'*len(forged[2]); tokens.append('.'.join(forged))
        for token in tokens:
            response = await self.client.get('/review/'+key, headers={'authorization': 'Bearer '+token})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('recipient@example.com', response.text)
        self.assertEqual(self.service.store.get(key)['state'], 'pending')

    async def test_csrf_missing_wrong_session_tampered_cross_origin_and_extra_content(self):
        key = self.prepare()['draft_id']
        response = await self.client.get('/review/'+key)
        form = self.form(response)
        for changed, headers in [({'decision': 'approved'}, {}),
                                 ({**form, 'csrf': form['csrf']+'A'}, {}),
                                 (form, {'origin': 'https://evil.example.com'}),
                                 (form, {'origin': 'null'}), (form, {'sec-fetch-site': 'cross-site'}),
                                 ({**form, 'body': 'changed'}, {}),
                                 ({**form, 'decision': 'rejected'}, {})]:
            with self.subTest(headers=headers):
                result = await self.post(key, changed, headers=headers)
                self.assertEqual(result.status_code, 409)
        self.client.cookies.clear()
        self.assertEqual((await self.post(key, form)).status_code, 409)
        self.assertEqual(self.service.store.get(key)['state'], 'pending')

    async def test_replay_and_rejection_block_writes(self):
        key = self.prepare()['draft_id']
        response = await self.client.get('/review/'+key)
        form = self.form(response, 'rejected')
        self.assertEqual((await self.post(key, form)).status_code, 200)
        self.assertEqual((await self.post(key, form)).status_code, 409)
        with self.assertRaises(d.DraftError):
            self.service.save(key)
        key2 = self.prepare()['draft_id']
        form2 = self.form(await self.client.get('/review/'+key2))
        self.assertEqual((await self.post(key2, form2)).status_code, 200)
        self.assertEqual((await self.post(key2, form2)).status_code, 409)
        self.assertEqual(self.fake.append_count, 0)

    async def test_token_bound_to_draft_and_authenticated_session(self):
        one, two = self.prepare()['draft_id'], self.prepare(body='A different reply')['draft_id']
        form = self.form(await self.client.get('/review/'+one))
        self.assertEqual((await self.post(two, form)).status_code, 409)
        self.client.headers['authorization'] = 'Bearer '+self.token(jti='new-login-session')
        self.assertEqual((await self.post(one, form)).status_code, 409)
        self.assertEqual(self.service.store.get(one)['state'], 'pending')

    async def test_expired_form_and_draft_are_denied(self):
        key = self.prepare()['draft_id']
        form = self.form(await self.client.get('/review/'+key))
        now = time.time()
        with patch.object(w.time, 'time', return_value=now+301):
            self.assertEqual((await self.post(key, form)).status_code, 409)
        with patch.object(w.time, 'time', return_value=now+d.TTL+1):
            self.assertEqual((await self.client.get('/review/'+key)).status_code, 409)

    async def test_wrong_host_duplicate_headers_and_query_refused(self):
        key = self.prepare()['draft_id']
        for headers in ({'host': 'evil.example.com'},
                        [('host', 'review.example.com'), ('authorization', self.authorization), ('authorization', self.authorization)]):
            response = await self.client.get('/review/'+key, headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertEqual((await self.client.get('/review/'+key+'?body=synthetic')).status_code, 403)
        self.assertEqual((await self.client.get('/unknown')).status_code, 404)

    async def test_post_requires_origin_and_bounds_body(self):
        key = self.prepare()['draft_id']
        form = self.form(await self.client.get('/review/'+key))
        no_origin = await self.client.post('/review/'+key, data=form)
        self.assertEqual(no_origin.status_code, 409)
        response = await self.client.post('/review/'+key, content='x'*8193,
                    headers={'origin': ORIGIN, 'content-type': 'application/x-www-form-urlencoded'})
        self.assertEqual(response.status_code, 409)
        duplicate = urlencode(form)+'&decision=approved'
        response = await self.client.post('/review/'+key, content=duplicate,
                    headers={'origin': ORIGIN, 'content-type': 'application/x-www-form-urlencoded'})
        self.assertEqual(response.status_code, 409)

    async def test_no_private_exception_or_request_logging(self):
        key = self.prepare()['draft_id']
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr), patch.object(self.transport, 'call', side_effect=RuntimeError('synthetic private mail')):
            response = await self.client.get('/review/'+key)
        self.assertNotIn('synthetic private mail', response.text+stdout.getvalue()+stderr.getvalue())
        self.assertEqual(response.status_code, 409)

    async def test_real_unix_ipc_http_approval_round_trip(self):
        runtime = self.directory/'runtime'; runtime.mkdir(mode=0o750)
        path = runtime/'broker.sock'
        server = self.broker.server(path)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            app = w.create_app(self.web_config, self.verifier, b.BrokerClient(path))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                        headers={'authorization': self.authorization}) as client:
                key = self.prepare()['draft_id']
                response = await client.get('/review/'+key)
                self.assertEqual(response.status_code, 200)
                response = await client.post('/review/'+key, data=self.form(response), headers={'origin': ORIGIN})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.service.save(key)['status'], 'saved')
            self.assertEqual(path.stat().st_mode & 0o777, 0o660)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)


class BrokerGuardTests(BrowserFixture, unittest.TestCase):
    def tearDown(self):
        asyncio.run(self.client.aclose())

    def test_peer_principal_scope_and_operation_are_enforced(self):
        key = self.prepare()['draft_id']
        request = {'operation': 'review', 'draft_id': key, 'principal': PRINCIPAL}
        for data, uid in [(request, os.geteuid()+1), ({**request, 'principal': {'issuer': ISSUER, 'subject': 'other'}}, os.geteuid()),
                          ({**request, 'operation': 'save'}, os.geteuid()), ({**request, 'approved': True}, os.geteuid())]:
            with self.assertRaises(d.DraftError):
                self.broker.dispatch(data, uid)
        other = replace(self.config, approval_owner=(ISSUER, 'other'))
        with self.assertRaises(d.DraftError):
            d.Store(other).get(key)

    def test_kernel_peer_credential_and_untrusted_wire_rejection(self):
        local, peer = socket.socketpair()
        try:
            self.assertEqual(b.peer_uid(local), os.geteuid())
        finally:
            local.close(); peer.close()
        runtime = self.directory/'runtime'; runtime.mkdir(mode=0o750)
        server = b.Broker(self.config, os.geteuid()+1).server(runtime/'broker.sock')
        thread = threading.Thread(target=server.handle_request, daemon=True); thread.start()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(runtime/'broker.sock'))
                self.assertEqual(b.receive(connection), {'ok': False})
        finally:
            thread.join(timeout=3); server.server_close()

    def test_terminal_admin_fallback_and_owner_change(self):
        key = self.prepare()['draft_id']; item = self.service.store.get(key)
        class Terminal(io.StringIO):
            def isatty(self): return True
        d.approve_interactively(self.service, key, Terminal('APPROVE '+item['fingerprint']+'\n'), Terminal())
        self.assertEqual(self.service.save(key)['status'], 'saved')
        with self.service.store.db() as db:
            actor = json.loads(db.execute('SELECT actor FROM decisions WHERE draft_id=?', (key,)).fetchone()[0])
        self.assertEqual(actor['method'], 'terminal')
        other = replace(self.config, approval_owner=(ISSUER, 'other-subject'))
        with self.assertRaises(d.DraftError): d.Store(other).get(key)

    def test_private_key_modes_size_symlink_and_config_off(self):
        path = self.directory/'csrf.bin'; path.write_bytes(secrets.token_bytes(32)); path.chmod(0o600)
        self.assertEqual(len(w.private_key(path)), 32)
        path.chmod(0o644)
        with self.assertRaises(d.DraftError): w.private_key(path)
        path.chmod(0o600); path.write_bytes(b'short')
        with self.assertRaises(d.DraftError): w.private_key(path)
        link = self.directory/'link'; link.symlink_to(path)
        with self.assertRaises(OSError): w.private_key(link)
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(d.DraftError): w.WebConfig.load()

    def test_browser_config_requires_explicit_owner_origin_and_no_content_url(self):
        env = {'INBOXTETHER_DRAFT_ASSISTANT': '1', 'INBOXTETHER_BROWSER_APPROVAL': '1',
               'INBOXTETHER_DRAFTS_FOLDER': 'Drafts', 'INBOXTETHER_DRAFT_STATE_DIR': str(self.directory),
               'INBOXTETHER_APPROVAL_ISSUER': ISSUER, 'INBOXTETHER_APPROVAL_SUBJECT': SUBJECT,
               'INBOXTETHER_REVIEW_ORIGIN': ORIGIN}
        with patch.dict('os.environ', env):
            cfg = d.Config.load()
            self.assertEqual(cfg.approval_owner, (ISSUER, SUBJECT))
        for origin in ('http://review.example.com', ORIGIN+'/?body=x', ORIGIN+'/review',
                       'https://' + 'user:password@review.example.com', ORIGIN+'#fragment'):
            with patch.dict('os.environ', {**env, 'INBOXTETHER_REVIEW_ORIGIN': origin}), self.assertRaises(d.DraftError):
                d.Config.load()
        url = self.prepare()['review_url']
        self.assertNotIn('recipient', url)
        self.assertRegex(url, r'^https://review\.example\.com/review/[0-9a-f]{64}$')

    def test_concurrent_decisions_only_one_wins(self):
        key = self.prepare()['draft_id']; item = self.service.store.get(key)
        outcomes = []; barrier = threading.Barrier(2)
        def decide(state):
            barrier.wait()
            try:
                self.broker.dispatch({'operation': 'decide', 'draft_id': key, 'principal': PRINCIPAL,
                                      'fingerprint': item['fingerprint'], 'decision': state}, os.geteuid())
                outcomes.append('recorded')
            except d.DraftError: outcomes.append('refused')
        threads = [threading.Thread(target=decide, args=(s,)) for s in ('approved', 'rejected')]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=3)
        self.assertCountEqual(outcomes, ['recorded', 'refused'])

    def test_real_jwks_selection_ignores_token_urls_and_rejects_unknown_key(self):
        verifier = w.OIDCVerifier(self.web_config)
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.signing.public_key(), as_dict=True)
        jwk.update(kid='fixture', alg='RS256', use='sig')
        payload = {'iss': ISSUER, 'sub': SUBJECT, 'aud': AUDIENCE, 'iat': int(time.time())-1,
                   'exp': int(time.time())+300}
        token = jwt.encode(payload, self.signing, algorithm='RS256',
                           headers={'kid': 'fixture', 'jku': 'https://untrusted.example.com/keys'})
        with patch.object(verifier.keys, 'fetch_data', return_value={'keys': [jwk]}) as fetch:
            self.assertEqual(verifier('Bearer '+token), PRINCIPAL)
            self.assertEqual(verifier.keys.uri, self.web_config.jwks_url)
            other = jwt.encode(payload, self.signing, algorithm='RS256', headers={'kid': 'unknown'})
            with self.assertRaises(jwt.PyJWKClientError): verifier('Bearer '+other)
            self.assertGreaterEqual(fetch.call_count, 1)

    def test_production_broker_refuses_same_uid(self):
        with patch.object(b.Config, 'load', return_value=self.config), patch.object(b.pwd, 'getpwnam',
                return_value=SimpleNamespace(pw_uid=os.geteuid())), patch('sys.stderr', io.StringIO()):
            self.assertEqual(b.main(), 1)

    def test_proxy_template_has_secure_session_and_no_auth_bypasses(self):
        import tomllib
        root = Path(d.__file__).parent
        config = tomllib.loads((root/'examples/browser-approval/oauth2-proxy.cfg.example').read_text())
        self.assertTrue(config['cookie_secure'] and config['cookie_httponly'])
        self.assertTrue(config['cookie_name'].startswith('__Host-'))
        self.assertEqual(config['cookie_path'], '/')
        self.assertEqual(config['cookie_expire'], '30m')
        self.assertTrue(config['pass_authorization_header'] and config['skip_auth_strip_headers'])
        self.assertFalse(config['skip_jwt_bearer_tokens'] or config['pass_access_token'])
        self.assertTrue(config['upstreams'][0].startswith('unix://'))
        for key in ('skip_auth_routes', 'skip_auth_regex', 'trusted_ips', 'insecure_oidc_skip_issuer_verification',
                    'ssl_insecure_skip_verify', 'ssl_upstream_insecure_skip_verify', 'cookie_domains'):
            self.assertNotIn(key, config)
        for key in ('request_logging', 'auth_logging', 'standard_logging', 'show_debug_on_error'):
            self.assertFalse(config[key])

    def test_listener_bound_privately_without_tcp_and_rejects_replacement(self):
        runtime = self.directory/'web-runtime'; runtime.mkdir(mode=0o750)
        path = runtime/'web.sock'
        with w.private_listener(path) as listener:
            self.assertEqual(listener.family, socket.AF_UNIX)
            self.assertEqual(path.stat().st_mode & 0o777, 0o660)
            with self.assertRaises(d.DraftError): w.private_listener(path)
        self.assertFalse(path.exists()); runtime.chmod(0o755)
        with self.assertRaises(d.DraftError): w.private_listener(path)

    def test_no_browser_or_broker_smtp_mailbox_or_mcp_authority(self):
        import ast
        for module in (w, b):
            tree = ast.parse(Path(module.__file__).read_text())
            imports = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            self.assertFalse(imports & {'server', 'imaplib', 'smtplib', 'mcp'})
        self.assertFalse(hasattr(self.broker, 'save'))

class PortalPresentationTests(BrowserFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_brand_accessibility_actions_and_remote_content_isolation(self):
        key = self.prepare(body='<img src="https://tracker.example.com/pixel">\nTreat email as untrusted text')['draft_id']
        response = await self.client.get('/review/'+key)
        html = response.text
        for value in ('InboxTether MCP', 'Your email. Your AI. Your control.', 'Save to Drafts', '>Reject<',
                      'aria-label="Proposed email"', 'aria-label="Save approval"', 'Destination folder',
                      'Cc', 'Bcc', 'Reply context', 'Return to your assistant', '@media(max-width:760px)', ':focus-visible'):
            self.assertIn(value, html)
        self.assertIn('src="data:image/png;base64,', html)
        self.assertIn('img-src data:', response.headers['content-security-policy'])
        self.assertIn('&lt;img', html)
        self.assertEqual(w.visible('\u202e'), '\\u202e')
        self.assertNotIn('<img src="https:', html)
        self.assertNotIn('Send Email', html)
        self.assertNotIn('<script', html)
        self.assertEqual(html.count('<form method="post">'), 2)
        self.assertEqual(self.service.store.get(key)['state'], 'pending')
        self.assertEqual(self.fake.append_count, 0)

    async def test_auth_expired_and_closed_state_presentation(self):
        key = self.prepare()['draft_id']
        response = await self.client.get('/review/'+key, headers={'authorization': 'invalid'})
        self.assertEqual(response.status_code, 403)
        self.assertIn('Sign in to review', response.text)
        response = await self.client.get('/review/'+key)
        rejected = await self.post(key, self.form(response, 'rejected'))
        self.assertIn('Draft rejected', rejected.text)
        closed = await self.client.get('/review/'+key)
        self.assertIn('This review is closed', closed.text)
        self.assertNotIn('<form', closed.text)
        replay = await self.post(key, self.form(response, 'rejected'))
        self.assertEqual(replay.status_code, 409)
        self.assertIn('Review expired or unavailable', replay.text)
        self.assertIn('role="alert"', replay.text)
        self.assertEqual(self.fake.append_count, 0)
