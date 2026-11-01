"""Published completion guidance; synthetic metadata inspection, no tool calls."""
import asyncio
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
import move_connection


ROOT = Path(__file__).resolve().parents[1]


class DiscoveryCompletionContractTests(unittest.TestCase):
    def test_exported_description_requires_all_completion_evidence(self):
        server = FastMCP('synthetic-completion-contract')
        with patch.dict(os.environ, {'INBOXTETHER_MOVES': '1',
                                   'INBOXTETHER_MOVE_SOCKET': '/synthetic/no-socket'}):
            move_connection.register(server)
        tool = asyncio.run(server.list_tools())[0]
        description = ' '.join(tool.description.split())
        for text in ('After processing the final pending message, call next again',
                     'SAME response', 'no UID (uid field absent)', 'remaining=0',
                     'No new messages; organization runs only on request.',
                     'automatic Keep is NOT fresh discovery completion',
                     'repeat the final discovery check', 'read scope and run limits',
                     'report discovery incomplete', 'never retry uncertain operations',
                     'caught up as of the final discovery check',
                     'does not continuously monitor', 'Handle my email',
                     'enabled owner policy or exact-manifest approval'):
            with self.subTest(text=text):
                self.assertIn(text, description)
        # The guidance is near the start of the real MCP definition, not only in docs.
        self.assertLess(description.index('DISCOVERY COMPLETION'), 100)

    def test_both_workflow_guides_include_completion_and_failure_rules(self):
        for name in ('WORKFLOWS.md', 'AUTOMATIC_FILING.md'):
            text = ' '.join((ROOT / name).read_text().split())
            for phrase in ('No UID', 'remaining=0',
                           'No new messages; organization runs only on request.',
                           'automatic Keep', 'repeat the final discovery check',
                           'incomplete', 'caught up as of the final discovery check',
                           'does not continuously monitor', 'Handle my email'):
                with self.subTest(document=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_example_preserves_authorization_and_safe_stopping(self):
        text = (ROOT / 'WORKFLOWS.md').read_text()
        example = text.split('Example user prompt:', 1)[1].split('## Trust choices', 1)[0]
        for phrase in ('Discover', 'classify', 'customer and uncertainty protections',
                       'configured owner policy or exact-manifest approval',
                       'Stop on errors or uncertain outcomes', 'verified filing results'):
            self.assertIn(phrase, example)


if __name__ == '__main__':
    unittest.main()
