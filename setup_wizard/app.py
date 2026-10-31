"""Single-owner temporary setup session. Secrets never appear in response state."""
from __future__ import annotations

import copy
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

from . import probe
from .clients import connection_config
from .model import MailSettings, Secret, SetupError, check, features, fingerprint, installation_plan


class Session:
    def __init__(self, source, *, provisioner=None, clock=time.monotonic):
        self.source = Path(source)
        self.clock, self.started, self.last_used = clock, clock(), clock()
        self.bootstrap = secrets.token_hex(32)
        self.cookie, self.csrf = None, None
        self.lock = threading.RLock()
        self.settings = self.discovery = self.plan = self.result = None
        self.reader_secret = self.organizer_secret = self.owner_secret = None
        self.stage, self.error, self.job = 'Connect your email', None, None
        self.provisioner = provisioner

    def expired(self):
        return not self.busy() and (self.clock() - self.last_used > 900 or self.clock() - self.started > 3600)

    def busy(self):
        return self.job is not None and self.job.is_alive()

    def authenticate(self, ticket):
        with self.lock:
            check(self.bootstrap is not None and type(ticket) is str and hmac.compare_digest(ticket, self.bootstrap),
                  'setup_access', 'Open the private setup link printed in your Terminal. Do not share that link.')
            self.bootstrap = None
            self.cookie, self.csrf = secrets.token_hex(32), secrets.token_hex(32)
            self.last_used = self.clock()
            return self.cookie, self.csrf

    def authorize(self, cookie, csrf=None, *, write=False):
        with self.lock:
            if self.expired():
                self.clear()
                self.cookie = self.csrf = None
            check(self.cookie is not None and type(cookie) is str
                  and hmac.compare_digest(cookie, self.cookie), 'session', 'Setup access expired. Relaunch the installer; no email was changed.')
            if write:
                check(type(csrf) is str and hmac.compare_digest(csrf, self.csrf), 'csrf', 'The setup request could not be verified. Reload the private setup page.')
            self.last_used = self.clock()

    def clear(self):
        for key in ('reader_secret', 'organizer_secret', 'owner_secret'):
            value = getattr(self, key)
            if value is not None:
                value.clear()
            setattr(self, key, None)

    def connect(self, value):
        check(not self.busy() and self.result is None, 'state', 'Installation has already begun.')
        check(type(value) is dict and set(value) == {'connection', 'password'}, 'fields', 'Supply connection details and a hidden password.')
        self.clear(); self.settings = self.discovery = self.plan = None
        settings = MailSettings.parse(value['connection'])
        candidate = Secret(value['password'])
        # Never reuse a cached credential for a newly entered server or username.
        try:
            discovery = probe.test_reader(settings, candidate)
        except BaseException:
            candidate.clear(); raise
        self.settings, self.discovery, self.reader_secret = settings, discovery, candidate
        self.stage = 'Connection verified'
        return copy.deepcopy(discovery)

    def configure(self, value):
        try:
            return self._configure(value)
        except BaseException:
            for name in ('organizer_secret', 'owner_secret'):
                secret = getattr(self, name)
                if secret is not None:
                    secret.clear()
                setattr(self, name, None)
            raise

    def _configure(self, value):
        check(self.reader_secret is not None and not self.busy() and self.result is None,
              'state', 'Test your email connection first.')
        check(type(value) is dict and set(value) == {'features', 'organizer_password', 'owner_password', 'owner_confirmation'},
              'fields', 'Use the setup form to validate the selected features.')
        self.plan = None
        for name in ('organizer_secret', 'owner_secret'):
            old = getattr(self, name)
            if old is not None:
                old.clear()
            setattr(self, name, None)
        selected = features(value['features'], self.discovery['folders'])
        if selected['organizer']:
            self.organizer_secret = Secret(value['organizer_password'])
            self.owner_secret = Secret(value['owner_password'])
            check(len(self.owner_secret.text()) >= 16 and len(self.owner_secret.value) <= 1024,
                  'owner_password', 'Use a dedicated approval-page passphrase of at least 16 characters.')
            check(type(value['owner_confirmation']) is str and hmac.compare_digest(self.owner_secret.text().encode(), value['owner_confirmation'].encode()),
                  'owner_password', 'The dedicated owner passwords do not match.')
            check(not hmac.compare_digest(self.owner_secret.value, self.reader_secret.value)
                  and not hmac.compare_digest(self.owner_secret.value, self.organizer_secret.value),
                  'owner_password', 'The owner approval password must be separate from both mailbox passwords.')
            from .install import certificate_check
            certificate_check(selected)
        validation = probe.validate_features(self.settings, self.reader_secret, selected, self.discovery, self.organizer_secret)
        self.plan = installation_plan(self.settings, selected, validation)
        self.plan['discovery'] = copy.deepcopy(self.discovery)
        self.stage = 'Ready to install'
        return {'plan': copy.deepcopy(self.plan), 'fingerprint': fingerprint(self.plan)}

    def install(self, value):
        check(type(value) is dict and set(value) == {'fingerprint', 'confirmation'} and value['confirmation'] == 'INSTALL_SELECTED_FEATURES',
              'confirmation', 'Confirm the exact displayed installation actions.')
        check(self.plan is not None and value['fingerprint'] == fingerprint(self.plan)
              and self.job is None, 'plan_changed', 'The installation plan changed or has already been started. It was not repeated.')
        from .install import Provisioner
        engine = (self.provisioner or Provisioner)(self.source, copy.deepcopy(self.plan), self.reader_secret,
                                                   self.organizer_secret, self.owner_secret, progress=self.progress)
        self.error = None

        def run():
            try:
                self.result = engine.install()
                self.stage = 'Installation verified'
            except SetupError as error:
                self.error = {'code': error.code, 'message': error.message}
                self.stage = 'Installation stopped'
            except Exception:
                self.error = {'code': 'installation_failed', 'message': 'Installation stopped. Check the protected installation receipt and diagnostics before another attempt; no automatic retry was made.'}
                self.stage = 'Installation stopped'
            finally:
                self.clear()
        self.job = threading.Thread(target=run, name='inboxtether-initial-install', daemon=False)
        self.job.start()
        return {'started': True}

    def progress(self, stage):
        self.stage = stage

    def status(self):
        return {'stage': self.stage, 'running': self.busy(), 'result': self.result, 'error': self.error,
                'connection_verified': self.discovery is not None,
                'default_linux_user': os.environ.get('SUDO_USER', ''), 'initial_installation_only': True}

    def dispatch(self, path, value):
        with self.lock:
            if path == '/api/connect': return self.connect(value)
            if path == '/api/configure': return self.configure(value)
            if path == '/api/install': return self.install(value)
            if path == '/api/client':
                check(type(value) is dict and set(value) == {'client', 'location', 'target'}, 'fields', 'Choose a connection option.')
                return connection_config(**value)
            raise SetupError('route', 'That setup action is not available.')
