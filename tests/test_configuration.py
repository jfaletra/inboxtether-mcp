"""Community configuration differs from the fixed private deployment."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1] / 'server.py'


class ConfigurationTests(unittest.TestCase):
    def test_explicit_environment_selects_fixed_operator_account(self):
        values = {'INBOXTETHER_IMAP_HOST': 'imap.example.org',
                  'INBOXTETHER_ACCOUNT': 'reader@example.org',
                  'INBOXTETHER_PASSWORD_FILE': '/private-example/imap-secret'}
        with patch.dict(os.environ, values, clear=True):
            module = runpy.run_path(str(SERVER), run_name='configuration_probe')
        self.assertEqual(module['HOST'], values['INBOXTETHER_IMAP_HOST'])
        self.assertEqual(module['ACCOUNT'], values['INBOXTETHER_ACCOUNT'])
        self.assertEqual(str(module['PASSWORD_FILE']), values['INBOXTETHER_PASSWORD_FILE'])

    def test_unconfigured_defaults_are_nonproduction_examples(self):
        with patch.dict(os.environ, {}, clear=True):
            module = runpy.run_path(str(SERVER), run_name='configuration_probe')
        self.assertEqual(module['HOST'], 'mail.example.com')
        self.assertEqual(module['ACCOUNT'], 'user@example.com')
        self.assertEqual(str(module['PASSWORD_FILE']), '/etc/inboxtether-mcp/imap-password')


if __name__ == '__main__':
    unittest.main()
