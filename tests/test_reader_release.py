import ast
import imaplib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s
from scripts.check_repository import findings


class ReaderReleaseTests(unittest.TestCase):
    def test_all_nonallowlisted_imap_commands_and_uid_mutations_denied(self):
        client = object.__new__(s.ReadOnlyIMAP)
        mutations = {'SEND', 'MOVE', 'COPY', 'STORE', 'APPEND', 'DELETE', 'CREATE',
                     'RENAME', 'EXPUNGE', 'CLOSE', 'SELECT', 'SUBSCRIBE', 'UNSUBSCRIBE',
                     'SETACL', 'SETQUOTA', 'UID EXPUNGE'}
        for name in (set(imaplib.Commands) - s.ReadOnlyIMAP.ALLOWED) | mutations:
            with self.subTest(command=name), self.assertRaises(s.MailError):
                client._command(name, '1')
        for operation in mutations | {'copy', 'move', 'store'}:
            with self.subTest(uid_operation=operation), self.assertRaises(s.MailError):
                client._command('UID', operation, '1', 'INBOX')

    def test_no_smtp_transport_import_in_application(self):
        tree = ast.parse(Path(s.__file__).read_text())
        imports = {alias.name.split('.')[0] for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for alias in node.names}
        imports |= {node.module.split('.')[0] for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module}
        self.assertFalse(imports & {'smtplib', 'aiosmtplib'})


class HygienePatternTests(unittest.TestCase):
    def test_detects_synthetic_credentials_and_private_metadata(self):
        samples = [b'sk-' + b'X' * 30, b'github_pat_' + b'X' * 30,
                   b'-----BEGIN ' + b'PRIVATE KEY-----', b'AKIA' + b'X' * 16,
                   b'https://' + b'user:password@host.example.com',
                   b'192.' + b'168.3.4', b'/' + b'Users/' + b'person/private/',
                   b'person@' + b'private.invalid']
        for index, sample in enumerate(samples):
            with self.subTest(sample_index=index):
                self.assertTrue(findings(sample))

    def test_allows_example_and_github_noreply_attribution(self):
        self.assertEqual(findings(b'user@example.com noreply@github.com support@github.com '
                                  b'123+maintainer@users.noreply.github.com'), [])
