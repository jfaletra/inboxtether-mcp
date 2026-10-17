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
            for name in ('send_assistant.py', 'send_client.py', 'draft_assistant.py'):
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
            # A fail-closed trap ensures the broker never constructs any SMTP client.
            program = "import send_assistant as s; s.smtplib.SMTP = s.smtplib.SMTP_SSL = lambda *a, **k: (_ for _ in ()).throw(AssertionError('SMTP forbidden')); s.main()"
            process = subprocess.Popen([sys.executable, '-B', '-c', program, '--config', str(config), 'serve'],
                                       env=env, preexec_fn=demote(sender_uid), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if (ipc / 'request.sock').exists() or process.poll() is not None:
                        break
                    time.sleep(0.05)
                self.assertIsNone(process.poll(), 'Synthetic sender must start under its separate UID')
                self.assertTrue((ipc / 'request.sock').exists())
                test_client = '''
import os, sys, socket
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
