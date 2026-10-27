import asyncio
import dataclasses
import imaplib
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from organizer.imap_adapter import BODY, HEADER, METADATA, GuardedIMAP, IMAPMailbox, quoted
from organizer.ipc import Broker, Client, MAX_REQUEST, peer_uid, receive, send
from organizer.model import CATEGORIES, Message, OrganizerError
from test_organizer import mail



class GuardTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(GuardedIMAP)

    def test_every_other_imap_command_denied(self):
        for command in set(imaplib.Commands) - GuardedIMAP.ALLOWED:
            with self.subTest(command=command), self.assertRaises(OrganizerError): self.client._command(command, '1')

    def test_all_unapproved_uid_mutations_denied(self):
        for operation in ('MOVE', 'COPY', 'STORE', 'EXPUNGE', 'APPEND', 'DELETE', 'CREATE', 'move', 'copy'):
            with self.subTest(operation=operation), self.assertRaises(OrganizerError):
                self.client._command('UID', operation, '1', 'Industry')

    def test_marking_fetches_and_macros_denied(self):
        for fetch in ('BODY[]', '(UID BODY[])', 'RFC822', '(RFC822.TEXT)', 'ALL', 'FULL', '(BODY.PEEK[] FLAGS)', '(UID BODY.PEEK[1])'):
            with self.subTest(fetch=fetch), self.assertRaises(OrganizerError):
                self.client._command('UID', 'FETCH', '1', fetch)

    def test_sequence_sets_and_search_injection_denied(self):
        for uid in ('1:*', '*', '1,2', '1\r\nEXPUNGE', '0'):
            with self.subTest(uid=uid), self.assertRaises(OrganizerError): self.client._command('UID', 'FETCH', uid, BODY)
        with self.assertRaises(OrganizerError): self.client._command('UID', 'SEARCH', None, 'TEXT', 'malicious')

    def test_select_requires_one_use_exact_inbox_permit(self):
        with self.assertRaises(OrganizerError): self.client._command('SELECT', '"INBOX"')
        self.client._select_permit = True
        with self.assertRaises(OrganizerError): self.client._command('SELECT', '"Drafts"')
        with self.assertRaises(OrganizerError): self.client._command('SELECT', '"INBOX"')

    def test_move_permit_consumed_even_on_network_failure(self):
        self.client._move_permit = ('1', '"Industry"')
        with patch.object(imaplib.IMAP4, '_command', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError): self.client._command('UID', 'MOVE', '1', '"Industry"')
        with self.assertRaises(OrganizerError): self.client._command('UID', 'MOVE', '1', '"Industry"')

    def test_move_permit_cannot_change_uid_or_destination(self):
        for args in [('MOVE', '2', '"Industry"'), ('MOVE', '1', '"Suppliers"'), ('MOVE', '1,2', '"Industry"')]:
            self.client._move_permit = ('1', '"Industry"')
            with self.subTest(args=args), self.assertRaises(OrganizerError): self.client._command('UID', *args)

    def test_nonmarking_metadata_and_peek_accepted(self):
        with patch.object(imaplib.IMAP4, '_command', return_value='synthetic') as dispatch:
            self.client._command('UID', 'FETCH', '1', HEADER)
            self.client._command('UID', 'FETCH', '1', METADATA)
            self.assertEqual(dispatch.call_count, 2)

    def test_live_adapter_disabled_by_default(self):
        with self.assertRaises(OrganizerError): IMAPMailbox('mail.example.com', 'owner@example.com', '/not-used')

    def test_only_fixed_six_folders_accepted(self):
        for name in ('Trash', 'Drafts', 'INBOX/Industry', 'industry', 'Industry\r\nDELETE'):
            with self.subTest(name=name), self.assertRaises(OrganizerError): quoted(name)

    def test_wire_literal_bound(self):
        with self.assertRaises(OrganizerError): self.client.read(1_048_577)

    def test_reader_mutation_guard_remains_enabled(self):
        self.assertNotIn("APPEND",GuardedIMAP.ALLOWED)
        self.assertNotIn("STORE",GuardedIMAP.ALLOWED)

class ScriptedIMAP:
    """Fabricated wire-response adapter. Records commands; never opens a socket."""
    def __init__(self, message=None):
        self.message = message or mail()
        self.commands = []
        self.mapping = b'200 1 55'
        self.bad_uid = False
        self.flags = ' '.join(self.message.flags)
        self.selected = None

    def uid(self, operation, *args):
        self.commands.append(('UID', operation, *args))
        if operation == 'FETCH':
            uid = 9 if self.bad_uid else int(args[0])
            raw_header, body = self.message.raw.split(b'\r\n\r\n', 1)
            if args[1] == METADATA:
                tree = '("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" ' + str(len(body)) + ' 1 NIL NIL NIL NIL)'
                return 'OK', [f'999 (FLAGS ({self.flags}) UID {uid} RFC822.SIZE {len(self.message.raw)} INTERNALDATE "{self.message.internaldate}" BODYSTRUCTURE {tree})'.encode()]
            import re
            if args[1] == HEADER:
                payload, section, offset = raw_header + b'\r\n\r\n', 'HEADER', 0
            elif 'PEEK[1]' in args[1]:
                payload, section, offset = body, '1', 0
            else:
                offset, count = map(int, re.search(r'<([0-9]+)\.([0-9]+)>', args[1]).groups())
                payload, section = self.message.raw[offset:offset+count], ''
            return 'OK', [(f'999 (UID {uid} BODY[{section}]<{offset}> {{{len(payload)}}}'.encode(), payload), b')']
        if operation == 'SEARCH': return 'OK', [b'1 55 999']
        if operation == 'MOVE': return 'OK', [b'moved']
        raise AssertionError('unexpected command')

    def select(self, name, readonly=True):
        self.commands.append(('EXAMINE' if readonly else 'SELECT', name)); self.selected = name
        return 'OK', [b'1']

    def response(self, name):
        if name == 'UIDVALIDITY': return name, [b'100' if self.selected == '"INBOX"' else b'200']
        if name == 'UIDNEXT': return name, [b'1000']
        if name == 'COPYUID': return name, [self.mapping]
        raise AssertionError('unexpected response')

    def myrights(self, name):
        self.commands.append(('MYRIGHTS', name))
        return 'OK', [name.encode() + b' lriswte']

class AdapterTests(unittest.TestCase):
    def test_metadata_identity_not_sequence_number(self):
        c = ScriptedIMAP()
        m = IMAPMailbox._fetch(c, 1)
        self.assertEqual(m.uid, 1); self.assertEqual(m.view.sections[0].payload, c.message.raw.split(b'\r\n\r\n',1)[1])
        self.assertEqual(c.commands[1][-1], HEADER)

    def test_wrong_uid_fails(self):
        c = ScriptedIMAP(); c.bad_uid = True
        with self.assertRaises(OrganizerError): IMAPMailbox._fetch(c, 1)

    def test_metadata_flags_and_internaldate_preserved(self):
        c = ScriptedIMAP(mail(flags=('\\Seen', '$Forwarded')))
        m = IMAPMailbox._fetch(c, 1)
        self.assertEqual(m.flags, ('\\Seen', '$Forwarded')); self.assertEqual(m.internaldate, c.message.internaldate)

    def test_nonexistent_uid(self):
        c = ScriptedIMAP()
        with patch.object(c, 'uid', return_value=('OK', [None])): self.assertIsNone(IMAPMailbox._fetch(c, 1))

    def adapter(self, client):
        from contextlib import contextmanager
        @contextmanager
        def connection(): yield client
        adapter = object.__new__(IMAPMailbox)
        adapter.connection = connection
        return adapter

    def test_move_sequence_has_no_copy_store_expunge(self):
        c = ScriptedIMAP(); adapter = self.adapter(c)
        self.assertEqual(adapter.move(100, 1, 'Industry', 200, evidence=IMAPMailbox._fetch(c, 1).evidence(), on_prepared=lambda _: None, expires_at=time.time() + 10), (200, 55))
        operations = [command[:2] for command in c.commands]
        self.assertIn(('SELECT', '"INBOX"'), operations)
        self.assertIn(('UID', 'MOVE'), operations)
        self.assertFalse(any(op in str(c.commands) for op in ('COPY', 'STORE', 'EXPUNGE', 'CLOSE')))

    def test_approval_rechecked_immediately_before_move(self):
        c = ScriptedIMAP(); adapter = self.adapter(c)
        with self.assertRaises(OrganizerError): adapter.move(100, 1, 'Industry', 200, evidence=IMAPMailbox._fetch(c, 1).evidence(), on_prepared=lambda _: None, expires_at=0)
        self.assertFalse(any(cmd[:2] == ('UID', 'MOVE') for cmd in c.commands))

    def test_source_rechecked_on_same_move_connection(self):
        c = ScriptedIMAP(); adapter = self.adapter(c)
        changed = {**c.message.evidence(), 'sha256': '0' * 64}
        with self.assertRaises(OrganizerError): adapter.move(100, 1, 'Industry', 200, evidence=changed, on_prepared=lambda _: None, expires_at=time.time() + 10)
        self.assertFalse(any(cmd[:2] == ('UID', 'MOVE') for cmd in c.commands))

    def test_missing_or_wrong_copyuid_refused(self):
        for mapping in (None, b'200 2 55', b'201 1 55', b'200 1:2 55:56', b'200 1 0'):
            c = ScriptedIMAP(); c.mapping = mapping
            with self.subTest(mapping=mapping), self.assertRaises(OrganizerError):
                self.adapter(c).move(100, 1, 'Industry', 200, evidence=IMAPMailbox._fetch(c, 1).evidence(), on_prepared=lambda _: None, expires_at=time.time() + 10)

    def test_missing_flag_rights_refused(self):
        c = ScriptedIMAP()
        with patch.object(c, 'myrights', return_value=('OK', [b'"Industry" lri'])):
            with self.assertRaises(OrganizerError): IMAPMailbox._rights(c, 'Industry', 'lrisw')

    def test_bounded_inventory_rejects_out_of_range(self):
        with self.assertRaises(OrganizerError): IMAPMailbox._uids(ScriptedIMAP(), 2, 1000)
