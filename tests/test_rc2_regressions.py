"""Focused regressions for the four demonstrated Linux release blockers."""
import ast
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import approval_web as web
from contract_support import contract_hash
from draft_assistant import DraftError
from journal import Refused
import socket_access


class ListenerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)/'runtime'
        self.runtime.mkdir(mode=0o750)
        self.path = self.runtime/'web.sock'

    def raw_socket(self, live=False):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        self.path.chmod(0o660)
        if live:
            listener.listen(1)
        self.addCleanup(listener.close)
        return listener

    def test_normal_close_removes_only_owned_endpoint_and_restarts(self):
        for _ in range(3):
            with web.private_listener(self.path):
                self.assertTrue(self.path.exists())
                self.assertEqual(Path(str(self.path)+'.lock').stat().st_mode & 0o777, 0o600)
            self.assertFalse(self.path.exists())

    def test_disconnected_owned_socket_recovers_without_manual_cleanup(self):
        self.raw_socket().close()
        with web.private_listener(self.path) as listener:
            self.assertEqual(listener.family, socket.AF_UNIX)
        self.assertFalse(self.path.exists())

    def test_live_unlocked_endpoint_is_preserved(self):
        self.raw_socket(live=True)
        before = self.path.stat()
        with self.assertRaises(DraftError):
            web.private_listener(self.path)
        self.assertEqual(self.path.stat().st_ino, before.st_ino)

    def test_regular_file_and_symlink_are_preserved(self):
        target=self.runtime/'target';target.write_text('synthetic')
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:self.path.symlink_to(target)
                else:self.path.write_text('synthetic')
                with self.assertRaises(DraftError):web.private_listener(self.path)
                self.assertEqual(target.read_text(),'synthetic')
                self.assertTrue(self.path.exists())
                self.path.unlink()

    def test_wrong_socket_mode_is_preserved(self):
        self.raw_socket().close();self.path.chmod(0o600)
        with self.assertRaises(DraftError):web.private_listener(self.path)
        self.assertTrue(self.path.exists())

    def test_lock_symlink_is_not_followed(self):
        target=self.runtime/'target';target.write_text('synthetic')
        Path(str(self.path)+'.lock').symlink_to(target)
        with self.assertRaises(OSError):web.private_listener(self.path)
        self.assertEqual(target.read_text(),'synthetic')

    def test_cleanup_preserves_replaced_path(self):
        with web.private_listener(self.path):
            self.path.unlink();self.path.write_text('replacement')
        self.assertEqual(self.path.read_text(),'replacement')


class PortableContractTests(unittest.TestCase):
    def test_empty_version_field_ignored_but_signature_and_body_changes_fail(self):
        root=Path(__file__).resolve().parents[1]
        frozen=json.loads((root/'tests/reader-draft-contract.json').read_text())
        functions={n.name:n for n in ast.parse((root/'server.py').read_text()).body
                   if isinstance(n,ast.FunctionDef) and n.name in frozen}
        self.assertEqual(len(functions),8)
        for name,node in functions.items():
            with self.subTest(name=name):
                self.assertEqual(contract_hash(node),frozen[name])
                if 'type_params' not in node._fields:node._fields+=('type_params',)
                node.type_params=[]
                self.assertEqual(contract_hash(node),frozen[name])
                node.type_params=[ast.Name(id='Changed',ctx=ast.Load())]
                self.assertNotEqual(contract_hash(node),frozen[name])
                node.type_params=[];node.args.kwonlyargs.append(ast.arg(arg='changed'))
                node.args.kw_defaults.append(None)
                self.assertNotEqual(contract_hash(node),frozen[name])
                node.args.kwonlyargs.pop();node.args.kw_defaults.pop()
                node.body.append(ast.Pass())
                self.assertNotEqual(contract_hash(node),frozen[name])


class ExactSocketPeerTests(unittest.TestCase):
    def test_mismatched_web_uid_and_duplicate_peers_fail_before_acl_changes(self):
        for settings in ({'reader_uid':1000,'web_uid':1001},
                         {'reader_uid':1002,'web_uid':1002}):
            with self.subTest(settings=settings),patch('socket_access.pwd.getpwnam',
                 side_effect=lambda name:SimpleNamespace(pw_uid=1002 if name=='inboxtether-web' else 1003)):
                runner=Mock()
                with self.assertRaises(Refused):socket_access.grant('broker',settings,runner=runner)
                runner.assert_not_called()

    def test_acl_waits_until_stale_endpoint_is_replaced_and_listening(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime=Path(temp)/'runtime';runtime.mkdir(mode=0o750)
            path=runtime/'moves.sock'
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as endpoint:
                endpoint.bind(str(path));path.chmod(0o660)
            owner=os.geteuid();runner=Mock();pause=Mock();readiness=iter([False,True])
            def probe(path):
                runner.assert_not_called()
                return next(readiness)
            with patch('socket_access.pwd.getpwnam',side_effect=lambda name:SimpleNamespace(pw_uid=1002 if name=='inboxtether-web' else owner)),patch('socket_access.socket_ready',side_effect=probe):
                socket_access.grant('broker',{'reader_uid':1001,'web_uid':1002},base=runtime,
                                    runner=runner,sleep=pause,clock=lambda:0)
            self.assertEqual(pause.call_count,1)
            self.assertEqual(runner.call_count,4)
