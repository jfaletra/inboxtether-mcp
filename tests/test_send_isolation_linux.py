"""Privileged Linux-only synthetic process-isolation test, run explicitly in CI.

Uses transient numeric process identities, no useradd, no credentials, no SMTP.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0,
                     'Requires dedicated Linux CI root for transient process identities')
class LinuxSendIsolationTests(unittest.TestCase):
    def test_real_peer_identity_separation_no_approval_endpoint(self):
        with tempfile.TemporaryDirectory(prefix='inboxtether-synthetic-') as directory:
            root = Path(directory); root.chmod(0o755)
            code = root / 'code'; code.mkdir(mode=0o755)
            for name in ('send_bootstrap.py', 'send_assistant.py', 'send_client.py', 'draft_assistant.py'):
                shutil.copyfile(Path(__file__).resolve().parents[1] / name, code / name)
                (code / name).chmod(0o644)
            sender_uid, client_uid, outsider_uid, group = 65001, 65002, 65003, 65000
            state, ipc = root / 'state', root / 'ipc'
            for path, mode in ((state, 0o700), (ipc, 0o750)):
                path.mkdir(mode=mode); os.chown(path, sender_uid, group)
            config = root / 'sender.json'
            config.write_text(json.dumps({'enabled': True, 'mode': 'secure', 'identity': 'sender@example.com',
                'smtp_host': 'smtp.example.com', 'smtp_port': 465, 'tls': 'implicit', 'smtp_username': 'sender@example.com',
                'password_file': str(root / 'absent-synthetic.secret'), 'state_dir': str(state),
                'socket_path': str(ipc / 'request.sock'), 'client_uid': client_uid}))
            config.chmod(0o600); os.chown(config, sender_uid, group)
            def demote(uid):
                def run():
                    os.setgroups([]); os.setgid(group); os.setuid(uid)
                return run
            env = {**os.environ, 'PYTHONPATH': str(code), 'PYTHONDONTWRITEBYTECODE': '1'}
            # No SMTP secret exists. Use the actual isolated/sanitized bootstrap,
            # not a -c/PYTHONPATH test shim that could bypass startup protections.
            sender_env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC'}
            process = subprocess.Popen([sys.executable, '-I', '-S', '-B', str(code / 'send_bootstrap.py'), '--config', str(config), 'serve'],
                                       env=sender_env, preexec_fn=demote(sender_uid), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if (ipc / 'request.sock').exists() or process.poll() is not None:
                        break
                    time.sleep(0.05)
                self.assertIsNone(process.poll(), 'Synthetic sender must start under its separate UID')
                self.assertTrue((ipc / 'request.sock').exists())
                test_client = '''
import os, sys, socket, threading, time
from pathlib import Path
import send_client as c
p, state, config, sender, authorized = sys.argv[1:]
cfg = c.ClientConfig(Path(p), int(sender))
for path in (state, config):
    try:
        Path(path).read_bytes() if Path(path).is_file() else list(Path(path).iterdir())
    except PermissionError:
        pass
    else:
        raise AssertionError('Client accessed trusted storage')
if authorized == 'yes':
    item = c.request('prepare', {'to':['to@example.com'], 'subject':'Synthetic', 'body':'Synthetic only'}, cfg)
    assert item['status'] == 'pending_independent_approval'
    assert c.request('status', {'send_id':item['send_id']}, cfg)['status'] == 'pending'
    # A real authorized slow peer must lose its connection, allowing a queued
    # healthy request through the single broker under the production deadline.
    slow = socket.socket(socket.AF_UNIX); slow.connect(p); slow.sendall((128).to_bytes(4, 'big'))
    def drip():
        try:
            for _ in range(40):
                time.sleep(0.2); slow.sendall(b' ')
        except OSError:
            pass
    worker = threading.Thread(target=drip, daemon=True); worker.start()
    began = time.monotonic()
    assert c.request('status', {'send_id':item['send_id']}, cfg)['status'] == 'pending'
    assert time.monotonic() - began < 8
    slow.close(); worker.join(timeout=1)
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5); sock.connect(p)
        c.transmit(sock, {'operation':'approve-send','arguments':{'send_id':item['send_id'],'approved':True}})
        assert c.receive(sock)['ok'] is False
else:
    try:
        c.request('prepare', {'to':['to@example.com'], 'subject':'Synthetic', 'body':'Synthetic only'}, cfg)
    except c.SendError:
        pass
    else:
        raise AssertionError('Unauthorized peer reached broker')
'''
                for uid, authorized in ((client_uid, 'yes'), (outsider_uid, 'no')):
                    tested = subprocess.run([sys.executable, '-B', '-c', test_client, str(ipc / 'request.sock'),
                                             str(state), str(config), str(sender_uid), authorized],
                                            env=env, preexec_fn=demote(uid), capture_output=True, timeout=15)
                    self.assertEqual(tested.returncode, 0, 'Synthetic client isolation check failed')
                self.assertIsNone(process.poll())
            finally:
                process.terminate()
                process.communicate(timeout=10)


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0,
                     'Requires administrator-owned synthetic Linux installation')
class LinuxTrustedStartupTests(unittest.TestCase):
    def test_real_sanitized_entrypoint_blocks_startup_hooks_and_unsafe_code(self):
        with tempfile.TemporaryDirectory(prefix='inboxtether-bootstrap-') as directory:
            root = Path(directory); root.chmod(0o755)
            code = root / 'code'; code.mkdir(mode=0o755)
            source = Path(__file__).resolve().parents[1]
            for name in ('send_bootstrap.py', 'send_assistant.py', 'send_client.py', 'draft_assistant.py'):
                shutil.copyfile(source / name, code / name); (code / name).chmod(0o644)
            runtime = root / 'runtime'
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(runtime)], check=True, capture_output=True, timeout=30)
            markers = root / 'markers'; markers.mkdir(mode=0o700); os.chown(markers, 65001, 65000)
            marker = markers / 'hook.marker'
            payload = 'from pathlib import Path; Path(' + repr(str(marker)) + ').write_text("unexpected")\n'
            hostile = root / 'hostile'; hostile.mkdir(mode=0o755)
            (hostile / 'sitecustomize.py').write_text(payload)
            (hostile / 'usercustomize.py').write_text(payload)
            site = next(runtime.glob('lib/python*/site-packages'))
            (site / 'sitecustomize.py').write_text(payload)
            (site / 'unexpected.pth').write_text('import pathlib; pathlib.Path(' + repr(str(marker)) + ').write_text("unexpected")\n')
            template = (source / 'examples/secure-send/inboxtether-send').read_text()
            template = template.replace('/opt/inboxtether-send/venv/bin/python', str(runtime / 'bin/python'))
            template = template.replace('/opt/inboxtether-send/send_bootstrap.py', str(code / 'send_bootstrap.py'))
            launcher = root / 'inboxtether-send'; launcher.write_text(template); launcher.chmod(0o755)
            env = {**os.environ, 'PYTHONPATH': str(hostile), 'PYTHONHOME': str(hostile),
                   'PYTHONUSERBASE': str(hostile), 'PYTHONINSPECT': '1',
                   'SSLKEYLOGFILE': str(markers / 'never-keylog'), 'EXTRA_UNTRUSTED': 'synthetic'}
            def demote():
                os.setgroups([]); os.setgid(65000); os.setuid(65001)
            # Positive control: the old non-isolated invocation really executes
            # a harmless startup hook in this synthetic runtime.
            old = subprocess.run([str(runtime / 'bin/python'), '-B', '-c', 'pass'],
                                 env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'PYTHONPATH': str(hostile)},
                                 preexec_fn=demote, capture_output=True, timeout=10)
            self.assertEqual(old.returncode, 0)
            self.assertTrue(marker.exists()); marker.unlink()
            result = subprocess.run([str(launcher), '--help'], env=env, preexec_fn=demote,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, 'Valid administrator-owned isolated installation must start')
            self.assertIn(b'Trusted local send authority', result.stdout)
            self.assertFalse(marker.exists())
            self.assertFalse((markers / 'never-keylog').exists())
            # Checked BEFORE importing application modules, so neither malicious
            # ownership nor group-writable code may execute its harmless marker.
            unsafe = code / 'send_client.py'
            unsafe.write_text(payload); unsafe.chmod(0o666)
            for owner, mode in ((0, 0o666), (65002, 0o644)):
                os.chown(unsafe, owner, 0); unsafe.chmod(mode)
                rejected = subprocess.run([str(launcher), '--help'], env=env, preexec_fn=demote,
                                          capture_output=True, timeout=10)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(b'startup rejected', rejected.stderr)
                self.assertFalse(marker.exists())
