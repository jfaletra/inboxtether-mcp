"""Synthetic installer contracts. No production paths, processes or IP sockets."""
import copy,imaplib,json,os,ssl,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from setup_wizard.model import MailSettings,Secret,SetupError,features,fingerprint
from setup_wizard.app import Session
from setup_wizard import probe
from setup_wizard.clients import connection_config
from setup_wizard.install import verify_source,cleanup

MAIL={'host':'mail.example.com','port':1993,'account':'owner@example.com','login':'mailbox-owner'}
PASSWORD='synthetic-mail-secret-only'
OWNER_PASSWORD='synthetic-owner-passphrase-only'
NAMES=['INBOX','Industry','Marketing','Orders','Suppliers','Review','Drafts']
class FakeIMAP:
    rights='lriswte'
    caps=('IMAP4rev1','UIDPLUS','MOVE','ACL')
    draft_flag=True
    fail=None
    seen=[]
    def __init__(self,host,port,**options):
        self.host,self.port=host,port;self.capabilities=self.caps
        assert options['ssl_context'].check_hostname and options['ssl_context'].verify_mode==ssl.CERT_REQUIRED
        self.names=set();type(self).seen.append(('connect',host,port))
    def login(self,login,password):
        type(self).seen.append(('login',login))
        if self.fail=='auth':raise imaplib.IMAP4.error('provider echoed '+password)
        return 'OK',[]
    def list(self,*a):
        rows=[]
        for name in NAMES:
            flags='\\Drafts' if name=='Drafts' and self.draft_flag else '\\HasNoChildren'
            rows.append(('('+flags+') "/" "'+name+'"').encode())
        return 'OK',rows
    def select(self,path,readonly):
        assert readonly is True;type(self).seen.append(('EXAMINE',path));return 'OK',[b'1']
    def response(self,name):return name,[b'12345']
    def myrights(self,path):return 'OK',[(path+' '+self.rights).encode()]
    def shutdown(self):pass

def discovery():
    with patch.object(probe,'SetupIMAP',FakeIMAP):
        return probe.test_reader(MailSettings.parse(MAIL),Secret(PASSWORD),factory=FakeIMAP)

def input_features(organizer=False,drafts=False):
    return {'drafts':drafts,'organizer':organizer,'draft_ack':drafts,'drafts_path':'Drafts',
            'mailboxes':{n:n for n in NAMES if n!='Drafts'},'organizer_login':'owner@example.com+organizer',
            'review_origin':'https://review.example.com','certificate_file':'/etc/ssl/test/server.pem',
            'certificate_key_file':'/etc/ssl/test/server.key','linux_user':'ubuntu','owner_username':'owner'}

class ModelTests(unittest.TestCase):
    def test_port_login_and_safe_defaults(self):
        self.assertEqual(MailSettings.parse(MAIL).login,'mailbox-owner')
        self.assertEqual(MailSettings.parse({**MAIL,'login':''}).login,MAIL['account'])
        self.assertEqual(MailSettings.parse({k:v for k,v in MAIL.items() if k!='port'}).port,993)
        for port in (True,0,65536,'993'):
            with self.subTest(port=port),self.assertRaises(SetupError):MailSettings.parse({**MAIL,'port':port})
    def test_host_injection_and_password_linebreaks_rejected(self):
        for host in ('https://mail.test','mail.test\nINJECT=1','--mail','a..b'):
            with self.subTest(host=host),self.assertRaises(SetupError):MailSettings.parse({**MAIL,'host':host})
        for secret in ('', 'x\ny','x\ry','x\0y'):
            with self.assertRaises(SetupError):Secret(secret)
    def test_secret_clear_and_utf8(self):
        s=Secret('synthetic-é-secret');self.assertEqual(s.text(),'synthetic-é-secret');s.clear()
        self.assertEqual(s.value,bytearray())
        with self.assertRaises(SetupError):s.text()
    def test_reader_is_always_included_and_writes_not_enabled(self):
        f=features(input_features(),discovery()['folders']);self.assertTrue(f['reader']);self.assertFalse(f['drafts']);self.assertFalse(f['organizer'])
    def test_drafts_requires_special_use_and_explicit_acknowledgment(self):
        d=discovery();self.assertEqual(features(input_features(drafts=True),d['folders'])['drafts_path'],'Drafts')
        for value in ({**input_features(drafts=True),'draft_ack':False},{**input_features(drafts=True),'drafts_path':'Industry'}):
            with self.assertRaises(SetupError):features(value,d['folders'])
    def test_organizer_requires_six_distinct_existing_paths(self):
        d=discovery();self.assertEqual(len(features(input_features(organizer=True),d['folders'])['mailboxes']),6)
        for maps in ({'INBOX':'INBOX'}, {n:'INBOX' for n in NAMES if n!='Drafts'}, {n:('Missing' if n=='Industry' else n) for n in NAMES if n!='Drafts'}):
            with self.assertRaises(SetupError):features({**input_features(organizer=True),'mailboxes':maps},d['folders'])
    def test_invalid_origins_and_master_separator_not_silently_changed(self):
        d=discovery()
        for origin in ('http://review.test','https'+':'+'//'+'user'+':'+'pass'+'@review.example.com','https://review.test/path','https://review.test:0'):
            with self.subTest(origin=origin),self.assertRaises(SetupError):features({**input_features(organizer=True),'review_origin':origin},d['folders'])
        with self.assertRaises(SetupError):features({**input_features(organizer=True),'organizer_login':'owner*master'},d['folders'])

class ProbeTests(unittest.TestCase):
    def setUp(self):FakeIMAP.seen=[]
    def test_real_port_username_tls_and_metadata_only(self):
        r=discovery();self.assertTrue(r['tls']);self.assertFalse(r['message_content_read']);self.assertEqual(len(r['folders']),7)
        self.assertIn(('connect','mail.example.com',1993),FakeIMAP.seen);self.assertIn(('login','mailbox-owner'),FakeIMAP.seen)
        self.assertFalse(any(x[0] in ('FETCH','SEARCH','SELECT','MOVE','COPY','STORE','APPEND') for x in FakeIMAP.seen))
    def test_organizer_reuses_exact_adapter_rights_checks(self):
        s=MailSettings.parse(MAIL);d=discovery();f=features(input_features(organizer=True),d['folders'])
        v=probe.validate_features(s,Secret(PASSWORD),f,d,Secret('synthetic-organizer-only'),factory=FakeIMAP)
        self.assertEqual(set(v['mailboxes']),set(NAMES)-{'Drafts'})
        self.assertEqual(v['mailboxes']['INBOX']['uidvalidity'],12345)
        for rights in ('lr','lriswtekxa'):
            with patch.object(FakeIMAP,'rights',rights),self.subTest(rights=rights),self.assertRaises(SetupError) as e:
                probe.validate_features(s,Secret(PASSWORD),f,d,Secret('synthetic-organizer-only'),factory=FakeIMAP)
            self.assertEqual(e.exception.code,'organizer_rights')
    def test_missing_capability_and_non_dedicated_account_fail(self):
        s=MailSettings.parse(MAIL);d=discovery();f=features(input_features(organizer=True),d['folders'])
        with patch.object(FakeIMAP,'caps',('IMAP4rev1','UIDPLUS')),self.assertRaises(SetupError) as e:
            probe.validate_features(s,Secret(PASSWORD),f,d,Secret('synthetic-organizer-only'),factory=FakeIMAP)
        self.assertEqual(e.exception.code,'organizer_capability')
        with self.assertRaises(SetupError):probe.validate_features(s,Secret(PASSWORD),{**f,'organizer_login':s.account},d,Secret('synthetic-only'),factory=FakeIMAP)
    def test_changed_pins_stop(self):
        d=discovery();d['source_uidvalidity']=54321
        with self.assertRaises(SetupError) as e:probe.validate_features(MailSettings.parse(MAIL),Secret(PASSWORD),features(input_features(),d['folders']),d,factory=FakeIMAP)
        self.assertEqual(e.exception.code,'identity_changed')
    def test_authentication_errors_never_echo_credentials(self):
        with patch.object(FakeIMAP,'fail','auth'),self.assertRaises(SetupError) as e:discovery()
        self.assertNotIn(PASSWORD,e.exception.message);self.assertNotIn('provider echoed',e.exception.message)
    def test_tls_error_is_distinguishable_and_not_bypassed(self):
        def fail(*a,**k):raise ssl.SSLCertVerificationError('bad certificate')
        with self.assertRaises(SetupError) as e:probe.test_reader(MailSettings.parse(MAIL),Secret(PASSWORD),factory=fail)
        self.assertEqual(e.exception.code,'tls_certificate')
    def test_probe_protocol_blocks_mutations_at_dispatch(self):
        client=object.__new__(probe.SetupIMAP)
        for command in ('SELECT','UID','APPEND','CREATE','DELETE','STORE','EXPUNGE','COPY'):
            with self.subTest(command=command),self.assertRaises(Exception):client._command(command)

class SessionTests(unittest.TestCase):
    def make(self):
        t=[0.0];s=Session(Path(__file__).parent,clock=lambda:t[0]);cookie,csrf=s.authenticate(s.bootstrap);return s,t,cookie,csrf
    def connect(self,s):
        value=discovery()
        with patch.object(probe,'test_reader',return_value=value):return s.connect({'connection':MAIL,'password':PASSWORD})
    def configure(self,s):
        with patch.object(probe,'validate_features',return_value={'reader_uidvalidity':12345,'mailboxes':{}}):
            return s.configure({'features':input_features(),'organizer_password':'','owner_password':'','owner_confirmation':''})
    def test_bootstrap_single_use_csrf_and_expiry(self):
        s,t,c,csrf=self.make()
        with self.assertRaises(SetupError):s.authenticate('0'*64)
        s.authorize(c,csrf,write=True)
        with self.assertRaises(SetupError):s.authorize(c,'wrong',write=True)
        self.connect(s);secret=s.reader_secret;t[0]=901
        with self.assertRaises(SetupError):s.authorize(c)
        self.assertEqual(secret.value,bytearray())
    def test_public_state_and_plan_contain_no_password(self):
        s,*_=self.make();self.connect(s);p=self.configure(s)
        self.assertNotIn(PASSWORD,json.dumps(p));self.assertNotIn(PASSWORD,json.dumps(s.status()))
        self.assertFalse(p['plan']['execution_enabled']);self.assertFalse(p['plan']['automatic_filing_enabled']);self.assertFalse(p['plan']['client_session_consent'])
    def test_host_changes_never_reuse_secrets(self):
        s,*_=self.make();self.connect(s);prior=s.reader_secret
        with self.assertRaises(SetupError):s.connect({'connection':{**MAIL,'host':'different.test'},'password':''})
        self.assertIsNone(s.settings);self.assertIsNone(s.plan)
        self.assertEqual(prior.value,bytearray())
    def test_install_exact_plan_one_attempt_and_secret_erasure(self):
        s,*_=self.make();self.connect(s);p=self.configure(s);calls=[]
        class Fake:
            def __init__(self,*a,**k):pass
            def install(self):calls.append(1);return {'installed':True,'checks':[]}
        s.provisioner=Fake
        with self.assertRaises(SetupError):s.install({'fingerprint':'0'*64,'confirmation':'INSTALL_SELECTED_FEATURES'})
        self.assertEqual(calls,[])
        s.install({'fingerprint':p['fingerprint'],'confirmation':'INSTALL_SELECTED_FEATURES'});s.job.join(2)
        self.assertEqual(calls,[1]);self.assertIsNone(s.reader_secret)
        with self.assertRaises(SetupError):s.install({'fingerprint':p['fingerprint'],'confirmation':'INSTALL_SELECTED_FEATURES'})
    def test_preparation_alone_has_no_provisioning_side_effect(self):
        s,*_=self.make();self.connect(s);self.configure(s);self.assertIsNone(s.job);self.assertIsNone(s.result)

class PackagingAndClientTests(unittest.TestCase):
    def test_client_exports_are_password_free_and_keep_web_manual(self):
        for client in ('claude','chatgpt-desktop','chatgpt-web','other'):
            result=connection_config(client,'ssh','ubuntu@test-server');self.assertEqual(result['command'],'ssh');self.assertNotIn('env',result['configuration']['mcpServers']['inboxtether'])
            if client=='chatgpt-web':self.assertFalse(result['web_connection_configured'])
        for value in ('-oProxyCommand=evil','a;command','user@host\ncommand'):
            with self.assertRaises(SetupError):connection_config('other','ssh',value)
    def test_recovery_rejects_unrelated_paths_before_service_actions(self):
        s={'schema':1,'status':'failed','services':[],'resources':[{'path':'/etc/passwd'}],'users':[]}
        with patch('setup_wizard.install.subprocess.run') as run,self.assertRaises(SetupError):cleanup(s)
        run.assert_not_called()
    def test_recovery_refuses_complete_installation(self):
        with self.assertRaises(SetupError):cleanup({'schema':1,'status':'complete'})
    def test_source_manifest_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'MANIFEST.sha256').write_text('0'*64+'  ../escape\n')
            with self.assertRaises(SetupError):verify_source(p)

class RuntimeConnectionSettingsTests(unittest.TestCase):
    def test_reader_honors_explicit_login_and_secure_port(self):
        import server
        with patch.object(server,'ReadOnlyIMAP',FakeIMAP),patch.object(server,'password',return_value=PASSWORD),patch.object(server,'PORT',1993),patch.object(server,'LOGIN_ACCOUNT','mailbox-owner'):
            with server.connection() as c:
                self.assertEqual(c.port,1993)
        self.assertIn(('login','mailbox-owner'),FakeIMAP.seen)
    def test_draft_writer_uses_the_same_port_and_login(self):
        import server
        from draft_assistant import DraftService
        service=object.__new__(DraftService);service.reader=server
        with patch.object(server,'DraftAppendIMAP',FakeIMAP),patch.object(server,'password',return_value=PASSWORD),patch.object(server,'PORT',1993),patch.object(server,'LOGIN_ACCOUNT','mailbox-owner'):
            with service.writer() as c:self.assertEqual(c.port,1993)
        self.assertIn(('login','mailbox-owner'),FakeIMAP.seen)
    def test_organizer_port_is_bounded_without_changing_default(self):
        from organizer.imap_adapter import IMAPMailbox
        from organizer.model import OrganizerError
        self.assertEqual(IMAPMailbox('mail.test','owner@test','/synthetic',live_enabled=True).port,993)
        self.assertEqual(IMAPMailbox('mail.test','owner@test','/synthetic',live_enabled=True,port=1993).port,1993)
        for p in (True,0,65536):
            with self.assertRaises(OrganizerError):IMAPMailbox('mail.test','owner@test','/synthetic',live_enabled=True,port=p)

class DesktopConnectorTests(unittest.TestCase):
    @staticmethod
    def module():
        import importlib.util
        source=Path(__file__).resolve().parents[1]/'setup_wizard/web/connect_claude.py'
        spec=importlib.util.spec_from_file_location('synthetic_claude_connector',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    def test_owner_connector_preserves_other_entries_and_is_idempotent(self):
        m=self.module();server={'command':'ssh','args':['-T','-o','BatchMode=yes','ubuntu@example-server','/usr/local/bin/inboxtether']}
        m.validate({'mcpServers':{'inboxtether':server}})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'client.json';prior={'theme':'dark','mcpServers':{'other':{'command':'existing-tool','args':[]}}};p.write_text(json.dumps(prior))
            m.merge(p,server);value=json.loads(p.read_text());self.assertEqual(value['theme'],'dark');self.assertEqual(value['mcpServers']['other'],prior['mcpServers']['other'])
            before=p.read_bytes();m.merge(p,server);self.assertEqual(p.read_bytes(),before)
            self.assertEqual(len(list(p.parent.glob('*.before-inboxtether-*'))),1)
            with self.assertRaises(ValueError):m.merge(p,{'command':'different','args':[]})
            self.assertEqual(p.read_bytes(),before)
    def test_unsafe_client_command_and_symlink_are_rejected(self):
        m=self.module()
        for server in ({'command':'sh','args':['-c','anything']},{'command':'ssh','args':['-oProxyCommand=anything']},{'command':'ssh','args':[],'env':{'PASSWORD':'synthetic-only'}}):
            with self.assertRaises(ValueError):m.validate({'mcpServers':{'inboxtether':server}})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'original').write_text('{}');(p/'link').symlink_to(p/'original')
            with self.assertRaises(ValueError):m.merge(p/'link',{'command':'/usr/local/bin/inboxtether','args':[]})
            self.assertEqual((p/'original').read_text(),'{}')
    def test_generated_connector_source_is_valid_and_contains_only_public_command(self):
        r=Path(__file__).resolve().parents[1];source=(r/'setup_wizard/web/connect_claude.py').read_text()
        config=connection_config('claude','ssh','ubuntu@example-server')['configuration']
        encoded=json.dumps(json.dumps(config));generated=source.replace('"__INBOXTETHER_ENTRY_JSON__"',encoded)
        compile(generated,'synthetic-connector.py','exec');self.assertNotIn('__INBOXTETHER_ENTRY_JSON__',generated)
        self.assertNotIn(PASSWORD,generated)

class AdditionalInstallBoundaryTests(unittest.TestCase):
    def test_reader_login_cannot_double_as_restricted_executor(self):
        d=discovery();f=features(input_features(organizer=True),d['folders'])
        settings=MailSettings.parse({**MAIL,'login':f['organizer_login']})
        with patch.object(probe,'SetupIMAP',FakeIMAP),self.assertRaises(SetupError) as error:
            probe.validate_features(settings,Secret(PASSWORD),f,d,Secret('synthetic-organizer-secret'),factory=FakeIMAP)
        self.assertEqual(error.exception.code,'dedicated_login')
    def test_changed_service_identity_stops_recovery_before_any_system_action(self):
        from types import SimpleNamespace
        state={'schema':1,'status':'failed','services':[],'resources':[],
               'users':[{'name':'inboxtether-reader','uid':1234,'gid':1234}]}
        with patch('setup_wizard.install.pwd.getpwnam',return_value=SimpleNamespace(pw_uid=1235,pw_gid=1234)),patch('setup_wizard.install.subprocess.run') as run,self.assertRaises(SetupError):
            cleanup(state)
        run.assert_not_called()
    def test_changed_service_group_stops_recovery_before_any_system_action(self):
        from types import SimpleNamespace
        state={'schema':1,'status':'failed','services':[],'resources':[],
               'users':[{'name':'inboxtether-reader','uid':1234,'gid':1234}]}
        with patch('setup_wizard.install.pwd.getpwnam',side_effect=KeyError),patch('setup_wizard.install.grp.getgrnam',return_value=SimpleNamespace(gr_gid=1234,gr_mem=['someone'])),patch('setup_wizard.install.subprocess.run') as run,self.assertRaises(SetupError):
            cleanup(state)
        run.assert_not_called()

class TransientFolderStatusTests(unittest.TestCase):
    def test_folder_status_hints_and_list_order_are_not_source_identity(self):
        d=discovery();f=features(input_features(drafts=True),d['folders'])
        class StatusChange(FakeIMAP):
            def list(self,*args):
                status,rows=super().list(*args)
                return status,[r.replace(b'(\\Drafts)',b'(\\UnMarked \\Drafts)') for r in reversed(rows)]
        result=probe.validate_features(MailSettings.parse(MAIL),Secret(PASSWORD),f,d,factory=StatusChange)
        self.assertEqual(result['drafts_uidvalidity'],12345)
    def test_special_use_changes_still_stop_setup(self):
        d=discovery();f=features(input_features(drafts=True),d['folders'])
        class ChangedUse(FakeIMAP):draft_flag=False
        with self.assertRaises(SetupError):probe.validate_features(MailSettings.parse(MAIL),Secret(PASSWORD),f,d,factory=ChangedUse)

class InterruptedIdentityCleanupTests(unittest.TestCase):
    def test_private_group_is_removed_even_if_user_was_already_removed(self):
        from types import SimpleNamespace
        state={'schema':1,'status':'failed','services':[],'resources':[],
               'users':[{'name':'inboxtether-reader','uid':1234,'gid':1234}]}
        with patch('setup_wizard.install.pwd.getpwnam',side_effect=KeyError),patch('setup_wizard.install.grp.getgrnam',return_value=SimpleNamespace(gr_gid=1234,gr_mem=[])),patch('setup_wizard.install.shutil.which',return_value=None),patch('setup_wizard.install.subprocess.run') as run:
            cleanup(state)
        commands=[c.args[0] for c in run.call_args_list]
        self.assertIn(['/usr/sbin/groupdel','inboxtether-reader'],commands)
        self.assertFalse(any(c[0]=='/usr/sbin/userdel' for c in commands))

class DownloadedConnectorTests(unittest.TestCase):
    def test_rendered_claude_download_is_valid_and_contains_only_exact_connection(self):
        template=(Path(__file__).resolve().parents[1]/'setup_wizard/web/connect_claude.py').read_text()
        config={'mcpServers':{'inboxtether':{'command':'ssh','args':['-T','-o','BatchMode=yes','owner@test-server','/usr/local/bin/inboxtether']}}}
        # Equivalent to the browser's double JSON.stringify, for ASCII connection fields.
        rendered=template.replace('"__INBOXTETHER_ENTRY_JSON__"',json.dumps(json.dumps(config)))
        namespace={'__name__':'synthetic_download_only'};exec(compile(rendered,'synthetic-connector','exec'),namespace)
        self.assertEqual(json.loads(namespace['ENTRY_JSON']),config)
        self.assertEqual(namespace['validate'](json.loads(namespace['ENTRY_JSON'])),config['mcpServers']['inboxtether'])
        self.assertNotIn(PASSWORD,rendered);self.assertNotIn(OWNER_PASSWORD,rendered)

class GeneratedResourceRecoveryTests(unittest.TestCase):
    def test_complete_new_application_tree_includes_generated_bytecode(self):
        with tempfile.TemporaryDirectory() as d:
            app=Path(d)/'app';app.mkdir();package=app/'package';package.mkdir();cache=package/'__pycache__';cache.mkdir();(cache/'synthetic.pyc').write_bytes(b'synthetic')
            rows=[]
            for p in (app,package):
                s=p.lstat();rows.append({'path':str(p),'device':s.st_dev,'inode':s.st_ino,'uid':s.st_uid,'directory':True})
            state={'schema':1,'status':'failed','services':[],'resources':rows,'users':[]}
            with patch('setup_wizard.install.APP',app),patch('setup_wizard.install.TARGETS',(app,)),patch('setup_wizard.install.subprocess.run'),patch('setup_wizard.install.shutil.which',return_value=None):cleanup(state)
            self.assertFalse(app.exists())
    def test_already_removed_unit_can_be_confirmed_inactive_during_recovery(self):
        from types import SimpleNamespace
        state={'schema':1,'status':'cleanup_required','services':['inboxtether-approval-web.service'],'resources':[],'users':[]}
        def result(args,**kwargs):return SimpleNamespace(returncode=5 if args[1]=='stop' else 3 if args[1]=='is-active' else 0)
        with patch('setup_wizard.install.subprocess.run',side_effect=result) as run,patch('setup_wizard.install.shutil.which',return_value=None),patch('setup_wizard.install.Path.exists',return_value=False):cleanup(state)
        self.assertTrue(any(c.args[0][1]=='is-active' for c in run.call_args_list))

class FinalWizardUXContractTests(unittest.TestCase):
    def test_error_region_is_programmatically_focusable_and_announced(self):
        from html.parser import HTMLParser
        class Regions(HTMLParser):
            values={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if attrs.get('id')=='error':self.values=attrs
        parser=Regions();parser.feed((Path(__file__).resolve().parents[1]/'setup_wizard/web/index.html').read_text())
        self.assertEqual(parser.values['role'],'alert');self.assertEqual(parser.values['tabindex'],'-1')
        self.assertEqual(parser.values['aria-atomic'],'true')
    def test_claude_instructions_work_independently_of_current_directory(self):
        for location,target in (('local',''),('ssh','owner@test-server')):
            value=connection_config('claude',location,target);steps=' '.join(value['manual_steps'])
            self.assertIn('python3 "$HOME/Downloads/connect_inboxtether_claude.py"',steps)
            self.assertIn('py -3 "$HOME\\Downloads\\connect_inboxtether_claude.py"',steps)
            self.assertIn('actual full quoted path',steps);self.assertIn('containing folder first',steps)
            self.assertNotIn(PASSWORD,json.dumps(value));self.assertNotIn(OWNER_PASSWORD,json.dumps(value))


class CompletedConnectorTests(unittest.TestCase):
    def prepared(self):
        s=Session(Path(__file__).parent)
        with patch.object(probe,'test_reader',return_value=discovery()):
            s.connect({'connection':MAIL,'password':PASSWORD})
        with patch.object(probe,'validate_features',return_value={'reader_uidvalidity':12345,'mailboxes':{}}):
            plan=s.configure({'features':input_features(),'organizer_password':'','owner_password':'','owner_confirmation':''})
        return s,plan

    def test_success_binds_exact_validated_connection_and_does_not_expose_secrets(self):
        s,plan=self.prepared()
        chosen={'client':'claude','location':'ssh','target':'owner@synthetic-server'}
        exported=s.dispatch('/api/client',chosen)
        expected=connection_config(**chosen)
        exported['configuration']['mcpServers']['inboxtether']['args'][3]='changed@other-server'
        class Fake:
            def __init__(self,*a,**kw):pass
            def install(self):return {'installed':True,'checks':[],'features':plan['plan']['features']}
        s.provisioner=Fake
        self.assertIsNone(s.status()['result'])
        s.install({'fingerprint':plan['fingerprint'],'confirmation':'INSTALL_SELECTED_FEATURES'});s.job.join(2)
        self.assertEqual(s.result['client_connection'],expected)
        self.assertNotIn(PASSWORD,json.dumps(s.status()))
        self.assertNotIn(OWNER_PASSWORD,json.dumps(s.status()))
        with self.assertRaises(SetupError):s.dispatch('/api/client',{**chosen,'target':'changed@other-server'})
        self.assertEqual(s.result['client_connection'],expected)

    def test_running_install_has_no_completed_connector_and_cannot_change_choice(self):
        import threading
        s,plan=self.prepared();started=threading.Event();finish=threading.Event()
        s.dispatch('/api/client',{'client':'claude','location':'local','target':''})
        class Fake:
            def __init__(self,*a,**kw):pass
            def install(self):
                started.set();finish.wait(3)
                return {'installed':True,'checks':[]}
        s.provisioner=Fake
        s.install({'fingerprint':plan['fingerprint'],'confirmation':'INSTALL_SELECTED_FEATURES'})
        try:
            self.assertTrue(started.wait(1));self.assertTrue(s.status()['running'])
            self.assertIsNone(s.status()['result'])
            with self.assertRaises(SetupError):s.dispatch('/api/client',{'client':'other','location':'ssh','target':'different-server'})
        finally:finish.set();s.job.join(2)
        self.assertEqual(s.result['client_connection']['command'],'/usr/local/bin/inboxtether')

    def test_failed_install_never_publishes_completed_connector_and_does_not_retry(self):
        s,plan=self.prepared();calls=[]
        s.dispatch('/api/client',{'client':'claude','location':'local','target':''})
        class Fake:
            def __init__(self,*a,**kw):pass
            def install(self):calls.append(1);raise SetupError('synthetic_failure','Synthetic setup failed.')
        s.provisioner=Fake
        s.install({'fingerprint':plan['fingerprint'],'confirmation':'INSTALL_SELECTED_FEATURES'});s.job.join(2)
        self.assertIsNone(s.status()['result']);self.assertEqual(s.error['code'],'synthetic_failure')
        self.assertIsNone(s.reader_secret)
        with self.assertRaises(SetupError):s.install({'fingerprint':plan['fingerprint'],'confirmation':'INSTALL_SELECTED_FEATURES'})
        self.assertEqual(calls,[1])

    def test_reconfiguration_discards_prior_connection_snapshot(self):
        s,plan=self.prepared();s.dispatch('/api/client',{'client':'claude','location':'ssh','target':'prior-server'})
        with patch.object(probe,'validate_features',return_value={'reader_uidvalidity':12345,'mailboxes':{}}):
            s.configure({'features':input_features(),'organizer_password':'','owner_password':'','owner_confirmation':''})
        self.assertIsNone(s.client_connection)

    def test_connector_is_initially_hidden_and_all_export_buttons_are_disabled(self):
        from html.parser import HTMLParser
        class Regions(HTMLParser):
            def __init__(self):super().__init__();self.ids={}
            def handle_starttag(self,tag,attrs):
                value=dict(attrs)
                if 'id' in value:self.ids[value['id']]=value
        parser=Regions();parser.feed((Path(__file__).resolve().parents[1]/'setup_wizard/web/index.html').read_text())
        self.assertIn('hidden',parser.ids['connectorStep'])
        for name in ('downloadClaude','downloadConfig','copyConfig'):
            self.assertIn('disabled',parser.ids[name])
        self.assertEqual({name for name in parser.ids if name.startswith('screen')},{'screen1','screen2','screen3'})
