"""TLS-verified, metadata-only setup checks. No SEARCH, FETCH or mutation command."""
from __future__ import annotations

from contextlib import contextmanager
import imaplib
import re
import socket
import ssl

from server import ReadOnlyIMAP, quoted
from .model import SetupError, check


class SetupIMAP(ReadOnlyIMAP):
    ALLOWED = frozenset({'CAPABILITY', 'LOGIN', 'LIST', 'EXAMINE', 'MYRIGHTS', 'LOGOUT'})


def examine(client, path):
    status, _ = client.select(quoted(path, 512), readonly=True)
    _, rows = client.response('UIDVALIDITY')
    check(status == 'OK' and rows and len(rows) == 1 and isinstance(rows[0], bytes)
          and re.fullmatch(rb'[1-9][0-9]{0,9}', rows[0]) and int(rows[0]) <= 4294967295,
          'uidvalidity', 'The folder did not supply a valid, stable mailbox identity.')
    return int(rows[0])


@contextmanager
def connection(settings, secret, *, factory=SetupIMAP, login=None):
    client = None
    try:
        client = factory(settings.host, settings.port, ssl_context=ssl.create_default_context(), timeout=15)
        client.login(login or settings.login, secret.text())
        yield client
    except SetupError:
        raise
    except ssl.SSLCertVerificationError:
        raise SetupError('tls_certificate', 'The server certificate is not trusted or does not match the hostname. TLS verification was not bypassed.') from None
    except ssl.SSLError:
        raise SetupError('tls', 'A secure TLS connection could not be established. Check the secure IMAP port.') from None
    except imaplib.IMAP4.error:
        raise SetupError('authentication', 'Sign-in or mailbox access was refused. Check the username, application password and provider IMAP settings.') from None
    except (OSError, socket.timeout):
        raise SetupError('connection', 'The mail server could not be reached. Check its hostname, port and network access.') from None
    except Exception:
        raise SetupError('mailbox_metadata', 'The provider returned unsupported or incomplete mailbox metadata. No messages were read or changed.') from None
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                pass


def discover(client):
    status, rows = client.list('""', '"*"')
    check(status == 'OK' and rows, 'folders', 'The mailbox did not return its existing folders.')
    check(len(rows) <= 200, 'folders_limit', 'This mailbox has more than 200 folders; it needs an operator assessment before setup.')
    result = []
    for row in rows:
        check(isinstance(row, bytes) and len(row) <= 8192, 'folder_format',
              'This provider uses a mailbox-name format not supported by InboxTether 2.0.')
        match = re.fullmatch(rb'\(([^)]*)\) (NIL|"(?:[^"\\]|\\.)*") (.+)', row)
        check(match is not None, 'folder_format', 'The mailbox folder listing could not be interpreted safely.')
        try:
            flags = match[1].decode('ascii').split()
            wire = match[3].decode('ascii')
            delimiter = None if match[2] == b'NIL' else match[2][1:-1].decode('ascii')
        except UnicodeError:
            raise SetupError('folder_format', 'The provider must return supported IMAP wire names.') from None
        if wire.startswith('"') and wire.endswith('"'):
            wire = re.sub(r'\\(.)', r'\1', wire[1:-1])
        if '\\noselect' in [f.lower() for f in flags]:
            continue
        check(0 < len(wire) <= 512 and not any(ord(c) < 32 for c in wire), 'folder_format', 'A folder name is outside supported limits.')
        check(wire not in {r['path'] for r in result}, 'folder_alias', 'Duplicate folder identities were returned.')
        result.append({'path': wire, 'flags': flags, 'delimiter': delimiter})
    return result


def test_reader(settings, secret, *, factory=SetupIMAP):
    with connection(settings, secret, factory=factory) as client:
        folders = discover(client)
        inbox = next((f['path'] for f in folders if f['path'].upper() == 'INBOX'), None)
        check(inbox is not None, 'inbox', 'No selectable Inbox was advertised for this login. A shared-mailbox mapping needs operator review.')
        uv = examine(client, inbox)
        return {'tls': True, 'authenticated': True, 'inbox_path': inbox,
                'source_uidvalidity': uv, 'capabilities': sorted(client.capabilities),
                'folders': folders, 'message_content_read': False}


def folder_snapshot(rows):
    # LIST's Marked/Unmarked are transient folder-status hints, not mailbox
    # identities or message flags. EXAMINE itself can change these hints.
    return sorted((r['path'], r['delimiter'], sorted(f.casefold() for f in r['flags']
                  if f.casefold() not in ('\\marked', '\\unmarked'))) for r in rows)


def validate_features(settings, reader_secret, selected, discovery, organizer_secret=None, *, factory=SetupIMAP):
    result = {'reader_uidvalidity': discovery['source_uidvalidity'], 'mailboxes': {}}
    with connection(settings, reader_secret, factory=factory) as client:
        current = discover(client)
        check(folder_snapshot(current) == folder_snapshot(discovery['folders'])
              and examine(client, discovery['inbox_path']) == discovery['source_uidvalidity'],
              'identity_changed', 'Mailbox identity or folders changed. Test the connection again before installation.')
        if selected['drafts']:
            check('UIDPLUS' in client.capabilities, 'draft_capability', 'Draft saving requires the provider UIDPLUS capability.')
            check(any(f['path'] == selected['drafts_path'] and '\\drafts' in [x.lower() for x in f['flags']] for f in current),
                  'drafts_folder', 'The selected folder no longer advertises the Drafts special-use flag.')
            result['drafts_uidvalidity'] = examine(client, selected['drafts_path'])
        if selected['organizer']:
            result['reader_uidvalidity'] = examine(client, selected['mailboxes']['INBOX'])
    if selected['organizer']:
        check(all(re.fullmatch(r'[A-Za-z0-9_.+@-]{1,320}', x) for x in (settings.host, settings.account, selected['organizer_login'])),
              'organizer_identity', 'Organizer requires supported ASCII host and login identities. Reader remains available separately.')
        check(selected['organizer_login'].casefold() not in {settings.account.casefold(), settings.login.casefold()},
              'dedicated_login', 'Organizer needs an existing restricted login to this mailbox, not another mailbox. No account or permission will be created at your provider.')
        check(organizer_secret is not None, 'organizer_password', 'Enter the restricted Organizer application password.')
        from organizer.imap_adapter import IMAPMailbox
        with connection(settings, organizer_secret, factory=factory, login=selected['organizer_login']) as client:
            check({'ACL', 'MOVE', 'UIDPLUS'} <= set(client.capabilities), 'organizer_capability',
                  'Organizer requires ACL/MYRIGHTS, UID MOVE and UIDPLUS. Reader remains available with providers that do not support these features.')
            listed = {f['path'] for f in discover(client)}
            check(set(selected['mailboxes'].values()) <= listed, 'organizer_namespace',
                  'The restricted login cannot see every selected folder. Ask your provider to configure the mapping; no ACL was changed.')
            client._namespace_names = {name: quoted(path, 512) for name, path in selected['mailboxes'].items()}
            client._namespace_validities = {}
            client._corrective_rights = True
            for name, path in selected['mailboxes'].items():
                uv = examine(client, path)
                client._namespace_validities[name] = uv
                try:
                    IMAPMailbox._rights(client, name, 'lrte' if name == 'INBOX' else 'lrisw')
                except Exception:
                    raise SetupError('organizer_rights', 'The restricted login has missing or broader-than-supported rights for '+name+'. An administrator must provide the reviewed restricted access; the installer never changes provider ACLs.') from None
                result['mailboxes'][name] = {'path': path, 'uidvalidity': uv}
            check(result['mailboxes']['INBOX']['uidvalidity'] == result['reader_uidvalidity'],
                  'identity_changed', 'Reader and Organizer must point to the same verified Inbox identity.')
    return result
