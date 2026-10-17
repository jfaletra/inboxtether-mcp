"""Regressions for R1/R2/R3: synthetic state, mock transport, local sockets only."""
import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import send_assistant as s
import send_client as c
from test_send_assistant import SendTests, Terminal


class ReceiptRegressionTests(SendTests):
    # Reuse fixtures without rediscovering the inherited test methods below.
    def test_historical_accepted_failed_uncertain_receipts_survive_config_changes(self):
        proposals = []
        for state in ('accepted', 'failed', 'uncertain', 'attempting'):
            proposal = self.prepare()
            self.service.store.claim(proposal['send_id'], proposal['fingerprint'])
            if state != 'attempting':
                self.service.store.finish(proposal['send_id'], {'status': state, 'retry_allowed': False})
            proposals.append((proposal, 'uncertain' if state == 'attempting' else state))
        changes = [replace(self.config, smtp_host='replacement.example.com'), replace(self.config, smtp_port=587),
                   replace(self.config, tls='starttls'), replace(self.config, smtp_username='replacement@example.com'),
                   replace(self.config, password_file=self.directory / 'replacement.secret'),
                   replace(self.config, identity='replacement@example.com'), replace(self.config, client_uid=os.geteuid() + 2)]
        for cfg in changes:
            service = s.SendService(cfg)
            for proposal, expected in proposals:
                with self.subTest(scope=cfg.scope(), expected=expected):
                    status = service.status(proposal['send_id'], trusted=True)
                    self.assertEqual(status['status'], expected)
                    self.assertFalse(status['configuration_matches'])
                    self.assertEqual(status['approved_scope'], self.config.scope())
                    self.assertFalse(status['retry_allowed'])
                    with self.assertRaises(c.SendError):
                        service.approve_and_send(proposal['send_id'], proposal['fingerprint'])
        self.ssl_factory.assert_not_called(); self.plain_factory.assert_not_called()

    def test_old_pending_approval_cannot_authorize_changed_configuration(self):
        item = self.prepare()
        service = s.SendService(replace(self.config, smtp_host='replacement.example.com'))
        self.assertEqual(service.status(item['send_id'])['status'], 'pending')
        self.assertFalse(service.status(item['send_id'])['configuration_matches'])
        with self.assertRaises(c.SendError): service.approve_and_send(item['send_id'], item['fingerprint'])
        with self.assertRaises(c.SendError):
            s.approve_interactively(service, item['send_id'], incoming=Terminal('SEND ' + item['fingerprint'] + '\n'), outgoing=Terminal())
        self.assertEqual(self.service.status(item['send_id'])['status'], 'pending')
        self.ssl_factory.assert_not_called()

    def test_changed_owner_is_operator_only_and_no_ipc_trusted_flag(self):
        item = self.prepare()
        for cfg in (replace(self.config, identity='new@example.com'), replace(self.config, client_uid=os.geteuid() + 2)):
            service = s.SendService(cfg)
            with self.assertRaises(c.SendError): service.status(item['send_id'])
            self.assertEqual(service.status(item['send_id'], trusted=True)['status'], 'pending')
            with self.assertRaises(c.SendError):
                s.dispatch(service, 'status', {'send_id': item['send_id'], 'trusted': True})
            self.assertNotIn('approved_scope', self.service.status(item['send_id']))
        self.ssl_factory.assert_not_called()

    def test_historical_reads_do_not_relax_integrity_checks(self):
        item = self.prepare()
        service = s.SendService(replace(self.config, smtp_host='replacement.example.com'))
        with self.service.store.db() as db:
            db.execute('UPDATE sends SET raw=?', (b'changed',)); db.commit()
        with self.assertRaises(c.SendError): service.status(item['send_id'], trusted=True)
        self.ssl_factory.assert_not_called()

    def test_disabled_configuration_allows_receipts_but_never_sending(self):
        item = self.prepare()
        service = s.SendService(replace(self.config, enabled=False))
        self.assertEqual(service.status(item['send_id'], trusted=True)['status'], 'pending')
        with self.assertRaises(c.SendError): service.prepare(self.arguments)
        with self.assertRaises(c.SendError): service.approve_and_send(item['send_id'], item['fingerprint'])
        obj = {k: str(v) if isinstance(v, Path) else v for k, v in vars(service.config).items()}
        path = self.directory / 'disabled.json'; path.write_text(json.dumps({**obj, 'mode': 'secure'})); path.chmod(0o600)
        with self.assertRaises(c.SendError): s.SenderConfig.load(path)
        self.assertFalse(s.SenderConfig.load(path, read_only=True).enabled)
        self.ssl_factory.assert_not_called()


# unittest would otherwise repeat the existing baseline via the fixture subclass.
for _name in list(vars(SendTests)):
    if _name.startswith('test_') and _name not in ReceiptRegressionTests.__dict__:
        setattr(ReceiptRegressionTests, _name, None)
del SendTests


class DeadlineRegressionTests(unittest.TestCase):
    def test_slow_drip_header_and_body_hit_total_deadline(self):
        raw = json.dumps({'operation': 'status', 'arguments': {}}).encode()
        for prefix in (b'', struct.pack('!I', len(raw))):
            a, b = socket.socketpair()
            with a, b:
                stop = threading.Event()
                def drip():
                    try:
                        a.sendall(prefix)
                        for value in (struct.pack('!I', len(raw)) + raw if not prefix else raw):
                            if stop.wait(0.01): return
                            a.sendall(bytes([value]))
                    except OSError:
                        pass
                worker = threading.Thread(target=drip, daemon=True); worker.start()
                started = time.monotonic()
                try:
                    with self.assertRaisesRegex(c.SendError, 'deadline'):
                        c.receive(b, deadline=started + 0.08)
                    self.assertLess(time.monotonic() - started, 0.5)
                finally:
                    stop.set(); worker.join(timeout=1)

    def test_wall_clock_changes_cannot_extend_ipc_deadline(self):
        a, b = socket.socketpair()
        with a, b, patch.object(c.time, 'time', return_value=-1000000):
            started = time.monotonic()
            with self.assertRaisesRegex(c.SendError, 'deadline'):
                c.receive(b, deadline=started + 0.04)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_expired_deadline_rejects_both_read_and_write_immediately(self):
        a, b = socket.socketpair()
        with a, b:
            for operation in (lambda: c.receive(b, time.monotonic() - 1),
                              lambda: c.transmit(a, {'ok': True}, time.monotonic() - 1)):
                with self.assertRaisesRegex(c.SendError, 'deadline'): operation()

    def test_nonreading_peer_cannot_block_response_indefinitely(self):
        a, b = socket.socketpair()
        with a, b:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
            began = time.monotonic()
            with self.assertRaisesRegex(c.SendError, 'deadline'):
                c.transmit(a, {'large': 'x' * 500000}, deadline=began + 0.05)
            self.assertLess(time.monotonic() - began, 0.5)

    def test_broker_error_path_does_not_reset_expired_budget(self):
        a, b = socket.socketpair()
        config = type('Config', (), {'client_uid': os.geteuid()})()
        with a, b, patch.object(s, 'peer_uid', return_value=os.geteuid()), patch.object(s, 'dispatch') as dispatch:
            a.sendall(b'\0')
            started = time.monotonic()
            s.handle_connection(None, config, b, seconds=0.05)
            self.assertLess(time.monotonic() - started, 0.5)
            dispatch.assert_not_called()

    def test_complete_request_shares_receive_and_response_budget(self):
        a, b = socket.socketpair()
        config = type('Config', (), {'client_uid': os.geteuid()})()
        with a, b:
            c.transmit(a, {'operation': 'status', 'arguments': {'send_id': 'synthetic'}})
            def delayed(*args):
                time.sleep(0.08)
                return {'status': 'pending'}
            with patch.object(s, 'peer_uid', return_value=os.geteuid()), patch.object(s, 'dispatch', side_effect=delayed):
                s.handle_connection(None, config, b, seconds=0.03)
            a.settimeout(0.02)
            # No success/error frame may be sent under a newly reset deadline.
            with self.assertRaises(TimeoutError): a.recv(1)


class StartupRegressionTests(unittest.TestCase):
    def test_isolated_bootstrap_blocks_hostile_startup_and_rejects_dirty_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'hook.marker'
            (root / 'sitecustomize.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("unexpected")\n')
            (root / 'usercustomize.py').write_text('raise AssertionError("user startup must not run")\n')
            env = {**os.environ, 'PYTHONPATH': str(root), 'PYTHONHOME': str(root), 'PYTHONINSPECT': '1'}
            bootstrap = Path(s.__file__).with_name('send_bootstrap.py')
            result = subprocess.run([sys.executable, '-I', '-S', '-B', str(bootstrap), '--help'], env=env, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)  # dirty env is refused before any app/config load
            self.assertFalse(marker.exists())
            self.assertIn(b'startup rejected', result.stderr)

    def test_raw_main_is_not_a_supported_entrypoint(self):
        with self.assertRaises(c.SendError): s.main()

    def test_launcher_has_fixed_isolation_and_clean_environment(self):
        root = Path(s.__file__).parent
        launcher = (root / 'examples/secure-send/inboxtether-send').read_text()
        self.assertIn('exec /usr/bin/env -i', launcher)
        self.assertIn('/opt/inboxtether-send/venv/bin/python -I -S -B', launcher)
        self.assertNotIn('$PYTHON', launcher)
        unit = (root / 'examples/secure-send/inboxtether-send.service').read_text()
        self.assertIn('ExecStart=/usr/local/libexec/inboxtether-send --config', unit)
        self.assertNotIn('send_assistant.py --config', unit)
