"""Initial Ubuntu provisioning, using the 2.0 roles, files and service templates."""
from __future__ import annotations

import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import ssl
import stat
import subprocess
import time
from urllib.parse import urlsplit

from .model import SetupError, check

APP = Path('/opt/inboxtether')
STATE = Path('/var/lib/inboxtether-setup')
READER = 'inboxtether-reader'
EXECUTOR = 'inboxtether-organizer'
WEB = 'inboxtether-web'
BROKER_UNIT = 'inboxtether-approval-broker.service'
WEB_UNIT = 'inboxtether-approval-web.service'
TARGETS = (APP, Path('/etc/inboxtether-reader'), Path('/etc/inboxtether-organization'),
           Path('/etc/inboxtether-approval'), Path('/etc/inboxtether'),
           Path('/var/lib/inboxtether-organization'), Path('/var/lib/inboxtether-drafts'),
           Path('/usr/local/bin/inboxtether'), Path('/etc/sudoers.d/inboxtether-reader'),
           Path('/etc/systemd/system') / BROKER_UNIT, Path('/etc/systemd/system') / WEB_UNIT,
           Path('/etc/nginx/sites-available/inboxtether-approval.conf'),
           Path('/etc/nginx/sites-enabled/inboxtether-approval.conf'))


def verify_source(source):
    source = Path(source).resolve()
    manifest = source / 'MANIFEST.sha256'
    check(manifest.is_file() and not manifest.is_symlink(), 'source', 'The source checksum manifest is missing.')
    files = {}
    for line in manifest.read_text().splitlines():
        try:
            checksum, name = line.split('  ', 1)
        except ValueError:
            raise SetupError('source', 'The source checksum manifest is invalid.') from None
        path = Path(name)
        check(re.fullmatch('[0-9a-f]{64}', checksum) and not path.is_absolute()
              and all(p not in ('..', '.') for p in path.parts) and name not in files,
              'source', 'The source manifest contains an unsafe or duplicate path.')
        p = source / path
        check(p.is_file() and not p.is_symlink() and all(not a.is_symlink() for a in p.parents)
              and hashlib.sha256(p.read_bytes()).hexdigest() == checksum,
              'source', 'Source verification failed. Download a clean reviewed package; do not edit its manifest to bypass this check.')
        files[name] = checksum
    check({'server.py', 'setup_wizard/install.py', 'setup_wizard/web/index.html'} <= set(files),
          'source', 'The installation package is incomplete.')
    files['MANIFEST.sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return files


def platform_check():
    check(os.geteuid() == 0, 'administrator', 'Launch install.sh with sudo on the new Ubuntu server.')
    values = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            values[k] = v.strip('"')
    check(values.get('ID') == 'ubuntu' and values.get('VERSION_ID') == '24.04',
          'platform', 'This initial installer supports Ubuntu 24.04 only.')
    check(Path('/run/systemd/system').is_dir(), 'systemd', 'Use an Ubuntu server with systemd running, not an ordinary application container.')


def existing_user(name):
    try:
        user = pwd.getpwnam(name)
    except KeyError:
        raise SetupError('linux_user', 'The selected Linux login does not exist.') from None
    check(user.pw_uid > 0 and user.pw_shell not in ('/usr/sbin/nologin', '/bin/false'),
          'linux_user', 'Select an existing non-root login that can connect over SSH.')
    return user


def certificate_check(selected):
    if not selected['organizer']:
        return
    for key in ('certificate_file', 'certificate_key_file'):
        try:
            path = Path(selected[key]).resolve(strict=True)
        except OSError:
            raise SetupError('certificate', 'The existing certificate or private-key file was not found. Supply administrator-protected paths before continuing.') from None
        s = path.lstat()
        check(stat.S_ISREG(s.st_mode) and s.st_uid == 0 and not s.st_mode & 0o022
              and all(a.lstat().st_uid == 0 and not a.lstat().st_mode & 0o022
                      for a in (*path.parents, *Path(selected[key]).parents)),
              'certificate', 'The TLS certificate and key must already be in administrator-controlled paths.')
        if key == 'certificate_key_file':
            check(not s.st_mode & 0o007, 'certificate', 'The existing TLS private key must not be readable by other users.')
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(selected['certificate_file'], selected['certificate_key_file'], password=lambda: '')
    except Exception:
        raise SetupError('certificate', 'The TLS certificate and key do not match, are invalid, or require an interactive passphrase.') from None
    host = urlsplit(selected['review_origin']).hostname
    q = subprocess.run(['/usr/bin/openssl', 'x509', '-in', selected['certificate_file'],
                        '-noout', '-checkhost', host, '-checkend', '86400'], capture_output=True, timeout=10)
    check(q.returncode == 0 and b'does NOT match' not in q.stdout, 'certificate',
          'The certificate must match the approval hostname and remain valid for more than one day.')
    q = subprocess.run(['/usr/bin/openssl', 'verify', '-purpose', 'sslserver', '-untrusted',
                        selected['certificate_file'], selected['certificate_file']], capture_output=True, timeout=10)
    check(q.returncode == 0, 'certificate', 'The HTTPS certificate chain must be trusted by this Ubuntu installation. Self-signed certificates are not silently accepted.')


class Provisioner:
    def __init__(self, source, plan, reader_secret, organizer_secret=None, owner_secret=None, progress=lambda stage: None):
        self.source, self.plan = Path(source).resolve(), plan
        self.reader_secret, self.organizer_secret, self.owner_secret = reader_secret, organizer_secret, owner_secret
        self.progress = progress
        self.state = {'schema': 1, 'id': secrets.token_hex(16), 'status': 'installing',
                      'resources': [], 'users': [], 'services': [], 'created_at': time.time(),
                      'new_nginx': False}
        self.log = None

    def checkpoint(self):
        temporary = STATE / '.installation-next'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(self.state, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, STATE / 'installation.json')
        fd = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def record(self, path):
        p = Path(path); s = p.lstat()
        self.state['resources'].append({'path': str(p), 'device': s.st_dev, 'inode': s.st_ino,
                                        'uid': s.st_uid, 'directory': stat.S_ISDIR(s.st_mode)})
        self.checkpoint()

    def directory(self, path, mode=0o755, uid=0, gid=0):
        path = Path(path)
        path.mkdir(mode=mode)
        os.chown(path, uid, gid); os.chmod(path, mode)
        self.record(path)

    def write(self, path, data, mode=0o644, uid=0, gid=0):
        path = Path(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, 'wb') as f:
            f.write(data.encode() if isinstance(data, str) else data)
            f.flush(); os.fchown(f.fileno(), uid, gid); os.fchmod(f.fileno(), mode); os.fsync(f.fileno())
        self.record(path)

    def json(self, path, value, **kwargs):
        self.write(path, json.dumps(value, indent=2) + '\n', **kwargs)

    def run(self, stage, args, *, input=None, timeout=600):
        self.progress(stage)
        try:
            q = subprocess.run(args, input=input, capture_output=True, timeout=timeout,
                               cwd='/', env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                                             'HOME': '/root', 'LANG': 'C.UTF-8', 'DEBIAN_FRONTEND': 'noninteractive',
                                             'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        except subprocess.TimeoutExpired:
            raise SetupError('installation_timeout', stage+' took too long. The installation will be stopped and cleaned up.') from None
        text = (q.stdout + q.stderr).decode('utf-8', errors='replace')
        for secret in (self.reader_secret, self.organizer_secret, self.owner_secret):
            if secret is not None and secret.value:
                text = text.replace(secret.text(), '[redacted]')
        if self.log is not None:
            self.log.write(json.dumps({'stage': stage, 'program': Path(args[0]).name,
                                       'exit_code': q.returncode, 'output': text})+'\n'); self.log.flush()
        check(q.returncode == 0, 'installation_command', stage+' failed. Protected diagnostics are in /var/lib/inboxtether-setup/install.log; credentials were not included.')
        return q.stdout

    def preflight(self):
        platform_check()
        check(not any(p.exists() or p.is_symlink() for p in TARGETS), 'existing_installation',
              'Existing InboxTether files were found. This wizard is for initial installation only; nothing was overwritten.')
        check(not STATE.exists() and not STATE.is_symlink(), 'previous_installation',
              'An installation receipt already exists. For an interrupted installation, use the documented --recover action; completed installations are never replaced.')
        existing_user(self.plan['features']['linux_user'])
        for name in (READER, EXECUTOR, WEB):
            try:
                pwd.getpwnam(name)
            except KeyError:
                pass
            else:
                raise SetupError('existing_identity', 'An InboxTether service identity already exists. Use the existing installation, not this initial installer.')
            try:
                grp.getgrnam(name)
            except KeyError:
                continue
            raise SetupError('existing_identity', 'An InboxTether service group already exists. Nothing was changed.')
        certificate_check(self.plan['features'])
        if self.plan['features']['organizer'] and shutil.which('nginx'):
            q = subprocess.run(['/usr/sbin/nginx', '-T'], capture_output=True, timeout=15)
            check(q.returncode == 0, 'nginx_configuration', 'Existing nginx configuration must pass its own check before setup can continue.')
            host = urlsplit(self.plan['features']['review_origin']).hostname.lower()
            names = re.findall(r'^\s*server_name\s+([^;]+);', q.stdout.decode(errors='replace'), re.M)
            check(not any(host in line.lower().split() for line in names), 'https_in_use',
                  'The approval hostname already belongs to an nginx site. Choose an unused hostname; existing sites were not changed.')
        return verify_source(self.source)

    def install(self):
        files = self.preflight(); selected = self.plan['features']
        STATE.mkdir(mode=0o700)
        self.checkpoint()
        logfd = os.open(STATE / 'install.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.log = os.fdopen(logfd, 'w')
        try:
            self.state['new_nginx'] = selected['organizer'] and shutil.which('nginx') is None
            self.state['nginx_was_active'] = selected['organizer'] and subprocess.run(
                ['/usr/bin/systemctl', 'is-active', '--quiet', 'nginx.service'], capture_output=True).returncode == 0
            self.checkpoint()
            packages = ['python3-venv', 'ca-certificates'] + (['acl', 'nginx'] if selected['organizer'] else [])
            self.run('Prepare Ubuntu dependencies', ['/usr/bin/apt-get', 'update'])
            self.run('Install Ubuntu dependencies', ['/usr/bin/apt-get', 'install', '-y', '--no-install-recommends', *packages])
            for name in ((READER, EXECUTOR, WEB) if selected['organizer'] else (READER,)):
                self.run('Create '+name, ['/usr/sbin/useradd', '--system', '--user-group', '--no-create-home', '--shell', '/usr/sbin/nologin', name])
                self.state['users'].append({'name': name, 'uid': pwd.getpwnam(name).pw_uid, 'gid': pwd.getpwnam(name).pw_gid}); self.checkpoint()
            reader = pwd.getpwnam(READER)
            self.directory(APP)
            # Copy only checksum-inventoried release files, never a checkout's untracked files.
            for name, checksum in files.items():
                target = APP / name
                for parent in reversed(target.parents):
                    if APP in (parent, *parent.parents) and not parent.exists():
                        self.directory(parent)
                data = (self.source / name).read_bytes()
                check(hashlib.sha256(data).hexdigest() == checksum, 'source_changed', 'The source changed during installation; it was not trusted.')
                self.write(target, data, mode=0o755 if name.endswith('.sh') else 0o644)
            self.run('Create private Python environment', ['/usr/bin/python3', '-m', 'venv', str(APP / '.venv')])
            # The venv belongs to the new application directory and has no mailbox secrets.
            self.run('Install validated Python dependencies', [str(APP / '.venv/bin/python'), '-m', 'pip', '--isolated', 'install', '--no-input',
                     '-c', str(APP / 'constraints-validated.txt'), '-r', str(APP / ('requirements-organization.txt' if selected['organizer'] else 'requirements.txt'))])
            self.run('Verify Python dependencies', [str(APP / '.venv/bin/python'), '-m', 'pip', 'check'])
            from .model import MailSettings
            from .probe import validate_features
            settings = MailSettings(**self.plan['connection'])
            fresh = validate_features(settings, self.reader_secret, selected, self.plan['discovery'], self.organizer_secret)
            check(fresh == self.plan['validation'], 'identity_changed', 'Mailbox metadata changed before installation. Nothing will be enabled with stale identities.')
            self.directory('/etc/inboxtether')
            self.directory('/etc/inboxtether-reader', 0o700, reader.pw_uid, reader.pw_gid)
            self.write('/etc/inboxtether-reader/imap-password', self.reader_secret.text(), 0o600, reader.pw_uid, reader.pw_gid)
            env = {'INBOXTETHER_IMAP_HOST': settings.host, 'INBOXTETHER_IMAP_PORT': str(settings.port),
                   'INBOXTETHER_ACCOUNT': settings.account, 'INBOXTETHER_LOGIN_ACCOUNT': settings.login,
                   'INBOXTETHER_PASSWORD_FILE': '/etc/inboxtether-reader/imap-password'}
            if selected['drafts']:
                self.directory('/var/lib/inboxtether-drafts', 0o700, reader.pw_uid, reader.pw_gid)
                env.update(INBOXTETHER_DRAFT_ASSISTANT='1', INBOXTETHER_DRAFT_MODE='basic',
                           INBOXTETHER_BASIC_ACK='I_ACCEPT_CLIENT_CONTROLLED_APPROVAL',
                           INBOXTETHER_DRAFTS_FOLDER=selected['drafts_path'],
                           INBOXTETHER_DRAFT_STATE_DIR='/var/lib/inboxtether-drafts')
            if selected['organizer']:
                env.update(INBOXTETHER_MOVES='1', INBOXTETHER_MOVE_SOCKET='/run/inboxtether-approval-broker/moves.sock')
                self.organization(settings, selected)
            self.json('/etc/inboxtether/reader.json', env)
            command = '/opt/inboxtether/.venv/bin/python -I -B /opt/inboxtether/setup_wizard/reader_entry.py'
            self.write('/usr/local/bin/inboxtether', '#!/bin/sh\nset -eu\nexec /usr/bin/sudo -n -u '+READER+' -- '+command+'\n', 0o755)
            sudoers = selected['linux_user']+' ALL=('+READER+') NOPASSWD: NOSETENV: '+command+'\n'
            self.write('/etc/sudoers.d/inboxtether-reader', sudoers, 0o440)
            self.run('Validate the fixed Reader launch permission', ['/usr/sbin/visudo', '-cf', '/etc/sudoers.d/inboxtether-reader'])
            self.health(selected)
            self.state['status'] = 'complete'; self.state['features'] = selected
            self.state['checks'] = ['TLS and mailbox identities verified', 'Private credential permissions verified',
                                    'Constrained dependencies verified', 'MCP client handshake and tool declarations verified']
            if selected['organizer']:
                self.state['checks'] += ['Broker and browser service startup verified', 'HTTPS approval login page verified',
                                         'Execution, automatic filing and chat-consent activation remain disabled']
            self.checkpoint()
            return {'installed': True, 'checks': self.state['checks'], 'features': selected,
                    'tools': self.state['tools'], 'execution_enabled': False, 'automatic_filing_enabled': False,
                    'manual_requirements': ['Connect your chosen AI client using the generated configuration.'] +
                        (['Verify the approval hostname reaches this server through your DNS and firewall.',
                          'Sign in to the HTTPS approval page with your dedicated owner password.',
                          'Filing execution and delegated chat consent require separate explicit operator activation.'] if selected['organizer'] else [])}
        except BaseException:
            self.state['status'] = 'failed'; self.checkpoint()
            try:
                cleanup(self.state)
                self.state['status'] = 'rolled_back'; self.checkpoint()
            except Exception as cleanup_error:
                self.log.write(json.dumps({'stage': 'rollback', 'error_type': type(cleanup_error).__name__,
                    'error_code': getattr(cleanup_error, 'code', None),
                    'errno': getattr(cleanup_error, 'errno', None)})+'\n'); self.log.flush()
                self.state['status'] = 'cleanup_required'; self.checkpoint()
            raise
        finally:
            self.log.close()

    def organization(self, settings, selected):
        executor, web = pwd.getpwnam(EXECUTOR), pwd.getpwnam(WEB)
        proxy = pwd.getpwnam('www-data')
        nginx_config = Path('/etc/nginx/nginx.conf').read_text()
        check(re.search(r'^\s*user\s+www-data\s*;', nginx_config, re.M), 'nginx_identity',
              'This installer supports the standard Ubuntu nginx www-data worker. Existing custom proxy identities require operator setup.')
        self.directory('/etc/inboxtether-organization', 0o700, executor.pw_uid, executor.pw_gid)
        self.directory('/var/lib/inboxtether-organization', 0o700, executor.pw_uid, executor.pw_gid)
        self.directory('/etc/inboxtether-approval')
        self.write('/etc/inboxtether-organization/imap-password', self.organizer_secret.text(), 0o600, executor.pw_uid, executor.pw_gid)
        owner_id = secrets.token_hex(16)
        config = json.loads((APP / 'examples/organization.json.example').read_text())
        reader_uid = pwd.getpwnam(READER).pw_uid
        config.update(host=settings.host, port=settings.port, account=settings.account,
                      login_account=selected['organizer_login'], reader_uid=reader_uid,
                      web_uid=web.pw_uid, owner={'kind': 'local-owner', 'id': owner_id},
                      review_origin=selected['review_origin'], mailboxes=self.plan['validation']['mailboxes'])
        config.update(execution_enabled=False, client_session_consent=False)
        config['automatic_filing_policy']['enabled'] = False
        self.json('/etc/inboxtether-approval/organization.json', config)
        owner = json.loads((APP / 'examples/owner-login.json.example').read_text())
        owner.update(origin=selected['review_origin'], owner_id=owner_id)
        self.json('/etc/inboxtether-approval/owner-login.json', owner)
        self.json('/etc/inboxtether-approval/socket-access.json', {'reader_uid': reader_uid, 'web_uid': web.pw_uid, 'proxy_uid': proxy.pw_uid})
        self.write('/etc/inboxtether-approval/csrf.key', secrets.token_bytes(32), 0o600, web.pw_uid, web.pw_gid)
        data = json.dumps({'owner_id': owner_id, 'username': selected['owner_username'], 'password': self.owner_secret.text(), 'uid': web.pw_uid}).encode()
        self.run('Enroll the dedicated owner password privately', [str(APP / '.venv/bin/python'), '-I', '-B', str(APP / 'setup_wizard/owner_entry.py')], input=data)
        del data
        self.record('/etc/inboxtether-approval/owner.json')
        for name in ('broker.env', 'web.env'):
            self.write('/etc/inboxtether-approval/'+name, (APP / ('examples/'+name+'.example')).read_bytes())
        for name in (BROKER_UNIT, WEB_UNIT):
            self.write(Path('/etc/systemd/system') / name, (APP / 'examples' / name).read_bytes())
        host = urlsplit(selected['review_origin']).hostname
        port = urlsplit(selected['review_origin']).port or 443
        nginx = 'server {\n listen '+str(port)+' ssl;\n server_name '+host+';\n ssl_protocols TLSv1.2 TLSv1.3;\n ssl_certificate '+selected['certificate_file']+';\n ssl_certificate_key '+selected['certificate_key_file']+';\n'
        nginx += (APP / 'examples/nginx-owner.conf.example').read_text().replace('proxy_set_header Host $host;', 'proxy_set_header Host $http_host;')+'\n}\n'
        self.write('/etc/nginx/sites-available/inboxtether-approval.conf', nginx)
        os.symlink('/etc/nginx/sites-available/inboxtether-approval.conf', '/etc/nginx/sites-enabled/inboxtether-approval.conf')
        self.record('/etc/nginx/sites-enabled/inboxtether-approval.conf')
        self.run('Validate HTTPS routing', ['/usr/sbin/nginx', '-t'])
        self.run('Load the existing service definitions', ['/usr/bin/systemctl', 'daemon-reload'])
        for unit in (BROKER_UNIT, WEB_UNIT):
            self.state['services'].append(unit); self.checkpoint()
            self.run('Start '+unit, ['/usr/bin/systemctl', 'enable', '--now', unit])
        self.run('Enable the selected HTTPS approval site', ['/usr/bin/systemctl', 'reload-or-restart', 'nginx.service'])

    def health(self, selected):
        q = self.run('Verify the installed MCP connection', ['/usr/sbin/runuser', '-u', READER, '--',
                     str(APP / '.venv/bin/python'), '-I', '-B', str(APP / 'setup_wizard/check_stdio.py')])
        result = json.loads(q)
        expected = {'list_mailboxes', 'search_messages', 'read_message', 'list_attachments', 'retrieve_attachment'}
        if selected['drafts']:
            expected |= {'prepare_reply_draft', 'save_draft'}
        if selected['organizer']:
            expected.add('organize_email')
        check(set(result['tools']) == expected, 'tools', 'Installed tool declarations do not match the selected features.')
        self.state['tools'] = sorted(expected)
        if selected['organizer']:
            for unit in (BROKER_UNIT, WEB_UNIT):
                self.run('Check '+unit, ['/usr/bin/systemctl', 'is-active', '--quiet', unit])
            host = urlsplit(selected['review_origin']).hostname
            port = urlsplit(selected['review_origin']).port or 443
            # Trusted local TLS, retaining the real hostname for certificate verification.
            import socket
            with socket.create_connection(('127.0.0.1', port), 10) as raw:
                with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as c:
                    c.sendall(('GET /inboxtether/login HTTP/1.1\r\nHost: '+urlsplit(selected['review_origin']).netloc+'\r\nConnection: close\r\n\r\n').encode())
                    reply = b''
                    while len(reply) < 65536:
                        block = c.recv(min(4096, 65536-len(reply)))
                        if not block:
                            break
                        reply += block
            check(reply.startswith(b'HTTP/1.1 200') and b'InboxTether' in reply
                  and b'name="password"' in reply, 'https', 'The trusted HTTPS approval login page is not healthy.')
            config = json.loads(Path('/etc/inboxtether-approval/organization.json').read_text())
            check(config['execution_enabled'] is False and config['client_session_consent'] is False
                  and config['automatic_filing_policy']['enabled'] is False, 'gates', 'Initial write-authorization settings must remain disabled.')


def cleanup(state):
    """Remove only recorded initial-install resources; never restore old mailbox state."""
    check(state.get('schema') == 1 and state.get('status') != 'complete', 'recovery', 'A completed installation cannot be removed by setup recovery.')
    check(set(state.get('services', [])) <= {WEB_UNIT, BROKER_UNIT}, 'recovery', 'Unexpected service in recovery receipt.')
    for row in state['users']:
        check(row['name'] in (READER, EXECUTOR, WEB), 'recovery', 'Unexpected service identity in recovery receipt.')
        try:
            user = pwd.getpwnam(row['name'])
        except KeyError:
            user = None
        check(user is None or (user.pw_uid, user.pw_gid) == (row['uid'], row['gid']),
              'recovery', 'A service identity changed; recovery stopped.')
        try:
            group = grp.getgrnam(row['name'])
        except KeyError:
            group = None
        check(group is None or (group.gr_gid == row['gid'] and not group.gr_mem),
              'recovery', 'A service group changed; recovery stopped.')
    # Validate every surviving resource before stopping services or deleting any.
    for row in state['resources']:
        p = Path(row['path'])
        check(p.is_absolute() and '..' not in p.parts and any(p == t or t in p.parents for t in TARGETS), 'recovery', 'Recovery found an unrecognized path; stop for operator assessment.')
        if p.exists() or p.is_symlink():
            s = p.lstat()
            check((s.st_dev, s.st_ino, s.st_uid) == (row['device'], row['inode'], row['uid']),
                  'recovery', 'An installation resource was replaced. Recovery stopped without deleting it.')
    for unit in (WEB_UNIT, BROKER_UNIT):
        if unit in state.get('services', []):
            if (Path('/etc/systemd/system') / unit).exists():
                subprocess.run(['/usr/bin/systemctl', 'disable', '--now', unit], capture_output=True, check=True, timeout=45)
            else:
                # Recovery may resume after the earlier cleanup removed this file.
                q = subprocess.run(['/usr/bin/systemctl', 'stop', unit], capture_output=True, timeout=45)
                check(q.returncode in (0, 5) and subprocess.run(
                    ['/usr/bin/systemctl', 'is-active', '--quiet', unit], capture_output=True).returncode != 0,
                    'recovery', 'An unfinished service could not be confirmed stopped.')
    for row in reversed(state['resources']):
        p = Path(row['path'])
        if APP in p.parents:
            # The complete new APP tree is removed at its own recorded root.
            # This includes expected generated venv files and Python caches.
            continue
        check(p.is_absolute() and '..' not in p.parts and any(p == t or t in p.parents for t in TARGETS), 'recovery', 'Recovery found an unrecognized path; stop for operator assessment.')
        if not p.exists() and not p.is_symlink():
            continue
        s = p.lstat()
        check((s.st_dev, s.st_ino, s.st_uid) == (row['device'], row['inode'], row['uid']),
              'recovery', 'An installation resource was replaced. Recovery stopped without deleting it.')
        if row['directory']:
            # Only APP contains generated, untracked venv files. All other new
            # directories must be empty after their recorded children are removed.
            if p == APP:
                shutil.rmtree(p)
            else:
                p.rmdir()
        else:
            p.unlink()
    subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], capture_output=True, check=True, timeout=30)
    if state.get('new_nginx') and shutil.which('nginx'):
        subprocess.run(['/usr/bin/systemctl', 'disable', '--now', 'nginx.service'], capture_output=True, check=True, timeout=30)
    elif state.get('nginx_was_active') and shutil.which('nginx'):
        subprocess.run(['/usr/sbin/nginx', '-t'], capture_output=True, check=True, timeout=15)
        subprocess.run(['/usr/bin/systemctl', 'reload', 'nginx.service'], capture_output=True, check=True, timeout=30)
    elif state.get('services') and shutil.which('nginx'):
        subprocess.run(['/usr/bin/systemctl', 'stop', 'nginx.service'], capture_output=True, check=True, timeout=30)
    for row in reversed(state['users']):
        check(row['name'] in (READER, EXECUTOR, WEB), 'recovery', 'Unexpected service identity in the recovery receipt.')
        try:
            user = pwd.getpwnam(row['name'])
        except KeyError:
            user = None
        if user is not None:
            check(user.pw_uid == row['uid'], 'recovery', 'A service identity changed; recovery stopped.')
            subprocess.run(['/usr/sbin/userdel', row['name']], capture_output=True, check=True, timeout=30)
        try:
            group = grp.getgrnam(row['name'])
        except KeyError:
            continue
        check(group.gr_gid == row['gid'] and not group.gr_mem, 'recovery', 'A service group changed; recovery stopped.')
        subprocess.run(['/usr/sbin/groupdel', row['name']], capture_output=True, check=True, timeout=30)


def recover():
    platform_check()
    p = STATE / 'installation.json'
    s = p.lstat()
    check(not p.is_symlink() and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600,
          'recovery', 'Recovery needs the original administrator-owned installation receipt.')
    state = json.loads(p.read_text())
    check(state['status'] in ('installing', 'failed', 'cleanup_required', 'rolled_back'), 'recovery', 'This installation is complete; recovery will not alter it.')
    if state['status'] != 'rolled_back':
        cleanup(state)
    # Retain nonsecret protected diagnostic evidence; a new attempt uses a fresh path.
    destination = STATE.with_name('inboxtether-setup-recovered-'+str(int(time.time())))
    os.rename(STATE, destination)
    return str(destination)
