"""Synthetic state and mocked IMAP/SMTP only; no remote mail connections."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import base64
import json
import os
from pathlib import Path
import ssl
import sqlite3
import time
import unittest
from unittest.mock import patch

import send_assistant as s
import test_send_assistant as fixtures


class FakeIMAP:
    def __init__(self):
        self.calls, self.messages = [], {}
        self.rows = [b'(\\HasNoChildren \\Sent) "/" "Sent Items"']
        self.failure = None
        self.caps = b'IMAP4rev1 UIDPLUS SPECIAL-USE'
        self.validity = 71
        self.append_uid = b'71 42'
        self.last_raw = None

    def step(self, name):
        self.calls.append(name)
        if self.failure == name:
            raise OSError('SYNTHETIC PRIVATE IMAP REPLY')

    def login(self, username, secret):
        self.step('login')
        assert secret == 'synthetic-imap-only-secret'
        return 'OK', [b'authenticated']

    def capability(self):
        self.step('capability')
        return 'OK', [self.caps]

    def list(self, *args):
        self.step('list')
        return 'OK', self.rows

    def select(self, mailbox, readonly=False):
        self.step('select')
        assert readonly and mailbox.startswith('"') and mailbox.endswith('"')
        return 'OK', [b'0']

    def response(self, name):
        if name == 'UIDVALIDITY':
            return name, [str(self.validity).encode()]
        if name == 'APPENDUID':
            return name, [self.append_uid]
        raise AssertionError('Unexpected response requested')

    def uid(self, command, *args):
        self.step(command.lower())
        if command == 'SEARCH':
            return 'OK', [b' '.join(str(k).encode() for k in self.messages)]
        if command == 'FETCH':
            uid = int(args[0]);raw = self.messages[uid]
            if args[1] == '(RFC822.SIZE)':
                return 'OK', [f'1 (UID {uid} RFC822.SIZE {len(raw)})'.encode()]
            assert args[1] == '(BODY.PEEK[])'
            return 'OK', [(f'1 (UID {uid} BODY[] {{{len(raw)}}}'.encode(), raw), b')']
        raise AssertionError('Unexpected IMAP operation')

    def append(self, mailbox, flags, date, raw):
        self.step('append-before')
        assert mailbox == s.folder_wire('Sent Items') and flags == '(\\Seen)' and date is None
        self.last_raw = raw
        self.messages[42] = raw
        self.step('append-after')
        return ('NO' if self.failure == 'append-rejected' else 'OK'), [b'synthetic']

    def logout(self):
        self.step('logout')
        return 'BYE', []

    def shutdown(self):
        self.calls.append('shutdown')


class SentSyncTests(unittest.TestCase):
    setUpBase = fixtures.SendTests.setUp

    def setUp(self):
        temp = patch('tempfile.tempdir', str(Path('/tmp').resolve()))
        temp.start();self.addCleanup(temp.stop)
        self.setUpBase()
        self.imap = FakeIMAP()
        self.secret = self.directory / 'imap.secret'
        self.secret.write_text('synthetic-imap-only-secret');self.secret.chmod(0o600)
        sent = s.SentConfig('imap.example.com', self.config.identity, self.secret, enabled=True)
        self.config = replace(self.config, sent_copy=sent)
        self.service = s.SendService(self.config)
        p = patch.object(s.imaplib, 'IMAP4_SSL', return_value=self.imap)
        self.factory = p.start();self.addCleanup(p.stop)
        s.discover_sent(self.config)
        self.factory.reset_mock();self.imap.calls.clear()

    def prepare(self, **kwargs):
        return self.service.prepare({**self.arguments, **kwargs})

    def send(self, proposal):
        return self.service.approve_and_send(proposal['send_id'], proposal['fingerprint'])

    def accepted(self):
        p = self.prepare()
        self.service.store.claim(p['send_id'], p['fingerprint'])
        self.service.store.finish(p['send_id'], {'status': 'accepted', 'retry_allowed': False})
        return p

    def test_disabled_default_and_legacy_configuration(self):
        cfg = replace(self.config, sent_copy=None)
        manifest, _ = s.prepare_message(cfg, self.arguments)
        self.assertNotIn('sent_copy', cfg.scope());self.assertNotIn('sent_filing', manifest)
        disabled = replace(self.config, sent_copy=replace(self.config.sent_copy, enabled=False))
        self.assertNotIn('sent_copy', disabled.scope())
        self.assertNotIn('sent_filing', s.prepare_message(disabled, self.arguments)[0])
        data = {k: str(v) if isinstance(v, Path) else v for k,v in vars(cfg).items() if k != 'sent_copy'}
        data['mode'] = 'secure'
        path = self.directory / 'sender.json';path.write_text(json.dumps(data));path.chmod(0o600)
        self.assertIsNone(s.SenderConfig.load(path).sent_copy)
        data['sent_copy'] = {**vars(self.config.sent_copy), 'password_file': str(self.secret)}
        path.write_text(json.dumps(data))
        self.assertEqual(s.SenderConfig.load(path), self.config)
        self.factory.assert_not_called()

    def test_authenticated_discovery_refresh_tls_and_no_folder_writes(self):
        s.discover_sent(self.config)
        self.assertLess(self.imap.calls.index('login'), self.imap.calls.index('capability'))
        context = self.factory.call_args.kwargs['ssl_context']
        self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertNotIn('append-before', self.imap.calls)
        self.assertEqual(s.sent_destination(self.config)['folder'], 'Sent Items')
        self.assertEqual((self.directory/'sent-destination.json').stat().st_mode & 0o777, 0o600)

    def test_preparation_offline_and_exact_approval_destination(self):
        p = self.prepare()
        self.factory.assert_not_called()
        self.assertEqual(p['manifest']['sent_filing']['folder'], 'Sent Items')
        self.assertEqual(p['fingerprint'], s.digest(s.canonical(p['manifest'])))
        with self.assertRaises(s.SendError):self.prepare(sent_filing={'folder':'Other'})
        with self.assertRaises(s.SendError):s.dispatch(self.service, 'file-sent', {'send_id':p['send_id']})
        with self.assertRaises(s.SendError):s.dispatch(self.service, 'reconcile-sent', {'send_id':p['send_id']})

    def test_missing_pin_requires_operator_setup(self):
        (self.directory/'sent-destination.json').unlink()
        with self.assertRaises(FileNotFoundError):self.prepare()
        self.factory.assert_not_called()

    def test_exact_mime_attachment_bcc_and_thread_headers_preserved(self):
        p = self.prepare(attachments=[{'filename':'test.txt','content_type':'text/plain','data_base64':base64.b64encode(b'synthetic attachment').decode()}])
        raw = self.service.store.get(p['send_id'])['raw']
        result = self.send(p)
        self.assertEqual(result['status'], 'accepted');self.assertEqual(result['sent_copy'], 'saved')
        self.assertEqual(self.imap.last_raw, raw);self.assertEqual(self.fake.raw, raw)
        self.assertEqual(s.digest(raw), p['manifest']['mime_sha256'])
        self.assertNotIn(b'Bcc:', self.imap.last_raw)
        self.assertEqual(result['sent_copy_receipt']['uidvalidity'], 71)
        self.assertEqual(result['sent_copy_receipt']['uid'], 42)

    def test_reply_threading_is_identical_in_sent_copy(self):
        parent = b'Message-ID: <parent@example.com>\r\nReferences: <older@example.com>\r\n\r\n'
        reply = {'source': {'mailbox':'INBOX','uid':12,'uidvalidity':34,'sha256':s.digest(parent)},
                 'headers_base64':base64.b64encode(parent).decode(), 'context':{'body':'Synthetic parent'}}
        p=self.prepare(reply=reply);self.send(p)
        self.assertEqual(self.imap.last_raw,self.fake.raw)
        self.assertIn(b'In-Reply-To: <parent@example.com>',self.imap.last_raw)
        self.assertIn(b'References: <older@example.com> <parent@example.com>',self.imap.last_raw)

    def test_only_after_durable_acceptance_and_no_smtp_from_filing(self):
        p = self.prepare()
        with self.assertRaises(s.SendError):self.service.file_sent(p['send_id'])
        self.factory.assert_not_called()
        self.service.store.claim(p['send_id'],p['fingerprint'])
        with self.assertRaises(s.SendError):self.service.file_sent(p['send_id'])
        for status in ('uncertain','failed'):
            other=self.prepare();self.service.store.claim(other['send_id'],other['fingerprint'])
            self.service.store.finish(other['send_id'],{'status':status})
            with self.assertRaises(s.SendError):self.service.file_sent(other['send_id'])
        self.factory.assert_not_called();self.ssl_factory.assert_not_called()

    def test_smtp_failed_or_uncertain_never_files(self):
        for failure in ('data','data-rejected'):
            self.fake.failure=failure
            r=self.send(self.prepare())
            self.assertIn(r['status'],('failed','uncertain'))
        self.factory.assert_not_called()

    def test_lost_smtp_receipt_never_files(self):
        p=self.prepare()
        with patch.object(self.service.store,'finish',side_effect=OSError):
            r=self.send(p)
        self.assertEqual(r['status'],'uncertain');self.factory.assert_not_called()

    def test_duplicate_append_and_smtp_replay_rejected(self):
        p=self.prepare();self.send(p)
        with self.assertRaises(s.SendError):self.send(p)
        with self.assertRaises(s.SendError):self.service.file_sent(p['send_id'])
        self.assertEqual(self.imap.calls.count('append-before'),1)
        self.assertEqual(self.fake.calls.count('data'),1)

    def test_concurrent_claim_is_single_use(self):
        p=self.accepted()
        def claim(_):
            try:self.service.store.claim_filing(p['send_id']);return True
            except s.SendError:return False
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(sum(pool.map(claim,range(4))),1)
        self.factory.assert_not_called()

    def test_connection_and_preappend_failures_never_resend(self):
        for failure in ('connection','login','capability','list','select','search'):
            with self.subTest(failure=failure):
                self.imap.failure=failure
                if failure=='connection':self.factory.side_effect=OSError('private')
                p=self.prepare();r=self.send(p)
                self.assertEqual(r['status'],'accepted');self.assertEqual(r['sent_copy'],'failed')
                with self.assertRaises(s.SendError):self.service.file_sent(p['send_id'])
                self.factory.side_effect=None
        self.assertEqual(self.fake.calls.count('data'),6)
        self.assertNotIn('append-before',self.imap.calls)

    def test_ambiguous_append_reconciles_exact_bytes_without_reappend(self):
        p=self.prepare();self.imap.failure='append-after'
        r=self.send(p);self.assertEqual(r['sent_copy'],'uncertain')
        self.imap.failure=None
        r=self.service.reconcile_sent(p['send_id'])
        self.assertEqual(r['state'],'saved');self.assertTrue(r['reconciled'])
        self.assertEqual(self.imap.calls.count('append-before'),1)
        self.assertEqual(self.fake.calls.count('data'),1)

    def test_ambiguous_append_absence_never_retries(self):
        p=self.prepare();self.imap.failure='append-before'
        self.assertEqual(self.send(p)['sent_copy'],'uncertain')
        self.imap.failure=None
        self.assertEqual(self.service.reconcile_sent(p['send_id'])['state'],'uncertain')
        with self.assertRaises(s.SendError):self.service.file_sent(p['send_id'])
        self.assertEqual(self.imap.calls.count('append-before'),1)

    def test_append_no_response_is_failure_but_never_automatic_retry(self):
        self.imap.failure='append-rejected';p=self.prepare()
        self.assertEqual(self.send(p)['sent_copy'],'failed')
        with self.assertRaises(s.SendError):self.service.file_sent(p['send_id'])
        self.assertEqual(self.imap.calls.count('append-before'),1)

    def test_uidplus_missing_before_append_and_after_append(self):
        p=self.prepare();self.imap.caps=b'IMAP4rev1'
        self.assertEqual(self.send(p)['sent_copy'],'failed')
        self.assertNotIn('append-before',self.imap.calls)
        self.imap.caps=b'IMAP4rev1 UIDPLUS';self.imap.append_uid=b''
        p=self.prepare();self.assertEqual(self.send(p)['sent_copy'],'uncertain')
        self.assertEqual(self.imap.calls.count('append-before'),1)

    def test_changed_mailbox_before_append_is_blocked(self):
        p=self.prepare();self.imap.validity=72
        self.assertEqual(self.send(p)['sent_copy'],'failed')
        self.assertNotIn('append-before',self.imap.calls)

    def test_uidvalidity_change_and_verification_failure_are_uncertain(self):
        for returned in (b'72 42',b'71 0',b'71 42:43'):
            self.imap.messages.clear();self.imap.append_uid=returned
            p=self.prepare();self.assertEqual(self.send(p)['sent_copy'],'uncertain')
        self.imap.messages.clear();self.imap.append_uid=b'71 42';self.imap.failure='fetch'
        self.assertEqual(self.send(self.prepare())['sent_copy'],'uncertain')

    def test_conflicting_or_duplicate_existing_message_never_appends(self):
        p=self.accepted();raw=self.service.store.get(p['send_id'])['raw']
        for messages in ({1:b'conflicting'}, {1:raw,2:raw}):
            with self.subTest(messages=len(messages)):
                # Exercise helper only; claim state remains owned by service APIs.
                self.imap.messages=messages
                r=s.file_sent_copy(self.config,self.service.store.get(p['send_id']))
                self.assertEqual(r['state'],'failed')
        self.assertNotIn('append-before',self.imap.calls)

    def test_preexisting_exact_server_copy_is_not_duplicated(self):
        p=self.accepted();self.imap.messages={8:self.service.store.get(p['send_id'])['raw']}
        r=self.service.file_sent(p['send_id']);self.assertEqual(r['state'],'saved');self.assertEqual(r['uid'],8)
        self.assertNotIn('append-before',self.imap.calls);self.ssl_factory.assert_not_called()

    def test_recovery_after_receipt_write_failure(self):
        p=self.prepare()
        with patch.object(self.service.store,'finish_filing',side_effect=OSError):
            self.assertEqual(self.send(p)['sent_copy'],'uncertain')
        recovered=s.SendService(self.config)
        self.assertEqual(recovered.reconcile_sent(p['send_id'])['state'],'saved')
        self.assertEqual(self.imap.calls.count('append-before'),1)
        self.assertEqual(self.fake.calls.count('data'),1)

    def test_consistent_database_restore_preserves_uncertain_claim(self):
        p=self.prepare();self.imap.failure='append-after';self.send(p)
        restored=self.directory/'restored';restored.mkdir(mode=0o700)
        with self.service.store.db() as source:
            target=sqlite3.connect(restored/'sends.sqlite3');source.backup(target);target.close()
        (restored/'sends.sqlite3').chmod(0o600)
        pin=restored/'sent-destination.json';pin.write_bytes((self.directory/'sent-destination.json').read_bytes());pin.chmod(0o600)
        recovered=s.SendService(replace(self.config,state_dir=restored,enabled=False))
        with self.assertRaises(s.SendError):recovered.file_sent(p['send_id'])
        self.imap.failure=None
        self.assertEqual(recovered.reconcile_sent(p['send_id'])['state'],'saved')
        self.assertEqual(self.imap.calls.count('append-before'),1)
        self.assertEqual(self.fake.calls.count('data'),1)

    def test_malformed_fetch_metadata_and_excessive_matches_fail_closed(self):
        p=self.accepted();item=self.service.store.get(p['send_id'])
        self.imap.messages={n:item['raw'] for n in range(1,22)}
        self.assertEqual(s.file_sent_copy(self.config,item)['state'],'failed')
        self.imap.messages={1:item['raw']}
        with patch.object(self.imap,'uid',side_effect=[('OK',[b'1']),('OK',[b'1 (UID 2 RFC822.SIZE 100)'])]):
            self.assertEqual(s.file_sent_copy(self.config,item)['state'],'failed')
        self.assertNotIn('append-before',self.imap.calls)

    def test_altered_manifest_or_staged_mime_cannot_file(self):
        p=self.accepted()
        with self.service.store.db() as db:
            db.execute('update sends set raw=? where id=?',(b'altered',p['send_id']));db.commit()
        with self.assertRaises(s.SendError):self.service.file_sent(p['send_id'])
        self.factory.assert_not_called()

    def test_stale_or_tampered_filing_receipt_rejected(self):
        p=self.prepare();self.send(p)
        with self.service.store.db() as db:
            db.execute('update sent_copies set result=? where send_id=?',(s.canonical({'state':'uncertain','retry_allowed':True}),p['send_id']));db.commit()
        with self.assertRaises(s.SendError):self.service.status(p['send_id'])

    def test_recovery_between_acceptance_and_claim_with_sending_disabled(self):
        p=self.accepted();self.assertEqual(self.service.status(p['send_id'])['sent_copy'],'pending')
        recovered=s.SendService(replace(self.config,enabled=False))
        self.assertEqual(recovered.file_sent(p['send_id'])['state'],'saved')
        self.ssl_factory.assert_not_called()

    def test_historical_receipt_after_config_changes_and_disabled_sync(self):
        p=self.prepare();self.send(p)
        new=s.SendService(replace(self.config,sent_copy=replace(self.config.sent_copy,host='other.example.com')))
        r=new.status(p['send_id'],trusted=True);self.assertEqual(r['sent_copy'],'saved');self.assertFalse(r['configuration_matches'])
        with self.assertRaises(s.SendError):new.file_sent(p['send_id'])
        off=s.SendService(replace(self.config,sent_copy=None,enabled=False))
        self.assertEqual(off.status(p['send_id'],trusted=True)['sent_copy'],'saved')

    def test_destination_or_imap_policy_changes_invalidate_pending_approval(self):
        p=self.prepare();pin=self.directory/'sent-destination.json';data=json.loads(pin.read_text());data['folder']='Elsewhere';pin.write_text(json.dumps(data))
        with self.assertRaises(s.SendError):self.send(p)
        self.ssl_factory.assert_not_called()
        other=s.SendService(replace(self.config,sent_copy=replace(self.config.sent_copy,port=999)))
        with self.assertRaises(s.SendError):other.approve_and_send(p['send_id'],p['fingerprint'])

    def test_missing_ambiguous_noselect_and_override_discovery(self):
        for rows in ([],[b'(\\Sent \\Noselect) "/" "Sent"'],[b'(\\Sent) "/" "A"',b'(\\Sent) "/" "B"']):
            self.imap.rows=rows
            with self.assertRaises(s.SendError):s.discover_sent(self.config)
        self.imap.rows=[b'() "/" "Archive"']
        cfg=replace(self.config,sent_copy=replace(self.config.sent_copy,folder='Archive'))
        self.assertEqual(s.discover_sent(cfg)['sent_folder'],'Archive')
        self.assertNotIn('append-before',self.imap.calls)

    def test_literal_unicode_escaped_and_malformed_folder_handling(self):
        name='Envoyés & "notes" \\ 2026'
        encoded=s.folder_wire(name)[1:-1].replace('\\"','"').replace('\\\\','\\').encode('ascii')
        self.imap.rows=[(b'(\\Sent) "/" {'+str(len(encoded)).encode()+b'}',encoded)]
        self.assertEqual(s.choose_sent(self.imap,None),name)
        for invalid in ('','Sent\r\nCREATE evil','A\x00B'):
            with self.assertRaises((s.SendError, fixtures.DraftError, ValueError)):s.folder_wire(invalid)
        self.imap.rows=[b'invalid folder response']
        with self.assertRaises(s.SendError):s.choose_sent(self.imap,None)

    def test_separate_credential_owner_mode_and_same_mailbox_required(self):
        for sent in (replace(self.config.sent_copy,password_file=self.config.password_file),replace(self.config.sent_copy,username='other@example.com')):
            with self.assertRaises(s.SendError):s.SendService(replace(self.config,sent_copy=sent))
        self.secret.chmod(0o644);p=self.prepare()
        self.assertEqual(self.send(p)['sent_copy'],'failed')
        self.assertNotIn('login',self.imap.calls)

    def test_symlink_pin_and_secret_rejected(self):
        pin=self.directory/'sent-destination.json';saved=pin.read_bytes();pin.unlink();target=self.directory/'pin-copy';target.write_bytes(saved);target.chmod(0o600);pin.symlink_to(target)
        with self.assertRaises(OSError):self.prepare()
        pin.unlink();pin.write_bytes(saved);pin.chmod(0o600)
        self.secret.unlink();self.secret.symlink_to(self.config.password_file)
        self.assertEqual(self.send(self.prepare())['sent_copy'],'failed')
        self.assertNotIn('append-before',self.imap.calls)

    def test_filing_receipt_survives_expired_message_and_does_not_log_secrets(self):
        p=self.prepare();self.imap.failure='append-after';self.send(p)
        with patch.object(s.time,'time',return_value=time.time()+10000):
            self.assertEqual(self.service.reconcile_sent(p['send_id'])['state'],'saved')
        r=json.dumps(self.service.status(p['send_id'],trusted=True))
        for forbidden in ('synthetic-imap-only-secret','SYNTHETIC PRIVATE IMAP REPLY'):
            self.assertNotIn(forbidden,r)
        self.assertFalse(self.service.status(p['send_id'])['retry_allowed'])


if __name__ == '__main__':
    unittest.main()
