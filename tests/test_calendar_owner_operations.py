import asyncio
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from icalendar import Calendar
from mcp.server.fastmcp import FastMCP

from calendar_accounts import CalendarAccounts
from calendar_create import CreateTransport
from calendar_invitations import InvitationPolicy, attendee_addresses, email_address, matches_invitation, policy_from_config
from calendar_owner_connection import create_server
from calendar_owner_operations import OwnerOperations, OwnerStore, normalized_event
from sogo_calendar import CalendarError, SogoCalendar
from test_calendar_create import EVENT, REQUEST
from test_calendar_occurrences import SERIES
from test_sogo_calendar import HOME, PERSONAL, SHARED


def account(key, domain, *, writable=True):
    return {
        'id': key, 'home_url': 'https://' + domain + HOME, 'username': 'user@' + domain,
        'password_file': '/private/' + key + '-read', 'write_password_file': '/private/' + key + '-write',
        'read_ids': [PERSONAL], 'full_visibility_ids': [PERSONAL] if writable else [],
        'create_ids': [PERSONAL] if writable else [], 'update_ids': [PERSONAL] if writable else [],
        'cancel_ids': [PERSONAL] if writable else [], 'aliases': {key.upper(): PERSONAL},
    }


def config():
    return [account('jtf', 'mail.example.com'), account('other', 'mail.example.net', writable=False)]


class OwnerCalendarAccountTests(unittest.TestCase):
    @patch.object(SogoCalendar, 'calendars', autospec=True)
    def test_two_domains_discover_the_same_path_without_leaking_unlisted_calendars(self, discover):
        discover.return_value = {PERSONAL: {'name': 'Personal'}, SHARED: {'name': 'Hidden'}}
        accounts = CalendarAccounts(json.dumps(config()))
        calendars = accounts.calendars()
        self.assertEqual(set(calendars), {'jtf:' + PERSONAL, 'other:' + PERSONAL})
        self.assertEqual(calendars[accounts.resolve('jTf')]['aliases'], ['JTF'])
        self.assertEqual([call.args[0].password_file for call in discover.call_args_list],
                         ['/private/jtf-read', '/private/other-read'])
        with self.assertRaisesRegex(CalendarError, 'distinct'):
            accounts.selection(['JTF', 'jtf:' + PERSONAL])
        with self.assertRaisesRegex(CalendarError, 'outside'):
            accounts.resolve('jtf:' + SHARED)

    def test_account_configuration_rejects_unsafe_aliases_and_permissions(self):
        for change in (
            {'aliases': {'jTf': PERSONAL}}, {'create_ids': [SHARED]}, {'update_ids': [PERSONAL]},
            {'home_url': 'http://example.net' + HOME}, {'password_file': 'relative'},
            {'password_file': '/private/jtf-read'},
        ):
            rows = config()
            rows[1].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(CalendarError, 'configuration'):
                CalendarAccounts(json.dumps(rows))

    @patch.object(SogoCalendar, 'calendars', autospec=True, return_value={PERSONAL: {'name': 'Personal'}})
    @patch.object(SogoCalendar, 'complete_resources', autospec=True, return_value=[])
    def test_normal_owner_tools_route_reads_and_fail_closed_availability(self, resources, _):
        with patch.dict(os.environ, {'INBOXTETHER_CALDAV_ACCOUNTS': json.dumps(config())}, clear=True):
            app = create_server()
        self.assertNotIn('calendar_commit_create', {tool.name for tool in asyncio.run(app.list_tools())})
        window = {'start': '2026-11-01T00:00:00Z', 'end': '2026-11-03T00:00:00Z'}
        result = asyncio.run(app.call_tool('calendar_search_events', {
            **window, 'calendar_ids': ['JTF', 'OTHER'], 'text': 'synthetic',
        }))
        self.assertIn('events', str(result))
        self.assertEqual([call.args[0].host for call in resources.call_args_list],
                         ['mail.example.com', 'mail.example.net'])
        resources.reset_mock()
        with self.assertRaisesRegex(Exception, 'full-visibility'):
            asyncio.run(app.call_tool('calendar_free_busy', {**window, 'calendar_ids': ['JTF', 'OTHER']}))
        resources.assert_not_called()

    def test_write_gates_are_independent_on_the_owner_worker(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'INBOXTETHER_CALDAV_ACCOUNTS': json.dumps(config()), 'INBOXTETHER_CALDAV_RADAR_STATE_DIR': directory,
        }, clear=True):
            flags = {'create': {'INBOXTETHER_CALDAV_CREATE_ENABLED': '1', 'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED': '1'},
                     'update': {'INBOXTETHER_CALDAV_RADAR_UPDATE_ENABLED': '1',
                                'INBOXTETHER_CALDAV_RADAR_UPDATE_CONDITIONAL_VERIFIED': '1'},
                     'cancel': {'INBOXTETHER_CALDAV_RADAR_CANCEL_ENABLED': '1',
                                'INBOXTETHER_CALDAV_RADAR_CANCEL_CONDITIONAL_VERIFIED': '1'}}
            for action, enabled in flags.items():
                with self.subTest(action=action), patch.dict(os.environ, enabled):
                    tools = {tool.name: tool for tool in asyncio.run(create_server().list_tools())}
                    self.assertEqual({name for name in tools if name.startswith('calendar_commit_')},
                                     {'calendar_commit_' + action})
                    self.assertIn('calendar_reconcile_operation', tools)
                    self.assertFalse(tools['calendar_commit_' + action].annotations.readOnlyHint)
                    self.assertEqual(tools['calendar_commit_' + action].inputSchema['required'], ['operation_id'])

    def test_mutation_registration_refuses_unqualified_conditional_methods(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'INBOXTETHER_CALDAV_ACCOUNTS': json.dumps(config()),
            'INBOXTETHER_CALDAV_RADAR_STATE_DIR': directory,
        }, clear=True):
            for action in ('update', 'cancel'):
                with self.subTest(action=action), patch.dict(os.environ, {
                    'INBOXTETHER_CALDAV_RADAR_' + action.upper() + '_ENABLED': '1',
                }), self.assertRaisesRegex(CalendarError, 'has not been validated'):
                    create_server()

    @patch.object(SogoCalendar, 'calendars', return_value={PERSONAL: {'name': 'Personal'}})
    @patch.object(SogoCalendar, 'complete_resources', autospec=True)
    def test_multi_account_availability_preserves_occurrence_expansion(self, resources, _):
        rows = config()
        rows[1]['full_visibility_ids'] = [PERSONAL]
        resources.side_effect = lambda client, _: [SERIES] if client.host.endswith('.net') else []
        with patch.dict(os.environ, {'INBOXTETHER_CALDAV_ACCOUNTS': json.dumps(rows)}, clear=True):
            app = create_server()
        result = asyncio.run(app.call_tool('calendar_free_busy', {
            'calendar_ids': ['JTF', 'OTHER'], 'start': '2026-11-03T21:00:00Z', 'end': '2026-11-03T23:00:00Z',
        }))
        self.assertIn('2026-11-03T22:00:00+00:00', str(result))
        self.assertIn('other:' + PERSONAL, str(result))
        self.assertNotIn('Moved appointment', str(result))


class OwnerCalendarOperationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = OwnerStore(Path(temporary.name))
        self.accounts = CalendarAccounts(json.dumps(config()))
        self.service = OwnerOperations(self.accounts, self.store, {'create', 'update', 'cancel'}, (20, 50))
        self.events = {}
        self.writes = []
        self.forced = None
        self.read_status = None
        self.enterContext(patch.object(CreateTransport, 'calendar_path', autospec=True, side_effect=lambda _, path: path))
        self.enterContext(patch.object(CreateTransport, 'exchange_resource', autospec=True, side_effect=self.wire))

    def wire(self, transport, method, _calendar_id, path, raw=None, *, etag=None, scheduling=False):
        self.assertEqual(str(transport.password_file), '/private/jtf-write')
        before, version = self.events.get(path, (None, None))
        if method == 'GET':
            return self.read_status or (200 if before else 404), before, version
        self.writes.append((method, path, etag))
        if self.forced:
            return self.forced(method, path, raw)
        if method == 'DELETE':
            self.assertEqual(etag, version)
            del self.events[path]
            return 204, None, None
        if etag is not None:
            self.assertEqual(etag, version)
        self.events[path] = raw, '"version-2"' if before else '"version-1"'
        return (204 if before else 201), None, None

    def prepare(self, action='create', request_id=REQUEST, **changes):
        inputs = {} if action == 'cancel' else {'event': EVENT}
        return self.service.prepare(action, request_id, 'JTF', **{**inputs, **changes})['proposal']

    def create(self):
        proposal = self.prepare()
        self.assertEqual(self.service.commit(proposal['operation_id'], 'create')['status'], 'verified')
        return proposal

    def test_create_persists_random_id_and_readback_survives_replay(self):
        with patch('calendar_owner_operations.secrets.token_hex', return_value='c' * 64) as random:
            proposal = self.prepare()
        random.assert_called_once_with(32)
        self.assertEqual(self.prepare(), proposal)
        self.assertEqual(proposal['event_id'], PERSONAL + 'c' * 64 + '.ics')
        self.assertNotEqual(proposal['operation_id'], 'c' * 64)
        with self.assertRaisesRegex(CalendarError, 'different calendar operation'):
            self.prepare(event={**EVENT, 'title': 'Other'})
        receipt = self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual(receipt['status'], 'verified')
        self.assertFalse(receipt['human_approval_verified'])
        self.assertEqual(receipt['version'], '"version-1"')
        self.assertEqual(self.writes, [('PUT', proposal['event_id'], None)])
        self.assertEqual(self.service.commit(proposal['operation_id'], 'create'), receipt)
        del self.events[proposal['event_id']]
        checked = self.service.commit(proposal['operation_id'], None, write=False)
        self.assertEqual((checked['status'], checked['observation'], checked['current_observation']),
                         ('verified', 'matches', 'missing'))
        self.assertEqual(len(self.writes), 1)

    def test_visibility_and_availability_overrides_are_preserved_in_owner_payloads(self):
        number = 0
        for all_day in (False, True):
            for classification in ('PUBLIC', 'PRIVATE', 'CONFIDENTIAL'):
                for transparency in ('OPAQUE', 'TRANSPARENT'):
                    number += 1
                    event = {**EVENT, 'classification': classification, 'transparency': transparency}
                    if all_day:
                        event.update(all_day=True, start='2026-12-29', end='2026-12-30')
                    with self.subTest(all_day=all_day, classification=classification, transparency=transparency):
                        proposal = self.prepare(request_id=f'synthetic-visibility-{number:04d}', event=event)
                        stored = self.store.get(proposal['operation_id'])
                        item = Calendar.from_ical(stored['raw']).walk('VEVENT')[0]
                        self.assertEqual((str(item['CLASS']), str(item['TRANSP'])), (classification, transparency))
                        self.assertEqual((proposal['event']['classification'], proposal['event']['transparency']),
                                         (classification, transparency))
        self.assertEqual(self.writes, [])

    def test_persisted_private_proposal_and_receipt_are_not_redefaulted_on_reopen(self):
        private_event = {**EVENT, 'classification': 'PRIVATE', 'transparency': 'TRANSPARENT'}
        proposal = self.prepare(event=private_event)
        original = self.store.get(proposal['operation_id'])
        reopened = OwnerOperations(self.accounts, OwnerStore(self.store.directory), {'create'}, (20, 50))
        receipt = reopened.commit(proposal['operation_id'], 'create')
        self.assertEqual(receipt['status'], 'verified')
        current = self.store.get(proposal['operation_id'])
        self.assertEqual(current['manifest'], original['manifest'])
        self.assertEqual(current['raw'], original['raw'])
        item = Calendar.from_ical(self.events[proposal['event_id']][0]).walk('VEVENT')[0]
        self.assertEqual((str(item['CLASS']), str(item['TRANSP'])), ('PRIVATE', 'TRANSPARENT'))
        self.assertEqual(reopened.commit(proposal['operation_id'], 'create'), receipt)
        # A repeat prepare with omitted fields cannot reinterpret a saved Private proposal.
        with self.assertRaisesRegex(CalendarError, 'different calendar operation'):
            reopened.prepare('create', REQUEST, 'JTF', event=EVENT)
        self.assertEqual(self.store.get(proposal['operation_id'])['raw'], original['raw'])
        self.assertEqual(len(self.writes), 1)

    def test_create_and_reconcile_through_private_mcp_tools(self):
        with patch.dict(os.environ, {
            'INBOXTETHER_CALDAV_ACCOUNTS': json.dumps(config()),
            'INBOXTETHER_CALDAV_RADAR_STATE_DIR': str(self.store.directory),
            'INBOXTETHER_CALDAV_CREATE_ENABLED': '1', 'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED': '1',
        }, clear=True):
            app = create_server()
        def call(name, arguments):
            content = asyncio.run(app.call_tool(name, arguments))
            return json.loads(content[0].text)

        result = call('calendar_prepare_create', {'calendar_id': 'JTF', 'request_id': REQUEST, 'event': EVENT})
        key = result['proposal']['operation_id']
        self.assertEqual(self.writes, [])
        receipt = call('calendar_commit_create', {'operation_id': key})
        self.assertEqual(receipt['status'], 'verified')
        readback = call('calendar_reconcile_operation', {'operation_id': key})
        self.assertEqual(readback['current_observation'], 'matches')
        self.assertEqual(len(self.writes), 1)

    def test_all_day_duration_and_timed_duration_at_dst(self):
        all_day = {**EVENT, 'start': '2026-11-01', 'end': None, 'duration_days': 2, 'all_day': True}
        proposal = self.prepare(event=all_day)
        self.assertEqual(self.service.commit(proposal['operation_id'], 'create')['status'], 'verified')
        stored = Calendar.from_ical(self.events[proposal['event_id']][0]).walk('VEVENT')[0]
        self.assertEqual(stored.decoded('DTEND'), date(2026, 11, 3))
        self.assertEqual(normalized_event({**EVENT, 'end': None, 'duration_minutes': 60})['end'],
                         '2026-11-01T01:30:00-06:00')
        for invalid in ({**EVENT, 'duration_minutes': 60}, {**all_day, 'attendees': ['Name <n@example.org>']},
                        {**EVENT, 'timezone': 'No/SuchZone', 'end': None, 'duration_minutes': 30}):
            with self.assertRaises(CalendarError):
                normalized_event(invalid)

    def test_occupied_url_and_read_failure_never_put(self):
        proposal = self.prepare()
        self.read_status = 403
        with self.assertRaisesRegex(CalendarError, 'absent'):
            self.service.commit(proposal['operation_id'], 'create')
        self.read_status = None
        self.events[proposal['event_id']] = b'occupied', '"occupied"'
        receipt = self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual((receipt['status'], receipt['attempts'], self.writes), ('conflict', 0, []))

    def test_lost_response_without_event_cannot_retry_even_after_reopen(self):
        proposal = self.prepare()
        self.forced = MagicMock(side_effect=CalendarError('synthetic loss'))
        self.assertEqual(self.service.commit(proposal['operation_id'], 'create')['status'], 'uncertain')
        reopened = OwnerOperations(self.accounts, OwnerStore(self.store.directory), {'create'}, (20, 50))
        self.assertEqual(reopened.commit(proposal['operation_id'], 'create')['attempts'], 1)
        checked = reopened.commit(proposal['operation_id'], None, write=False)
        self.assertEqual((checked['status'], checked['observation'], checked['retry_allowed']),
                         ('uncertain', 'missing', False))
        self.assertEqual(len(self.writes), 1)

    def test_lost_response_with_event_verifies_observed_state_only(self):
        proposal = self.prepare()

        def lose(_method, path, raw):
            self.events[path] = raw, '"created"'
            raise CalendarError('synthetic loss')

        self.forced = lose
        receipt = self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual((receipt['status'], receipt['outcome'], receipt['observation']),
                         ('verified', 'unknown', 'matches'))
        self.assertEqual(len(self.writes), 1)

    def test_update_like_create_response_blocks_account_durably(self):
        first = self.prepare()
        second = self.prepare(request_id='synthetic-request-0002')
        self.forced = lambda *_: (204, None, None)
        self.assertEqual(self.service.commit(first['operation_id'], 'create')['status'], 'integrity_failure')
        reopened = OwnerOperations(self.accounts, OwnerStore(self.store.directory), {'create'}, (20, 50))
        with self.assertRaisesRegex(CalendarError, 'blocked'):
            reopened.commit(second['operation_id'], 'create')
        self.assertEqual(len(self.writes), 1)

    def test_update_and_cancel_use_strong_version_and_verify(self):
        created = self.create()
        event_id = created['event_id']
        edited = {**EVENT, 'title': 'Rescheduled', 'location': 'Room 5'}
        update = self.prepare('update', 'synthetic-request-0002', event_id=event_id, event=edited)
        self.assertEqual(update['before']['title'], EVENT['title'])
        self.assertEqual(self.service.commit(update['operation_id'], 'update')['status'], 'verified')
        cancel = self.prepare('cancel', 'synthetic-request-0003', event_id=event_id)
        receipt = self.service.commit(cancel['operation_id'], 'cancel')
        self.assertEqual((receipt['status'], receipt['observation']), ('verified', 'missing'))
        self.assertEqual(self.writes, [('PUT', event_id, None), ('PUT', event_id, '"version-1"'),
                                      ('DELETE', event_id, '"version-2"')])

    def test_edit_and_cancel_reject_changed_or_missing_targets_before_wire(self):
        created = self.create()
        event_id = created['event_id']
        update = self.prepare('update', 'synthetic-request-0002', event_id=event_id,
                              event={**EVENT, 'title': 'Different'})
        cancel = self.prepare('cancel', 'synthetic-request-0003', event_id=event_id)
        # Same validator with different content must still fail the local preflight.
        content, etag = self.events[event_id]
        self.events[event_id] = content + b'\r\n', etag
        self.assertEqual(self.service.commit(update['operation_id'], 'update')['status'], 'conflict')
        del self.events[event_id]
        self.assertEqual(self.service.commit(cancel['operation_id'], 'cancel')['status'], 'conflict')
        self.assertEqual(len(self.writes), 1)

    def test_server_precondition_failure_is_conflict_without_retry(self):
        created = self.create()
        proposal = self.prepare('cancel', 'synthetic-request-0002', event_id=created['event_id'])
        self.forced = lambda *_: (412, None, None)
        self.assertEqual(self.service.commit(proposal['operation_id'], 'cancel')['status'], 'conflict')
        self.assertEqual(self.service.commit(proposal['operation_id'], 'cancel')['attempts'], 1)
        self.assertIn(created['event_id'], self.events)

    def test_held_lock_and_expiry_block_before_preflight(self):
        from datetime import datetime, timezone

        proposal = self.prepare()
        with self.store.locked(), self.assertRaisesRegex(CalendarError, 'in progress'):
            self.service.commit(proposal['operation_id'], 'create')
        with patch('calendar_owner_operations.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromtimestamp(proposal['expires_at'], timezone.utc)
            with self.assertRaisesRegex(CalendarError, 'expired'):
                self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual(self.writes, [])

    def test_weak_version_unmanaged_event_and_account_allowlist_are_refused(self):
        with self.assertRaisesRegex(CalendarError, 'allowlisted'):
            self.service.prepare('create', REQUEST, 'OTHER', event=EVENT)
        with self.assertRaisesRegex(CalendarError, 'created by this worker'):
            self.prepare('cancel', event_id=PERSONAL + 'unmanaged.ics')
        created = self.create()
        event_id = created['event_id']
        self.events[event_id] = self.events[event_id][0], 'W/"version-1"'
        with self.assertRaisesRegex(CalendarError, 'strong version'):
            self.prepare('cancel', 'synthetic-request-0002', event_id=event_id)

    def test_quota_is_shared_and_audit_uses_metadata_only(self):
        self.service.limits = (1, 1)
        created = self.create()
        cancel = self.prepare('cancel', 'synthetic-request-0002', event_id=created['event_id'])
        with self.assertRaisesRegex(CalendarError, 'rate limit'):
            self.service.commit(cancel['operation_id'], 'cancel')
        with self.store.db() as db:
            rows = [tuple(row) for row in db.execute('SELECT * FROM radar_create_audit')]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3:], ('accepted', 'verified'))
        self.assertNotIn(EVENT['title'], repr(rows))
        self.assertNotIn('private', repr(rows))

    def test_update_preserves_identity_and_unrelated_fields_with_exact_before_after(self):
        created = self.create()
        event_id = created['event_id']
        calendar = Calendar.from_ical(self.events[event_id][0])
        item = calendar.walk('VEVENT')[0]
        item.add('X-LOCAL-NOTE', 'Keep this')
        item.add('SEQUENCE', 4)
        self.events[event_id] = calendar.to_ical(), '"external-version"'
        edited = {**EVENT, 'title': 'Lunch moved', 'start': '2026-12-18T13:00:00-06:00',
                  'end': None, 'duration_minutes': 60, 'location': 'New room',
                  'description': 'Reviewed details', 'classification': 'CONFIDENTIAL',
                  'transparency': 'TRANSPARENT'}
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=event_id, event=edited)
        self.assertEqual(proposal['before']['timezone'], 'America/Chicago')
        self.assertEqual(proposal['before']['start'], EVENT['start'])
        self.assertEqual(proposal['event']['end'], '2026-12-18T14:00:00-06:00')
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.service.commit(proposal['operation_id'], 'update')['status'], 'verified')
        stored = Calendar.from_ical(self.events[event_id][0]).walk('VEVENT')[0]
        self.assertEqual(str(stored['UID']), created['uid'])
        self.assertEqual(str(stored['X-LOCAL-NOTE']), 'Keep this')
        self.assertEqual(int(stored['SEQUENCE']), 5)
        self.assertIn('LAST-MODIFIED', stored)
        self.assertEqual(proposal['before']['title'], EVENT['title'])
        self.assertEqual(self.writes[-1], ('PUT', event_id, '"external-version"'))

    def test_all_day_update_preserves_exclusive_end_and_latest_display_timezone(self):
        created = self.create()
        event_id = created['event_id']
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=event_id, event={
            **EVENT, 'start': '2026-12-19', 'end': None, 'all_day': True,
            'duration_days': 2, 'timezone': 'America/New_York',
        })
        self.assertEqual(self.service.commit(proposal['operation_id'], 'update')['status'], 'verified')
        cancel = self.prepare('cancel', 'synthetic-request-0003', event_id=event_id)
        self.assertEqual((cancel['before']['start'], cancel['before']['end'], cancel['before']['timezone']),
                         ('2026-12-19', '2026-12-21', 'America/New_York'))

    def test_replaced_or_unsupported_targets_cannot_be_prepared(self):
        created = self.create()
        path = created['event_id']
        raw, etag = self.events[path]
        for prop, value in (('UID', 'different-identity'), ('ATTENDEE', 'mailto:n@example.org'),
                            ('ORGANIZER', 'mailto:n@example.org'), ('RRULE', {'FREQ': 'DAILY'}),
                            ('RECURRENCE-ID', date(2026, 11, 1)), ('STATUS', 'CANCELLED')):
            calendar = Calendar.from_ical(raw)
            item = calendar.walk('VEVENT')[0]
            item.pop(prop, None)
            item.add(prop, value)
            self.events[path] = calendar.to_ical(), etag
            for action in ('update', 'cancel'):
                with self.subTest(prop=prop, action=action), self.assertRaises(CalendarError):
                    self.prepare(action, 'synthetic-request-0002', event_id=path,
                                 **({'event': {**EVENT, 'title': 'Change'}} if action == 'update' else {}))
        self.assertEqual(len(self.writes), 1)

    def test_changed_etag_or_failed_preflight_sends_no_edit_or_delete(self):
        created = self.create()
        path = created['event_id']
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=path,
                                event={**EVENT, 'title': 'Change'})
        self.read_status = 403
        with self.assertRaisesRegex(CalendarError, 'current calendar resource'):
            self.service.commit(proposal['operation_id'], 'update')
        self.read_status = None
        self.events[path] = self.events[path][0], '"new-version"'
        receipt = self.service.commit(proposal['operation_id'], 'update')
        self.assertEqual((receipt['status'], receipt['attempts']), ('conflict', 0))
        self.assertEqual(len(self.writes), 1)

    def test_expired_edit_and_cancel_never_consume_an_attempt(self):
        from datetime import datetime, timezone

        created = self.create()
        for action, request in (('update', 'synthetic-request-0002'), ('cancel', 'synthetic-request-0003')):
            proposal = self.prepare(action, request, event_id=created['event_id'],
                                    **({'event': {**EVENT, 'title': 'Change'}} if action == 'update' else {}))
            with patch('calendar_owner_operations.datetime', wraps=datetime) as clock:
                clock.now.return_value = datetime.fromtimestamp(proposal['expires_at'], timezone.utc)
                with self.assertRaisesRegex(CalendarError, 'expired'):
                    self.service.commit(proposal['operation_id'], action)
        self.assertEqual(len(self.writes), 1)

    def test_lost_update_response_reconciles_without_put_and_replay_keeps_identity(self):
        created = self.create()
        path = created['event_id']
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=path,
                                event={**EVENT, 'title': 'Changed'})

        def lose(_method, path, raw):
            self.events[path] = raw, '"edited"'
            raise CalendarError('synthetic loss')

        self.forced = lose
        receipt = self.service.commit(proposal['operation_id'], 'update')
        self.assertEqual((receipt['status'], receipt['outcome']), ('verified', 'unknown'))
        reopened = OwnerOperations(self.accounts, OwnerStore(self.store.directory), set(), (20, 50))
        self.assertEqual(reopened.commit(proposal['operation_id'], 'update'), receipt)
        self.assertEqual(reopened.commit(proposal['operation_id'], None, write=False)['current_observation'],
                         'matches')
        self.assertEqual(len(self.writes), 2)

    def test_unresolved_update_blocks_fresh_request_ids_even_after_restart(self):
        created = self.create()
        path = created['event_id']
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=path,
                                event={**EVENT, 'title': 'Changed'})
        # Prepare another proposal before the first is attempted.
        cancel = self.prepare('cancel', 'synthetic-request-0003', event_id=path)
        self.forced = MagicMock(side_effect=CalendarError('synthetic loss'))
        receipt = self.service.commit(proposal['operation_id'], 'update')
        self.assertEqual((receipt['status'], receipt['observation']), ('uncertain', 'unchanged'))
        reopened = OwnerOperations(self.accounts, OwnerStore(self.store.directory), {'update', 'cancel'}, (20, 50))
        with self.assertRaisesRegex(CalendarError, 'unresolved write'):
            reopened.prepare('cancel', 'synthetic-request-0004', 'JTF', event_id=path)
        with self.assertRaisesRegex(CalendarError, 'unresolved write'):
            reopened.commit(cancel['operation_id'], 'cancel')
        self.assertEqual(reopened.commit(proposal['operation_id'], 'update')['attempts'], 1)
        self.assertEqual(len(self.writes), 2)

    def test_lost_delete_response_reports_absence_without_claiming_verified_cancellation(self):
        created = self.create()
        path = created['event_id']
        proposal = self.prepare('cancel', 'synthetic-request-0002', event_id=path)

        def lose(_method, path, _raw):
            del self.events[path]
            raise CalendarError('synthetic loss')

        self.forced = lose
        receipt = self.service.commit(proposal['operation_id'], 'cancel')
        self.assertEqual((receipt['status'], receipt['observation'], receipt['retry_allowed']),
                         ('uncertain', 'missing', False))
        self.service.commit(proposal['operation_id'], None, write=False)
        self.service.commit(proposal['operation_id'], 'cancel')
        self.assertEqual(len(self.writes), 2)

    def test_success_response_with_failed_cancel_readback_is_uncertain(self):
        created = self.create()
        proposal = self.prepare('cancel', 'synthetic-request-0002', event_id=created['event_id'])
        self.forced = lambda *_: (204, None, None)
        receipt = self.service.commit(proposal['operation_id'], 'cancel')
        self.assertEqual((receipt['status'], receipt['observation']), ('uncertain', 'present'))
        self.assertEqual(len(self.writes), 2)

    def test_crash_after_dispatch_keeps_attempt_and_allows_only_reconciliation(self):
        created = self.create()
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=created['event_id'],
                                event={**EVENT, 'title': 'Changed'})
        self.forced = MagicMock(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.service.commit(proposal['operation_id'], 'update')
        reopened = OwnerOperations(self.accounts, OwnerStore(self.store.directory), {'update'}, (20, 50))
        self.assertEqual(reopened.commit(proposal['operation_id'], 'update')['status'], 'uncertain')
        self.assertEqual(reopened.commit(proposal['operation_id'], None, write=False)['observation'], 'unchanged')
        self.assertEqual(len(self.writes), 2)

    def test_quota_counts_update_and_stale_proposals_do_not_bypass_it(self):
        self.service.limits = (2, 2)
        created = self.create()
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=created['event_id'],
                                event={**EVENT, 'title': 'Changed'})
        self.assertEqual(self.service.commit(proposal['operation_id'], 'update')['status'], 'verified')
        cancel = self.prepare('cancel', 'synthetic-request-0003', event_id=created['event_id'])
        with self.assertRaisesRegex(CalendarError, 'rate limit'):
            self.service.commit(cancel['operation_id'], 'cancel')
        with self.store.db() as db:
            rows = [tuple(row) for row in db.execute('SELECT * FROM radar_create_audit')]
        self.assertEqual(len(rows), 2)
        self.assertNotIn(EVENT['title'], repr(rows))
        self.assertEqual(len(self.writes), 2)

    def test_revoked_allowlist_rejects_prepared_edit_and_cancel(self):
        created = self.create()
        for action, request in (('update', 'synthetic-request-0002'), ('cancel', 'synthetic-request-0003')):
            proposal = self.prepare(action, request, event_id=created['event_id'],
                                    **({'event': {**EVENT, 'title': 'Changed'}} if action == 'update' else {}))
            self.accounts.accounts['jtf'].permissions[action] = frozenset()
            with self.assertRaisesRegex(CalendarError, 'allowlisted'):
                self.service.commit(proposal['operation_id'], action)
        self.assertEqual(len(self.writes), 1)

    def test_update_like_creation_status_blocks_route_instead_of_reporting_success(self):
        created = self.create()
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=created['event_id'],
                                event={**EVENT, 'title': 'Changed'})
        self.forced = lambda *_: (201, None, None)
        self.assertEqual(self.service.commit(proposal['operation_id'], 'update')['status'], 'integrity_failure')
        with self.assertRaisesRegex(CalendarError, 'blocked'):
            self.prepare(request_id='synthetic-request-0003')
        self.assertEqual(len(self.writes), 2)

    def test_update_precondition_failure_preserves_original_and_never_retries(self):
        created = self.create()
        path = created['event_id']
        before = self.events[path]
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=path,
                                event={**EVENT, 'title': 'Changed'})
        self.forced = lambda *_: (412, None, None)
        self.assertEqual(self.service.commit(proposal['operation_id'], 'update')['status'], 'conflict')
        self.service.commit(proposal['operation_id'], 'update')
        self.assertEqual(self.events[path], before)
        self.assertEqual(len(self.writes), 2)

    def test_verified_update_reconciliation_reports_subsequent_external_change(self):
        created = self.create()
        path = created['event_id']
        proposal = self.prepare('update', 'synthetic-request-0002', event_id=path,
                                event={**EVENT, 'title': 'Changed'})
        self.assertEqual(self.service.commit(proposal['operation_id'], 'update')['status'], 'verified')
        self.events[path] = self.events[path][0].replace(b'Changed', b'External'), '"external"'
        receipt = self.service.commit(proposal['operation_id'], None, write=False)
        self.assertEqual((receipt['status'], receipt['observation'], receipt['current_observation']),
                         ('verified', 'matches', 'changed'))
        self.assertEqual(len(self.writes), 2)

    def test_cancel_absence_is_not_verified_when_collection_becomes_inaccessible(self):
        created = self.create()
        path = created['event_id']
        proposal = self.prepare('cancel', 'synthetic-request-0002', event_id=path)

        def remove_then_lose_access(_method, path, _raw):
            del self.events[path]
            self.forced_discovery.side_effect = CalendarError('synthetic forbidden')
            return 204, None, None

        self.forced = remove_then_lose_access
        with patch.object(CreateTransport, 'calendar_path', return_value=PERSONAL) as discovery:
            self.forced_discovery = discovery
            receipt = self.service.commit(proposal['operation_id'], 'cancel')
        self.assertEqual((receipt['status'], receipt['observation']), ('uncertain', 'unreadable'))
        self.assertEqual(len(self.writes), 2)

    def enable_invitations(self):
        policy = InvitationPolicy(True, frozenset({'jtf:' + PERSONAL}), frozenset({'guest@example.net'}), 1)
        self.service.invitations = policy
        return {**EVENT, 'attendees': ['guest@example.net']}

    def test_invitation_addresses_are_explicit_bounded_and_distinct(self):
        self.assertEqual(email_address('Guest+test@EXAMPLE.NET'), 'Guest+test@example.net')
        self.assertEqual(attendee_addresses(['b@example.net', 'a@example.net']), ['a@example.net', 'b@example.net'])
        for address in ('Nick', 'mailto:guest@example.net', 'Name <guest@example.net>',
                        'guest@example.net\r\nBcc:other@example.net', 'a@example.net,b@example.net',
                        '.guest@example.net', 'a..b@example.net', 'a@-bad.example', 'a@localhost',
                        'a?subject=bad@example.net', 'a#bad@example.net', 'a%0d@example.net'):
            with self.subTest(address=address), self.assertRaises(CalendarError):
                email_address(address)
        for addresses in (['Guest@example.net', 'guest@example.net'], ['a@example.net'] * 11):
            with self.assertRaises(CalendarError):
                attendee_addresses(addresses)

    def test_invitation_default_off_and_recipient_policy_are_fail_closed(self):
        with self.assertRaisesRegex(CalendarError, 'disabled'):
            self.prepare(event={**EVENT, 'attendees': ['guest@example.net']})
        event = self.enable_invitations()
        for changes in ({'attendees': ['other@example.net']},
                        {'attendees': ['guest@example.net', 'other@example.net']},
                        {'organizer': 'spoof@example.net'}, {'attendees': [{'email': 'guest@example.net'}]}):
            with self.subTest(changes=changes), self.assertRaises(CalendarError):
                self.prepare(event={**event, **changes})
        self.assertEqual(self.writes, [])

    def test_invitation_prepare_pins_organizer_and_does_not_send(self):
        event = self.enable_invitations()
        proposal = self.prepare(event=event)
        self.assertEqual(proposal['invitation']['organizer'], 'user@mail.example.com')
        self.assertEqual(proposal['event']['attendees'], ['guest@example.net'])
        self.assertEqual(self.writes, [])
        raw = self.store.get(proposal['operation_id'])['raw']
        stored = Calendar.from_ical(raw)
        self.assertNotIn('METHOD', stored)
        attendee = stored.walk('VEVENT')[0]['ATTENDEE']
        self.assertEqual(str(attendee), 'mailto:guest@example.net')
        self.assertEqual(str(attendee.params['RSVP']), 'TRUE')
        self.assertEqual(str(attendee.params['SCHEDULE-AGENT']), 'SERVER')
        self.assertEqual(int(stored.walk('VEVENT')[0]['SEQUENCE']), 0)
        self.assertTrue(matches_invitation(raw, proposal))

    def test_invitation_public_busy_default_and_explicit_overrides_keep_attendee_bindings(self):
        event = self.enable_invitations()
        for index, overrides in enumerate(({}, {'classification': 'PRIVATE', 'transparency': 'TRANSPARENT'},
                                           {'classification': 'CONFIDENTIAL', 'transparency': 'OPAQUE'})):
            with self.subTest(overrides=overrides):
                proposal = self.prepare(request_id=f'synthetic-invitation-default-{index:04d}', event={**event, **overrides})
                raw = self.store.get(proposal['operation_id'])['raw']
                item = Calendar.from_ical(raw).walk('VEVENT')[0]
                self.assertEqual(str(item['CLASS']), overrides.get('classification', 'PUBLIC'))
                self.assertEqual(str(item['TRANSP']), overrides.get('transparency', 'OPAQUE'))
                self.assertEqual(str(item['ATTENDEE']), 'mailto:guest@example.net')
                self.assertEqual(str(item['ORGANIZER']), 'mailto:user@mail.example.com')
                self.assertTrue(matches_invitation(raw, proposal))
        self.assertEqual(self.writes, [])

    def test_invitation_readback_checks_exact_addresses_and_rejects_unsupported_data(self):
        proposal = self.prepare(event=self.enable_invitations())
        raw = self.store.get(proposal['operation_id'])['raw']
        for change in ('organizer', 'attendee', 'extra_attendee', 'duplicate', 'recurrence', 'suppress', 'client'):
            calendar = Calendar.from_ical(raw)
            item = calendar.walk('VEVENT')[0]
            if change == 'organizer': item['ORGANIZER'] = 'mailto:other@example.net'
            if change == 'attendee': item['ATTENDEE'] = 'mailto:other@example.net'
            if change == 'extra_attendee': item.add('ATTENDEE', 'mailto:other@example.net')
            if change == 'duplicate': item.add('ATTENDEE', 'mailto:guest@example.net')
            if change == 'recurrence': item.add('RRULE', {'FREQ': 'DAILY'})
            if change == 'suppress': item.add('X-SOGo-Send-Appointment-Notifications', 'NO')
            if change == 'client': item['ORGANIZER'].params['SCHEDULE-AGENT'] = 'CLIENT'
            with self.subTest(change=change):
                self.assertFalse(matches_invitation(calendar.to_ical(), proposal))

    def test_invitation_readback_allows_server_name_and_actual_attendee_response(self):
        event = {**self.enable_invitations(), 'all_day': True, 'start': '2026-12-22', 'end': '2026-12-23'}
        proposal = self.prepare(event=event)
        raw = self.store.get(proposal['operation_id'])['raw']
        calendar = Calendar.from_ical(raw)
        item = calendar.walk('VEVENT')[0]
        item['ORGANIZER'].params['CN'] = 'Server supplied owner name'
        item['ATTENDEE'].params['PARTSTAT'] = 'ACCEPTED'
        self.assertTrue(matches_invitation(calendar.to_ical(), proposal))
        self.assertEqual(item.decoded('DTEND'), date(2026, 12, 23))

    def test_invitation_commit_verifies_creation_without_claiming_mail_delivery(self):
        proposal = self.prepare(event=self.enable_invitations())
        receipt = self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual((receipt['event_creation'], receipt['invitations']['dispatch'],
                          receipt['invitations']['email_delivery']), ('verified', 'unknown', 'unverified'))
        self.assertFalse(receipt['invitations']['resend_allowed'])
        self.assertEqual(self.service.commit(proposal['operation_id'], 'create'), receipt)
        self.assertEqual(len(self.writes), 1)

    def test_fresh_request_id_cannot_duplicate_an_invitation_after_restart(self):
        event = self.enable_invitations()
        proposal = self.prepare(event=event)
        self.service.commit(proposal['operation_id'], 'create')
        reopened = OwnerOperations(self.accounts, OwnerStore(self.store.directory), {'create'}, (20, 50),
                                   self.service.invitations)
        with self.assertRaisesRegex(CalendarError, proposal['operation_id']):
            reopened.prepare('create', 'synthetic-request-0002', 'JTF', event=event)
        self.assertEqual(len(self.writes), 1)

    def test_lost_invitation_response_never_resends_even_when_event_is_absent(self):
        event = self.enable_invitations()
        proposal = self.prepare(event=event)
        self.forced = MagicMock(side_effect=CalendarError('synthetic loss after possible email dispatch'))
        receipt = self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual((receipt['status'], receipt['invitations']['dispatch']), ('uncertain', 'unknown'))
        self.service.invitations = None  # Disabled mode retains GET-only recovery and historical receipts.
        self.service.commit(proposal['operation_id'], None, write=False)
        self.service.commit(proposal['operation_id'], 'create')
        self.enable_invitations()
        with self.assertRaisesRegex(CalendarError, 'do not resend'):
            self.prepare(request_id='synthetic-request-0002', event=event)
        self.assertEqual(len(self.writes), 1)

    def test_lost_response_with_stored_invitation_verifies_only_the_event(self):
        proposal = self.prepare(event=self.enable_invitations())
        def lost(_method, path, raw):
            self.events[path] = raw, '"stored"'
            raise CalendarError('synthetic response loss')
        self.forced = lost
        receipt = self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual((receipt['status'], receipt['invitations']['email_delivery']), ('verified', 'unverified'))
        self.assertEqual(len(self.writes), 1)

    def test_rejected_invitation_put_still_cannot_be_automatically_resent(self):
        event = self.enable_invitations()
        proposal = self.prepare(event=event)
        self.forced = lambda *_: (400, None, None)
        receipt = self.service.commit(proposal['operation_id'], 'create')
        self.assertEqual((receipt['status'], receipt['invitations']['dispatch']), ('rejected', 'unknown'))
        with self.assertRaisesRegex(CalendarError, 'do not resend'):
            self.prepare(request_id='synthetic-request-0002', event=event)
        self.assertEqual(len(self.writes), 1)

    def test_invitation_policy_is_rechecked_at_commit_and_plain_creation_still_works(self):
        proposal = self.prepare(event=self.enable_invitations())
        self.service.invitations = None
        with self.assertRaisesRegex(CalendarError, 'disabled'):
            self.service.commit(proposal['operation_id'], 'create')
        plain = self.prepare(request_id='synthetic-request-0002')
        self.assertEqual(self.service.commit(plain['operation_id'], 'create')['status'], 'verified')
        self.assertEqual(len(self.writes), 1)

    def test_invitation_quota_and_audit_exclude_addresses_and_event_details(self):
        self.service.limits = (1, 1)
        proposal = self.prepare(event=self.enable_invitations())
        self.service.commit(proposal['operation_id'], 'create')
        second = self.prepare(request_id='synthetic-request-0002', event={**EVENT, 'title': 'Other'})
        with self.assertRaisesRegex(CalendarError, 'rate limit'):
            self.service.commit(second['operation_id'], 'create')
        with self.store.db() as db:
            audit = repr([tuple(row) for row in db.execute('SELECT * FROM radar_create_audit')])
        self.assertNotIn('guest@example.net', audit)
        self.assertNotIn(EVENT['title'], audit)
        self.assertEqual(len(self.writes), 1)

    def test_attendees_cannot_be_updated_or_cancelled_through_phase2_methods(self):
        proposal = self.prepare(event=self.enable_invitations())
        self.service.commit(proposal['operation_id'], 'create')
        for action in ('update', 'cancel'):
            with self.subTest(action=action), self.assertRaises(CalendarError):
                self.prepare(action, 'synthetic-request-0002', event_id=proposal['event_id'],
                             **({'event': {**EVENT, 'title': 'Changed'}} if action == 'update' else {}))
        self.assertEqual(len(self.writes), 1)

    def test_invitation_prepare_and_commit_through_existing_mcp_tools(self):
        from calendar_owner_operations import register_owner_operations

        event = self.enable_invitations()
        app = FastMCP('Synthetic owner connection')
        with patch.dict(os.environ, {
            'INBOXTETHER_CALDAV_RADAR_STATE_DIR': str(self.store.directory),
            'INBOXTETHER_CALDAV_CREATE_ENABLED': '1', 'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED': '1',
        }, clear=True):
            register_owner_operations(app, self.accounts, invitations=self.service.invitations)
        def call(name, arguments):
            return json.loads(asyncio.run(app.call_tool(name, arguments))[0].text)
        result = call('calendar_prepare_create', {'calendar_id': 'JTF', 'request_id': REQUEST, 'event': event})
        receipt = call('calendar_commit_create', {'operation_id': result['proposal']['operation_id']})
        self.assertEqual(receipt['invitations']['email_delivery'], 'unverified')
        self.assertNotIn('calendar_commit_update', {t.name for t in asyncio.run(app.list_tools())})
        self.assertEqual(len(self.writes), 1)


class OwnerCalendarHookTests(unittest.TestCase):
    """Exercise the actual extension using synthetic config, without credentials or I/O."""

    def setUp(self):
        import calendar_radar_extension as hook

        self.hook = hook
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.rows = [account('jtf', 'mail.example.com')]
        for field in ('create_ids', 'update_ids', 'cancel_ids'):
            self.rows[0][field] = []
        self.rows[0].pop('write_password_file')
        self.policy = dict(enabled=True, account_id='jtf', create_ids=[PERSONAL],
                           write_password_file='/private/jtf-write', state_directory=temporary.name,
                           max_attempts_per_hour=2, max_attempts_per_day=2)
        self.changes = dict(account_id='jtf', calendar_ids=[PERSONAL], update_enabled=False,
                            cancel_enabled=False, conditional_update_verified=False,
                            conditional_cancel_verified=False)
        self.enterContext(patch.object(hook, 'CHANGES', Path(temporary.name) / 'changes.json'))
        self.enterContext(patch.object(hook, 'INVITATIONS', Path(temporary.name) / 'invitations.json'))
        self.enterContext(patch.object(hook, 'CONTACTS', Path(temporary.name) / 'contacts.json'))
        self.invitation = None
        hook.CHANGES.write_text('{}')
        self.enterContext(patch.object(hook, 'trusted_json', side_effect=self.read_config))

    def read_config(self, path):
        return {self.hook.CONFIG: self.rows, self.hook.CREATION: self.policy,
                self.hook.CHANGES: self.changes, self.hook.INVITATIONS: self.invitation}[path]

    def register(self):
        app = FastMCP('Synthetic existing connection')
        names = ('list_mailboxes', 'search_messages', 'read_message', 'list_attachments',
                 'retrieve_attachment', 'prepare_reply_draft', 'save_draft', 'organize_jtf_email')
        for name in names:
            def placeholder():
                """Synthetic inventory placeholder, never called."""
                raise AssertionError('No email tool should run during registration')
            app.tool(name=name)(placeholder)
        before = {tool.name: tool.model_dump() for tool in asyncio.run(app.list_tools())}
        self.hook.register(app)
        after = {tool.name: tool for tool in asyncio.run(app.list_tools())}
        self.assertTrue(all(after[name].model_dump() == before[name] for name in names))
        return after

    def test_missing_or_disabled_phase2_policy_preserves_phase1_and_process_environment(self):
        tools = self.register()
        self.assertEqual(len(tools), 16)
        self.assertIn('calendar_commit_create', tools)
        self.assertNotIn('calendar_commit_cancel', tools)
        self.assertEqual(dict(os.environ), {})
        self.hook.CHANGES.unlink()
        self.assertEqual(set(self.register()), set(tools))

    def test_qualified_methods_register_independently_and_disabled_mode_keeps_reconciliation(self):
        for action in ('update', 'cancel'):
            with self.subTest(action=action):
                self.changes[action + '_enabled'] = True
                self.changes['conditional_' + action + '_verified'] = True
                tools = self.register()
                self.assertIn('calendar_commit_' + action, tools)
                self.assertEqual(len(tools), 18 if action == 'update' else 20)
        self.changes.update(update_enabled=False, cancel_enabled=False)
        self.assertEqual(len(self.register()), 16)
        self.assertIn('calendar_reconcile_operation', self.register())

    def test_hook_rejects_unqualified_or_out_of_scope_policy(self):
        original = dict(self.changes)
        for changes in ({'update_enabled': True}, {'cancel_enabled': True}, {'account_id': 'other'},
                        {'calendar_ids': [SHARED]}, {'calendar_ids': [PERSONAL, PERSONAL]},
                        {'conditional_update_verified': 'yes'}, {'extra': True}):
            self.changes = {**original, **changes}
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.register()
        self.assertEqual(dict(os.environ), {})

    def test_invitation_pilot_preserves_inventory_and_refuses_phase2_enablement(self):
        self.hook.INVITATIONS.write_text('{}')
        self.invitation = dict(enabled=True, account_id='jtf', calendar_ids=[PERSONAL],
                               allowed_recipients=['guest@example.net'], max_attendees=1)
        tools = self.register()
        self.assertEqual(len(tools), 16)
        self.assertNotIn('calendar_commit_update', tools)
        self.assertNotIn('calendar_commit_cancel', tools)
        self.changes.update(update_enabled=True, conditional_update_verified=True)
        with self.assertRaisesRegex(RuntimeError, 'Keep update and cancellation disabled'):
            self.register()

    def test_invitation_policy_rejects_missing_recipients_and_widened_scope(self):
        good = dict(enabled=True, account_id='jtf', calendar_ids=[PERSONAL],
                    allowed_recipients=['guest@example.net'], max_attendees=1)
        for change in ({'allowed_recipients': []}, {'allowed_recipients': ['Name <a@example.net>']},
                       {'account_id': 'other'}, {'calendar_ids': [SHARED]}, {'max_attendees': 11},
                       {'max_attendees': True}, {'enabled': 'true'}, {'unexpected': True}):
            with self.subTest(change=change), self.assertRaises(CalendarError):
                policy_from_config({**good, **change}, self.policy)

    def test_contacts_preserve_all_sixteen_invitation_email_and_calendar_definitions(self):
        import carddav_contacts
        original_register = carddav_contacts.register_configured
        original_lstat = Path.lstat
        def administrator_owned(path, *args, **kwargs):
            info = list(original_lstat(path, *args, **kwargs))
            info[4] = 0
            return os.stat_result(info)
        def configured_with_administrator_metadata(*args, **kwargs):
            # Only the CardDAV policy load sees synthetic root ownership. State
            # validation still observes the real unprivileged service identity.
            with patch.object(Path, 'lstat', administrator_owned):
                return original_register(*args, **kwargs)
        self.enterContext(patch.object(carddav_contacts, 'register_configured',
                                      side_effect=configured_with_administrator_metadata))
        self.hook.INVITATIONS.write_text('{}')
        self.invitation = dict(enabled=True, account_id='jtf', calendar_ids=[PERSONAL],
                               allowed_recipients=['guest@example.net'], max_attendees=1)
        before = {key: tool.model_dump() for key, tool in self.register().items()}
        home = '/SOGo/dav/user@mail.example.com/Contacts/'
        contacts = dict(enabled=True, accounts=[dict(account_id='jtf',
                        home_url='https://mail.example.com' + home, read_ids=[home + 'personal/'])])
        self.hook.CONTACTS.write_text(json.dumps(contacts))
        self.hook.CONTACTS.chmod(0o644)
        with patch('carddav_contacts.read_secret', side_effect=AssertionError('No credential read')), \
                patch('carddav_contacts.HTTPSConnection', side_effect=AssertionError('No network')):
            after = {key: tool.model_dump() for key, tool in self.register().items()}
        self.assertEqual(len(after), 18)
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertEqual(set(after) - set(before), {'contacts_list_address_books', 'contacts_search'})
        self.assertNotIn('calendar_commit_update', after)
        self.assertNotIn('calendar_commit_cancel', after)
        contacts['enabled'] = False
        self.hook.CONTACTS.write_text(json.dumps(contacts))
        disabled = {key: tool.model_dump() for key, tool in self.register().items()}
        self.assertEqual(disabled, before)
        self.assertEqual(dict(os.environ), {})


class OwnerCalendarWireTests(unittest.TestCase):
    @patch('calendar_create.read_secret', return_value='synthetic-secret')
    @patch('calendar_create.HTTPSConnection')
    def test_invitation_put_uses_conditional_create_and_suppresses_group_expansion(self, https, _):
        transport = CreateTransport('https://mail.example.com' + HOME, 'user@example.com', '/private/secret')
        response = MagicMock(status=201)
        https.return_value.getresponse.return_value.__enter__.return_value = response
        transport.exchange_resource('PUT', PERSONAL, PERSONAL + 'new.ics', b'event', scheduling=True)
        headers = https.return_value.request.call_args.kwargs['headers']
        self.assertEqual(headers['X-SOGo'], 'NoGroupsDecomposition')
        self.assertEqual(headers['If-None-Match'], '*')
        self.assertNotIn('If-Match', headers)
        self.assertEqual(https.return_value.request.call_count, 1)
        for method, raw, etag in (('GET', None, None), ('DELETE', None, '"v1"'), ('PUT', b'e', '"v1"')):
            with self.assertRaises(CalendarError):
                transport.exchange_resource(method, PERSONAL, PERSONAL + 'new.ics', raw, etag=etag, scheduling=True)

    @patch('calendar_create.read_secret', return_value='synthetic-secret')
    @patch('calendar_create.HTTPSConnection')
    def test_exact_update_and_cancel_headers_and_path_guard(self, https, _):
        transport = CreateTransport('https://mail.example.com' + HOME, 'user@example.com', '/private/secret')
        response = MagicMock(status=204)
        https.return_value.getresponse.return_value.__enter__.return_value = response
        path = PERSONAL + 'test.ics'
        transport.exchange_resource('PUT', PERSONAL, path, b'event', etag='"v1"')
        transport.exchange_resource('DELETE', PERSONAL, path, etag='"v2"')
        calls = https.return_value.request.call_args_list
        self.assertEqual([call.args for call in calls], [('PUT', path), ('DELETE', path)])
        self.assertEqual([call.kwargs['headers']['If-Match'] for call in calls], ['"v1"', '"v2"'])
        self.assertTrue(all('If-None-Match' not in call.kwargs['headers'] for call in calls))
        with self.assertRaises(CalendarError):
            transport.exchange_resource('DELETE', PERSONAL, path, etag='*')
        with self.assertRaises(CalendarError):
            transport.exchange_resource('DELETE', PERSONAL, SHARED + 'test.ics', etag='"v2"')
