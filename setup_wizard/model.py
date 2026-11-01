"""Bounded setup inputs and short-lived secrets; no installed configuration is edited."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from urllib.parse import urlsplit

CATEGORIES = ('Industry', 'Marketing', 'Orders', 'Suppliers', 'Review')


class SetupError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def check(condition, code, message):
    if not condition:
        raise SetupError(code, message)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()


class Secret:
    """Best-effort memory erasure, not a promise that Python makes no copies."""
    def __init__(self, value):
        check(type(value) is str and 0 < len(value.encode('utf-8')) <= 4096
              and not any(c in value for c in '\r\n\x00'), 'password',
              'Enter a password or application password without line breaks.')
        self.value = bytearray(value.encode('utf-8'))

    def text(self):
        check(bool(self.value), 'password', 'Enter the password again.')
        return self.value.decode('utf-8')

    def clear(self):
        self.value[:] = b'\0' * len(self.value)
        self.value.clear()


@dataclass(frozen=True)
class MailSettings:
    host: str
    port: int
    account: str
    login: str

    @classmethod
    def parse(cls, value):
        check(type(value) is dict, 'fields', 'Check the connection details.')
        host = str(value.get('host', '')).strip()
        account = str(value.get('account', '')).strip()
        login = str(value.get('login', '')).strip() or account
        port = value.get('port', 993)
        check(bool(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', host))
              and '..' not in host, 'host', 'Enter a mail server hostname, without a URL or port.')
        check(type(port) is int and 1 <= port <= 65535, 'port', 'Enter a secure IMAP port from 1 to 65535.')
        check(bool(re.fullmatch(r'[^\s<>@]+@[^\s<>@]+', account)) and len(account) <= 320,
              'account', 'Enter the email address of the mailbox you want to connect.')
        check(0 < len(login) <= 320 and not any(ord(c) < 32 for c in login),
              'login', 'Enter a valid IMAP username.')
        return cls(host, port, account, login)


def features(value, folders):
    check(type(value) is dict and set(value) <= {
        'drafts', 'organizer', 'draft_ack', 'drafts_path', 'mailboxes', 'organizer_login',
        'review_origin', 'certificate_file', 'certificate_key_file', 'linux_user', 'owner_username'
    }, 'fields', 'An unsupported setup field was supplied.')
    for key in ('drafts', 'organizer', 'draft_ack'):
        check(type(value.get(key, False)) is bool, 'features', 'Use the feature checkboxes.')
    result = {'reader': True, 'drafts': value.get('drafts', False),
              'organizer': value.get('organizer', False),
              'linux_user': value.get('linux_user', '')}
    check(bool(re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', result['linux_user'])),
          'linux_user', 'Choose an existing, non-root Linux login for your AI connection.')
    available = {f['path']: f for f in folders}
    if result['drafts']:
        path = value.get('drafts_path')
        check(value.get('draft_ack') is True, 'draft_ack',
              'Confirm that your AI client will request approval before saving each draft.')
        check(path in available and '\\drafts' in [s.lower() for s in available[path]['flags']],
              'drafts_folder', 'Choose an existing folder marked as Drafts by your mail provider.')
        result['drafts_path'] = path
    if result['organizer']:
        maps = value.get('mailboxes', {})
        check(type(maps) is dict and set(maps) == {'INBOX', *CATEGORIES}, 'folders',
              'Map Inbox and all five filing categories to existing folders.')
        check(all(type(p) is str and p in available for p in maps.values()),
              'folders', 'Choose only folders discovered from this connection.')
        check(len({p.casefold() for p in maps.values()}) == 6, 'folders',
              'Each category needs a different existing folder.')
        for path in maps.values():
            check(len(path) <= 512 and bool(re.fullmatch(r'[A-Za-z0-9_@.+/-]+', path))
                  and all(s not in ('', '.', '..') for s in path.split('/')), 'folder_format',
                  'Organizer 2.0 requires ASCII wire paths without spaces or wildcards. No folder was changed.')
        login = value.get('organizer_login', '')
        check(type(login) is str and bool(re.fullmatch(r'[A-Za-z0-9_.+@-]{1,320}', login)),
              'organizer_login', 'Enter the existing restricted Organizer login. Asterisk master-logins are unsupported.')
        origin = value.get('review_origin', '')
        parsed = urlsplit(origin)
        try:
            port = parsed.port if parsed.port is not None else 443
        except ValueError:
            port = 0
        check(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
              and not parsed.path and not parsed.query and not parsed.fragment
              and bool(re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname)) and 1 <= port <= 65535,
              'https_origin', 'Enter the HTTPS approval address without a path, for example https://review.example.com.')
        for name in ('certificate_file', 'certificate_key_file'):
            path = value.get(name, '')
            check(type(path) is str and path.startswith('/etc/') and bool(re.fullmatch(r'[A-Za-z0-9_@.+/-]+', path))
                  and all(p not in ('.', '..', '') for p in path.split('/')[1:]),
                  'certificate', 'Use an existing certificate and key under /etc. The installer never obtains certificates or changes DNS.')
            result[name] = path
        username = value.get('owner_username', 'owner')
        check(type(username) is str and bool(re.fullmatch(r'[A-Za-z0-9_.@+-]{1,80}', username)),
              'owner_username', 'Choose a simple dedicated approval-page username.')
        result.update(mailboxes=maps, organizer_login=login, review_origin=origin,
                      owner_username=username)
    return result


def installation_plan(settings, selected, validation):
    return {'schema': 1, 'connection': asdict(settings), 'features': selected,
            'validation': validation, 'application_path': '/opt/inboxtether',
            'execution_enabled': False, 'automatic_filing_enabled': False,
            'client_session_consent': False,
            'actions': ['Install the verified source and constrained Python dependencies.',
                        'Create private credentials for the selected service identities.',
                        'Allow only the selected Linux login to launch the fixed-account MCP server.'] +
                       (['Install/reuse nginx for the explicitly configured HTTPS approval site.',
                         'Start the existing approval broker and owner-login web service.']
                        if selected['organizer'] else [])}
