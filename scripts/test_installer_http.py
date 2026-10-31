"""Explicit loopback HTTP security tests; no IMAP, privileged setup or real secrets.
Run separately from run_tests.py, whose process deliberately forbids IP sockets.
"""
import http.client,json,sys,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from setup_wizard.__main__ import make_server
from setup_wizard.app import Session
from setup_wizard.model import Secret

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.session=Session(Path(__file__).resolve().parents[1]);self.server=make_server(self.session,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.host='127.0.0.1:'+str(self.server.server_port);self.origin='http://'+self.host
        self.cookie=None;self.csrf=None
        self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(3);self.session.clear()
    def call(self,method,path,value=None,**overrides):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        headers={'Origin':self.origin}
        if value is not None:headers['Content-Type']='application/json'
        if self.cookie:headers['Cookie']=self.cookie
        if self.csrf:headers['X-InboxTether-CSRF']=self.csrf
        headers.update(overrides)
        c.request(method,path,None if value is None else json.dumps(value),headers)
        r=c.getresponse();body=r.read();result=(r.status,dict(r.getheaders()),body);c.close();return result
    def auth(self):
        r,h,b=self.call('POST','/api/session',{'ticket':self.session.bootstrap});self.assertEqual(r,200)
        self.cookie=h['Set-Cookie'].split(';',1)[0];self.csrf=json.loads(b)['csrf'];return h
    def test_no_session_or_cross_site_access(self):
        self.assertEqual(self.call('GET','/api/status')[0],403)
        ticket=self.session.bootstrap
        self.assertEqual(self.call('POST','/api/session',{'ticket':ticket},Origin='https://untrusted.example')[0],400)
        self.assertEqual(self.call('POST','/api/session',{'ticket':ticket},Host='evil.example')[0],400)
        self.assertEqual(self.session.bootstrap,ticket)
        self.auth();self.assertEqual(self.call('POST','/api/client',{'client':'other','location':'local','target':''},Origin='https://untrusted.example')[0],400)
    def test_ticket_replay_cookie_csrf_and_reload(self):
        ticket=self.session.bootstrap;h=self.auth()
        self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
        self.assertEqual(self.call('POST','/api/session',{'ticket':ticket})[0],400)
        self.assertEqual(self.call('POST','/api/session',{})[0],200)
        self.assertEqual(self.call('POST','/api/client',{'client':'other','location':'local','target':''},**{'X-InboxTether-CSRF':'wrong'})[0],400)
        self.assertEqual(self.call('POST','/api/client',{'client':'other','location':'local','target':''})[0],200)
    def test_state_and_client_export_never_reveal_secret(self):
        self.auth();secret='SYNTHETIC-SECRET-NOT-A-LIVE-CREDENTIAL';self.session.reader_secret=Secret(secret)
        for method,path,value in [('GET','/api/status',None),('POST','/api/client',{'client':'claude','location':'local','target':''})]:
            status,headers,body=self.call(method,path,value);self.assertEqual(status,200);self.assertNotIn(secret.encode(),body);self.assertEqual(headers['Cache-Control'],'no-store')
    def test_static_allowlist_and_browser_security_headers(self):
        status,h,body=self.call('GET','/');self.assertEqual(status,200)
        self.assertIn("frame-ancestors 'none'",h['Content-Security-Policy']);self.assertEqual(h['Referrer-Policy'],'no-referrer')
        self.assertNotIn('Access-Control-Allow-Origin',h)
        self.assertEqual(self.call('GET','/../../etc/passwd')[0],404)
    def test_size_guard_and_finish_requires_complete_installation(self):
        self.auth();self.assertEqual(self.call('POST','/api/finish',{})[0],400)
        self.assertEqual(self.call('POST','/api/client',{},**{'Content-Length':'65537'})[0],400)
    def test_finish_revokes_session_and_stops_temporary_listener(self):
        self.auth();self.session.result={'installed':True}
        self.assertEqual(self.call('POST','/api/finish',{})[0],200);self.thread.join(3)
        self.assertFalse(self.thread.is_alive());self.assertIsNone(self.session.cookie)

if __name__=='__main__':unittest.main(verbosity=2)
