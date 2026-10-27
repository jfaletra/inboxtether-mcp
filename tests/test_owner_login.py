"""Synthetic owner credentials only: dedicated login -> exact approval -> execution."""
import asyncio,copy,hashlib,json,os,re,time,unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch
import httpx
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from enroll_owner import make_record,write_record
from owner_login import LocalConfig,LoginState,credentials,create_app,AUTH_COOKIE,LOGIN_COOKIE,TTL
from test_move_integration import Fixture,ORIGIN,WEB,READER
from journal import Refused

OWNER={'kind':'local-owner','id':'c'*32}
PASSWORD='synthetic-owner-passphrase-only'
class LocalFixture(Fixture,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner_file=(self.root/'owner.json').resolve()
        self.record=make_record(OWNER['id'],'owner',PASSWORD);write_record(self.owner_file,self.record,os.geteuid())
        self.config=LocalConfig(ORIGIN,OWNER['id'],self.owner_file,self.root/'broker.sock',self.root/'web.sock',b'c'*32)
        self.service.owner=OWNER;self.service.approval_method='browser-password-session';self.broker.owner=OWNER
        broker=self.broker
        class Local:
            def call(self,operation,key,principal,**fields):return broker.dispatch({'operation':operation,'draft_id':key,'principal':principal,**fields},WEB)
        self.transport=Local();self.app=create_app(self.config,self.transport,clock=lambda:self.now)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url=ORIGIN)
    async def asyncTearDown(self):await self.client.aclose()
    async def post(self,path,fields,origin=ORIGIN):return await self.client.post(path,content=urlencode(fields),headers={'origin':origin,'content-type':'application/x-www-form-urlencoded'})
    def token(self,r):return re.search('name="csrf" value="([^"]+)"',r.text)[1]
    async def login(self,password=PASSWORD,username='owner',batch=''):
        r=await self.client.get('/login'+('?batch='+batch if batch else ''))
        return await self.post('/login',{'username':username,'password':password,'batch':batch,'csrf':self.token(r)})
class OwnerLoginTests(LocalFixture):
    async def test_complete_owner_login_approval_execution(self):
        b=self.batch();r=await self.login(batch=b['batch_id']);self.assertEqual(r.status_code,303)
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['state'],'prepared')
        with self.assertRaises(Refused):self.execute(b)
        r=await self.client.get('/review/'+b['batch_id']);self.assertEqual(r.status_code,200)
        proof=re.search('name="decision" value="approved".*?name="csrf" value="([^"]+)"',r.text)[1]
        r=await self.post('/review/'+b['batch_id'],{'decision':'approved','csrf':proof});self.assertEqual(r.status_code,200)
        v=self.execute(b);self.assertEqual(v['state'],'completed');self.assertEqual(v['approval']['method'],'browser-password-session')
        with self.assertRaises(Refused):self.execute(b)
    async def test_wrong_password_and_username(self):
        for username,password in (('owner','wrong'),('someone',PASSWORD)):
            r=await self.login(username=username,password=password);self.assertEqual(r.status_code,403)
        self.assertEqual(self.app.state.owner_login.sessions,{})
    async def test_throttle_is_global_per_owner_not_forwarded_ip(self):
        for _ in range(5):self.assertEqual((await self.login(password='wrong')).status_code,403)
        with patch.object(LoginState,'verify_password',side_effect=AssertionError('No further hashing')):
            self.assertEqual((await self.login()).status_code,429)
        self.now+=61;self.assertEqual((await self.login()).status_code,303)
    async def test_expiry_is_absolute_not_refreshed_by_use(self):
        await self.login();b=self.batch();self.now+=899
        self.assertEqual((await self.client.get('/review/'+b['batch_id'])).status_code,200)
        self.now+=1;r=await self.client.get('/review/'+b['batch_id']);self.assertEqual(r.status_code,303);self.assertTrue(r.headers['location'].startswith('/login'))
    async def test_logout_invalidates_copied_cookie_and_replay(self):
        await self.login();token=self.client.cookies.get(AUTH_COOKIE);r=await self.client.get('/');proof=self.token(r)
        r=await self.post('/logout',{'csrf':proof});self.assertEqual(r.status_code,303)
        self.client.cookies.set(AUTH_COOKIE,token,domain='review.example.org',path='/')
        self.assertEqual((await self.client.get('/')).status_code,303)
        self.assertEqual((await self.post('/logout',{'csrf':proof})).status_code,403)
    async def test_restart_invalidates_all_sessions(self):
        await self.login();self.assertTrue(self.app.state.owner_login.sessions)
        restarted=create_app(self.config,self.transport,clock=lambda:self.now)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url=ORIGIN,cookies=self.client.cookies) as client:
            self.assertEqual((await client.get('/')).status_code,303)
    async def test_password_change_invalidates_session_and_old_password(self):
        await self.login();record=make_record(OWNER['id'],'owner','synthetic-new-password-only')
        write_record(self.owner_file,record,os.geteuid(),replace=True)
        self.assertEqual((await self.client.get('/')).status_code,303)
        self.assertEqual((await self.login()).status_code,403)
        self.assertEqual((await self.login(password='synthetic-new-password-only')).status_code,303)
    async def test_login_csrf_missing_forged_cross_origin_and_replay(self):
        r=await self.client.get('/login');proof=self.token(r);v={'username':'owner','password':PASSWORD,'batch':'','csrf':proof}
        self.assertEqual((await self.post('/login',v,origin='https://evil.invalid')).status_code,403)
        self.assertEqual((await self.post('/login',{**v,'csrf':'forged'})).status_code,403)
        self.assertEqual((await self.post('/login',v)).status_code,403)
        self.assertEqual(self.app.state.owner_login.sessions,{})
    async def test_review_csrf_and_login_do_not_approve(self):
        b=self.batch();await self.login()
        for origin in (ORIGIN,'https://evil.invalid'):
            r=await self.post('/review/'+b['batch_id'],{'decision':'approved','csrf':'forged'},origin=origin);self.assertEqual(r.status_code,409)
        self.assertEqual(self.call('status',{'batch_id':b['batch_id']})['state'],'prepared')
    async def test_form_cannot_be_reused_in_other_session(self):
        b=self.batch();await self.login();r=await self.client.get('/review/'+b['batch_id']);proof=self.token(r)
        previous=self.client.cookies.get(AUTH_COOKIE);await self.login();self.assertNotEqual(self.client.cookies.get(AUTH_COOKIE),previous)
        self.assertEqual((await self.post('/review/'+b['batch_id'],{'decision':'approved','csrf':proof})).status_code,409)
    async def test_approval_csrf_bound_to_exact_batch(self):
        b=self.batch();await self.login();r=await self.client.get('/review/'+b['batch_id']);proof=self.token(r)
        self.now+=1801;fresh=self.call('prepare',{'uids':[1]});await self.login()
        self.assertEqual((await self.post('/review/'+fresh['batch_id'],{'decision':'approved','csrf':proof})).status_code,409)
    async def test_client_cannot_choose_owner_or_claim_password_approval(self):
        b=self.batch()
        for fields in ({'approved':True},{'principal':OWNER},{'method':'browser-password-session'}):
            with self.assertRaises(Refused):self.call('execute',{'batch_id':b['batch_id'],**fields})
        with self.assertRaises(Refused):self.decide(b,uid=READER,principal=OWNER)
    async def test_secure_cookie_and_no_plaintext_or_raw_session_in_state(self):
        r=await self.login();header=r.headers.get('set-cookie','')
        for s in ('Secure','HttpOnly','SameSite=strict','Max-Age=900','Path=/'):self.assertIn(s,header)
        self.assertNotIn(PASSWORD,self.owner_file.read_text());self.assertNotIn(self.client.cookies.get(AUTH_COOKIE),str(self.app.state.owner_login.sessions))
    async def test_no_open_redirect_or_owner_change(self):
        self.assertEqual((await self.client.get('/login?batch=https://evil.invalid')).status_code,403)
        bad={**self.record,'owner_id':'d'*32};self.owner_file.write_text(json.dumps(bad))
        self.assertEqual((await self.client.get('/login')).status_code,403)
    async def test_duplicate_session_cookies_rejected(self):
        await self.login();r=await self.client.get('/',headers={'cookie':AUTH_COOKIE+'=a; '+AUTH_COOKIE+'=b'});self.assertEqual(r.status_code,303)
    async def test_simultaneous_hash_attempts_are_throttled(self):
        import threading
        entered=threading.Event();release=threading.Event();original=LoginState.verify_password
        def wait(*args):entered.set();release.wait(2);return original(*args)
        with patch.object(LoginState,'verify_password',side_effect=wait):
            task=asyncio.create_task(self.login());await asyncio.to_thread(entered.wait,1)
            r=await self.login();self.assertEqual(r.status_code,429);release.set();self.assertEqual((await task).status_code,303)
    async def test_password_changed_during_hashing_cannot_create_old_session(self):
        original=LoginState.verify_password
        def change(*args):
            result=original(*args);record=make_record(OWNER['id'],'owner','replacement-synthetic-only')
            write_record(self.owner_file,record,os.geteuid(),replace=True);return result
        with patch.object(LoginState,'verify_password',side_effect=change):self.assertEqual((await self.login()).status_code,403)
        self.assertFalse(self.app.state.owner_login.sessions)

class EnrollmentTests(unittest.TestCase):
    def test_hashes_salted_and_not_plaintext(self):
        a=make_record(OWNER['id'],'owner',PASSWORD);b=make_record(OWNER['id'],'owner',PASSWORD)
        self.assertNotEqual(a['password_hash'],b['password_hash']);Argon2id.verify_phc_encoded(PASSWORD.encode(),a['password_hash'])
        self.assertNotIn(PASSWORD,json.dumps(a))
    def test_short_password_rejected(self):
        with self.assertRaises(Refused):make_record(OWNER['id'],'owner','short')

class PrefixTests(LocalFixture):
    async def test_deployed_prefix_login_review_logout_without_mailcow_routes(self):
        from dataclasses import replace
        config=replace(self.config,path_prefix='/inboxtether')
        self.app=create_app(config,self.transport,clock=lambda:self.now)
        await self.client.aclose();self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url=ORIGIN)
        self.service.review_path_prefix='/inboxtether'
        b=self.batch();self.assertEqual(b['review_url'],ORIGIN+'/inboxtether/review/'+b['batch_id'])
        r=await self.client.get('/inboxtether/login?batch='+b['batch_id']);self.assertIn('action="/inboxtether/login"',r.text)
        r=await self.post('/inboxtether/login',{'username':'owner','password':PASSWORD,'batch':b['batch_id'],'csrf':self.token(r)})
        self.assertEqual(r.headers['location'],'/inboxtether/review/'+b['batch_id'])
        r=await self.client.get(r.headers['location']);self.assertEqual(r.status_code,200);self.assertIn('action="/inboxtether/logout"',r.text)
        self.assertEqual((await self.client.get('/login')).status_code,404)

class CredentialFileTests(LocalFixture):
    async def test_insecure_file_permissions_and_symlink_refused(self):
        self.owner_file.chmod(0o644)
        with self.assertRaises((Refused,OSError)):credentials(self.config)
        self.owner_file.chmod(0o600);target=self.owner_file.with_name('saved.json');self.owner_file.rename(target);self.owner_file.symlink_to(target)
        with self.assertRaises((Refused,OSError)):credentials(self.config)
    async def test_enrollment_never_silently_overwrites_or_changes_owner(self):
        with self.assertRaises(Refused):write_record(self.owner_file,self.record,os.geteuid())
        different={**self.record,'owner_id':'f'*32}
        with self.assertRaises(Refused):write_record(self.owner_file,different,os.geteuid(),replace=True)
    async def test_temporarily_unreadable_credentials_revoke_existing_session(self):
        await self.login();self.owner_file.chmod(0o644)
        self.assertEqual((await self.client.get('/')).status_code,303)
        self.owner_file.chmod(0o600)
        self.assertEqual((await self.client.get('/')).status_code,303)

class ConfigurationTests(LocalFixture):
    async def test_production_config_load_and_local_factory_need_no_oidc(self):
        from move_web import app
        csrf_file=(self.root/'csrf.bin').resolve();csrf_file.write_bytes(b'x'*32);csrf_file.chmod(0o600)
        values={'origin':ORIGIN,'owner_id':OWNER['id'],'owner_file':str(self.owner_file),'broker_socket':str(self.config.broker_socket),'web_socket':str(self.config.web_socket),'csrf_key_file':str(csrf_file),'path_prefix':'/inboxtether'}
        with patch.dict(os.environ,{'INBOXTETHER_OWNER_CONFIG':'/synthetic/config.json'}),patch('organizer.runtime.load_protected_json',return_value=values),patch('approval_web.OIDCVerifier',side_effect=AssertionError('No OIDC')):
            config=LocalConfig.load();application=app(config,broker=self.transport)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url=ORIGIN) as c:
                self.assertEqual((await c.get('/inboxtether/login')).status_code,200)
    async def test_web_socket_directory_survives_service_restart_for_container_mount(self):
        text=(Path(__file__).resolve().parents[1]/'examples/inboxtether-approval-web.service').read_text()
        self.assertIn('RuntimeDirectoryPreserve=yes',text)
