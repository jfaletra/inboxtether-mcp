import asyncio
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from pydantic import ValidationError

import server
import calendar_owner_connection
from calendar_create import (CreationService, CreateTransport, EventSpec, Store, approve_interactively,
                             matches_event)
from sogo_calendar import CalendarError, SogoCalendar
from test_sogo_calendar import HOME, PERSONAL, SHARED


REQUEST = 'synthetic-booking-0001'
EVENT = {
    'title': 'Synthetic event, Café',
    'start': '2026-11-01T01:30:00-05:00',
    'end': '2026-11-01T01:30:00-06:00',
    'timezone': 'America/Chicago',
    'description': 'Synthetic text; newline\nSecond line.',
    'location': 'Room 2',
}


class TTY(StringIO):
    def isatty(self):
        return True


class CalendarCreationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.transport = CreateTransport('https://mail.example.com' + HOME, 'user@example.com', '/private/secret')
        self.transport.calendar_path = Mock(side_effect=lambda calendar_id: calendar_id)
        self.destination = None
        self.puts = []
        self.transport.exchange = Mock(side_effect=self.exchange)
        self.store = Store(self.directory)
        self.service = CreationService(self.transport, self.store, {PERSONAL})

    def exchange(self, calendar_id, key, raw=None):
        if raw is None:
            return (200, self.destination) if self.destination is not None else (404, None)
        self.puts.append((calendar_id, key, raw))
        if self.destination is not None:
            return 412, None
        self.destination = raw
        return 201, None

    def prepare(self, **changes):
        return self.service.prepare(REQUEST, PERSONAL, EventSpec(**{**EVENT, **changes}))

    def approve(self, **changes):
        prepared = self.prepare(**changes)
        key = prepared['proposal']['operation_id']
        output = TTY()
        approve_interactively(self.service, key, TTY('APPROVE ' + prepared['approval_fingerprint'] + '\n'), output)
        self.assertIn('Synthetic event', output.getvalue())
        self.assertIn(PERSONAL, output.getvalue())
        self.assertIn(prepared['proposal']['event']['start'], output.getvalue())
        return key

    def test_approval_timed_creation_readback_and_repeated_commit(self):
        pending = self.prepare()
        key = pending['proposal']['operation_id']
        self.assertEqual(pending, self.prepare())
        with self.assertRaisesRegex(CalendarError, 'Separate owner approval'):
            self.service.commit(key)
        self.transport.exchange.assert_not_called()
        with self.assertRaisesRegex(CalendarError, 'trusted interactive terminal'):
            approve_interactively(self.service, key, StringIO(), TTY())
        with self.assertRaisesRegex(CalendarError, 'approval cancelled'):
            approve_interactively(self.service, key, TTY('APPROVE wrong\n'), TTY())
        self.assertEqual(self.approve(), key)
        self.assertEqual(self.transport.exchange.call_count, 0)
        receipt = self.service.commit(key)
        self.assertEqual(receipt['status'], 'verified')
        self.assertEqual(receipt['attempts'], 1)
        self.assertEqual(receipt['event_id'], PERSONAL + key + '.ics')
        self.assertNotIn('Synthetic event', str(receipt))
        self.assertEqual([len(call.args) for call in self.transport.exchange.call_args_list], [2, 3, 2])
        self.assertIn(b'DTSTART:20261101T063000Z', self.destination)
        self.assertIn(b'DTEND:20261101T073000Z', self.destination)
        self.assertEqual(self.service.commit(key), receipt)
        self.assertEqual(len(self.puts), 1)

    def test_all_day_is_date_only_with_exclusive_end(self):
        key = self.approve(start='2026-11-01', end='2026-11-02', all_day=True)
        self.assertEqual(self.service.commit(key)['status'], 'verified')
        self.assertIn(b'DTSTART;VALUE=DATE:20261101', self.destination)
        self.assertIn(b'DTEND;VALUE=DATE:20261102', self.destination)
        self.assertNotIn(b'ATTENDEE', self.destination)
        self.assertNotIn(b'RRULE', self.destination)

    def test_default_public_busy_is_advertised_and_rendered_for_timed_and_all_day(self):
        from icalendar import Calendar
        from calendar_owner_operations import OwnerEventSpec

        for model in (EventSpec, OwnerEventSpec):
            properties = model.model_json_schema()['properties']
            self.assertEqual(properties['classification']['default'], 'PUBLIC')
            self.assertEqual(properties['transparency']['default'], 'OPAQUE')
            self.assertEqual(properties['classification']['enum'], ['PUBLIC', 'PRIVATE', 'CONFIDENTIAL'])
            self.assertEqual(properties['transparency']['enum'], ['OPAQUE', 'TRANSPARENT'])
        for index, changes in enumerate(({}, {'all_day': True, 'start': '2026-11-01', 'end': '2026-11-02'})):
            with self.subTest(changes=changes):
                prepared = self.service.prepare(REQUEST + '-' + str(index), PERSONAL, EventSpec(**{**EVENT, **changes}))
                proposal = prepared['proposal']
                self.assertEqual((proposal['event']['classification'], proposal['event']['transparency']), ('PUBLIC', 'OPAQUE'))
                item = Calendar.from_ical(self.store.get(proposal['operation_id'])['raw']).walk('VEVENT')[0]
                self.assertEqual((str(item['CLASS']), str(item['TRANSP'])), ('PUBLIC', 'OPAQUE'))
        self.assertEqual(self.puts, [])

    def test_request_id_cannot_be_repurposed(self):
        self.prepare()
        with self.assertRaisesRegex(CalendarError, 'different event'):
            self.prepare(title='Edited title')
        self.service.allowed = {PERSONAL, SHARED}
        with self.assertRaisesRegex(CalendarError, 'different event or calendar'):
            self.service.prepare(REQUEST, SHARED, EventSpec(**EVENT))
        self.assertEqual(self.transport.calendar_path.call_count, 1)

    def test_expired_proposal_and_revoked_calendar_never_write(self):
        key = self.approve()
        expires = self.store.get(key)['manifest']['expires_at']
        with patch('calendar_create.time.time', return_value=expires):
            with self.assertRaisesRegex(CalendarError, 'approval expired'):
                self.service.commit(key)
        self.service.allowed = set()
        with self.assertRaisesRegex(CalendarError, 'no longer authorized'):
            self.service.commit(key)
        self.transport.exchange.assert_not_called()

    def test_expired_pending_proposal_cannot_be_approved(self):
        item = self.prepare()
        with patch('calendar_create.time.time', return_value=item['proposal']['expires_at']):
            with self.assertRaisesRegex(CalendarError, 'changed or expired'):
                self.store.approve(item['proposal']['operation_id'], item['approval_fingerprint'])

    def test_invalid_input_and_inaccessible_calendar_fail_before_write(self):
        for changes in (
            {'timezone': 'Nowhere/Unknown'}, {'timezone': 'UTC'}, {'title': ' \n '},
            {'end': '2026-11-01T00:30:00-05:00'}, {'end': '2026-11-01T01:30:00-05:00'},
            {'start': '2026-03-08T02:30:00-06:00', 'end': '2026-03-08T03:45:00-05:00'},
            {'start': '2026-11-01', 'end': '2026-11-01', 'all_day': True},
        ):
            with self.subTest(changes=changes), self.assertRaises(CalendarError):
                self.prepare(**changes)
        with self.assertRaises(ValidationError):
            EventSpec(**EVENT, attendees=['someone@example.com'])
        with self.assertRaisesRegex(CalendarError, 'not authorized'):
            self.service.prepare(REQUEST, SHARED, EventSpec(**EVENT))
        self.transport.calendar_path.assert_not_called()
        self.transport.calendar_path.side_effect = CalendarError('Calendar is not in the inventory.')
        with self.assertRaisesRegex(CalendarError, 'not in the inventory'):
            self.prepare()
        self.transport.exchange.assert_not_called()

    def test_uncertain_response_with_stored_event_reconciles_without_second_put(self):
        key = self.approve()
        def lost_response(calendar_id, operation_id, raw=None):
            status = self.exchange(calendar_id, operation_id, raw)
            if raw is not None:
                raise CalendarError('Timeout')
            return status
        self.transport.exchange.side_effect = lost_response
        self.assertEqual(self.service.commit(key)['status'], 'verified')
        self.assertEqual(self.service.commit(key)['status'], 'verified')
        self.assertEqual(len(self.puts), 1)

    def test_timeout_then_absence_permits_one_retry_at_same_resource(self):
        key = self.approve()
        def first_lost(calendar_id, operation_id, raw=None):
            if raw is not None and not self.puts:
                self.puts.append((calendar_id, operation_id, raw))
                raise CalendarError('Timeout')
            return self.exchange(calendar_id, operation_id, raw)
        self.transport.exchange.side_effect = first_lost
        first = self.service.commit(key)
        self.assertEqual(first['status'], 'uncertain')
        self.assertTrue(first['retry_allowed'])
        self.assertEqual(self.service.commit(key)['status'], 'verified')
        self.assertEqual(self.puts, [self.puts[0]] * 2)

    def test_unknown_outcome_does_not_retry_without_readable_absence(self):
        key = self.approve()
        self.transport.exchange.side_effect = [(404, None), CalendarError('Timeout'),
                                              CalendarError('Read failed'), (403, None)]
        for _ in range(2):
            receipt = self.service.commit(key)
            self.assertEqual(receipt['status'], 'uncertain')
            self.assertTrue(receipt['recheck_allowed'])
            self.assertFalse(receipt['retry_allowed'])
        self.assertEqual(sum(len(call.args) == 3 for call in self.transport.exchange.call_args_list), 1)

    def test_retry_budget_and_acknowledged_creation_never_trigger_another_put(self):
        for status, maximum in ((503, 2), (201, 1), (204, 1)):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as directory:
                    self.store = Store(Path(directory))
                    self.service = CreationService(self.transport, self.store, {PERSONAL})
                    key = self.approve()
                    self.transport.exchange.reset_mock()
                    self.transport.exchange.side_effect = lambda *args: (status if len(args) == 3 else 404, None)
                    for _ in range(3):
                        self.assertEqual(self.service.commit(key)['status'], 'uncertain')
                    self.assertEqual(sum(len(call.args) == 3 for call in self.transport.exchange.call_args_list),
                                     maximum)

    def test_conflicting_resource_and_conditional_race_never_overwrite(self):
        key = self.approve()
        self.transport.exchange.side_effect = [(404, None), (412, None), (200, b'other data')]
        self.assertEqual(self.service.commit(key)['status'], 'conflict')
        self.assertEqual(self.service.commit(key)['status'], 'conflict')
        self.assertEqual(self.transport.exchange.call_count, 3)

    def test_inaccessible_write_is_rejected_without_retry(self):
        key = self.approve()
        self.transport.exchange.side_effect = [(404, None), (403, None), (404, None)]
        self.assertEqual(self.service.commit(key)['status'], 'rejected')
        self.assertEqual(self.service.commit(key)['status'], 'rejected')
        self.assertEqual(self.transport.exchange.call_count, 3)

    def test_update_style_response_cannot_be_reported_as_a_verified_creation(self):
        key = self.approve()

        def update_style(calendar_id, operation_id, raw=None):
            response = self.exchange(calendar_id, operation_id, raw)
            return (204, None) if raw is not None else response

        self.transport.exchange.side_effect = update_style
        self.assertEqual(self.service.commit(key)['status'], 'uncertain')
        receipt = self.service.commit(key)
        self.assertEqual(receipt['status'], 'uncertain')
        self.assertFalse(receipt['retry_allowed'])
        self.assertEqual(len(self.puts), 1)

    def test_expired_interrupted_attempt_still_allows_read_only_reconciliation(self):
        key = self.approve()
        item = self.store.get(key)
        self.store.state(key, 'attempting', 'unknown', attempt=True)
        self.destination = item['raw']
        with patch('calendar_create.time.time', return_value=item['manifest']['expires_at'] + 1):
            self.assertEqual(self.service.commit(key)['status'], 'verified')
        self.assertFalse(self.puts)

    def test_mismatched_stored_fields_or_unexpected_attendee_do_not_verify(self):
        key = self.approve()
        item = self.store.get(key)
        raw = item['raw']
        self.assertTrue(matches_event(raw, item['manifest']))
        for changed in (raw.replace(b'Room 2', b'Room 3'),
                        raw.replace(b'END:VEVENT', b'ATTENDEE:mailto:person@example.com\r\nEND:VEVENT')):
            self.assertFalse(matches_event(changed, item['manifest']))

    def test_tampered_payload_and_parallel_attempt_are_rejected(self):
        key = self.approve()
        with self.store.locked(), self.assertRaisesRegex(CalendarError, 'in progress'):
            self.service.commit(key)
        with self.store.db() as db:
            db.execute('UPDATE creations SET raw=? WHERE id=?', (b'bad data', key))
        with self.assertRaisesRegex(CalendarError, 'integrity check'):
            self.service.commit(key)
        self.transport.exchange.assert_not_called()


class CreationWireTests(unittest.TestCase):
    @patch('calendar_create.read_secret', return_value='synthetic-password')
    @patch('calendar_create.HTTPSConnection')
    def test_put_is_conditional_and_reader_remains_read_only(self, https, _):
        transport = CreateTransport('https://mail.example.com' + HOME, 'user@example.com', '/private/secret')
        response = MagicMock(status=201)
        https.return_value.getresponse.return_value.__enter__.return_value = response
        key = 'a' * 64
        self.assertEqual(transport.exchange(PERSONAL, key, b'event'), (201, None))
        wire = https.return_value.request.call_args
        self.assertEqual(wire.args, ('PUT', PERSONAL + key + '.ics'))
        self.assertEqual(wire.kwargs['headers']['If-None-Match'], '*')
        self.assertEqual(wire.kwargs['body'], b'event')
        response.read.assert_not_called()
        with self.assertRaises(CalendarError):
            transport.exchange('/outside/', key, b'event')
        with self.assertRaisesRegex(CalendarError, 'read-only guard'):
            transport.request('PUT', PERSONAL, document=MagicMock())
        https.return_value.request.assert_called_once()

    @patch.dict(os.environ, {
        'INBOXTETHER_CALDAV_HOME_URL': 'https://mail.example.com' + HOME,
        'INBOXTETHER_CALDAV_ACCOUNT': 'user@example.com',
        'INBOXTETHER_CALDAV_PASSWORD_FILE': '/private/read',
        'INBOXTETHER_CALDAV_CREATE_PASSWORD_FILE': '/private/write',
        'INBOXTETHER_CALDAV_CREATE_IDS': json.dumps([PERSONAL]),
    }, clear=True)
    def test_mcp_write_tools_are_opt_in_and_have_no_approval_tool(self):
        async def names(app):
            return {tool.name: tool for tool in await app.list_tools()}
        self.assertNotIn('calendar_prepare_create', asyncio.run(names(server.create_server())))
        with patch.dict(os.environ, {'INBOXTETHER_CALDAV_CREATE_ENABLED': '1'}):
            app = server.create_server()
            tools = asyncio.run(names(app))
            self.assertIn('calendar_prepare_create', tools)
            self.assertIn('calendar_commit_create', tools)
            self.assertNotIn('calendar_approve_create', tools)
            self.assertFalse(tools['calendar_commit_create'].annotations.readOnlyHint)
            self.assertEqual(tools['calendar_commit_create'].inputSchema['required'], ['operation_id'])
            event_schema = tools['calendar_prepare_create'].inputSchema['properties']['event']
            self.assertFalse(event_schema['additionalProperties'])
            self.assertIn('timezone', event_schema['required'])
            self.assertIn('search_messages', tools)
            with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {'INBOXTETHER_CALDAV_CREATE_STATE_DIR': directory},
            ), patch.object(SogoCalendar, 'calendar_path', return_value=PERSONAL):
                prepared = asyncio.run(app.call_tool('calendar_prepare_create', {
                    'request_id': REQUEST, 'calendar_id': PERSONAL, 'event': EVENT,
                }))
                self.assertIn('approval_fingerprint', str(prepared))
                self.assertEqual(CreationService.load().transport.password_file, Path('/private/write'))
                for invalid in ('private-marker', {**EVENT, 'attendees': ['private-marker']}):
                    with self.assertRaisesRegex(Exception, 'invalid or unsupported fields') as caught:
                        asyncio.run(app.call_tool('calendar_prepare_create', {
                            'request_id': REQUEST, 'calendar_id': PERSONAL, 'event': invalid,
                        }))
                    self.assertNotIn('private-marker', str(caught.exception))


class RadarCreationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name))
        self.transport = CreateTransport('https://mail.example.com' + HOME, 'user@example.com', '/private/secret')
        self.transport.calendar_path = Mock(side_effect=lambda path: path)
        self.transport.exchange = Mock(side_effect=self.exchange)
        self.resources = {}
        self.puts = []
        self.service = CreationService(self.transport, self.store, {PERSONAL}, radar_limits=(3, 10))

    def exchange(self, calendar_id, key, raw=None):
        if raw is None:
            return (200, self.resources[key]) if key in self.resources else (404, None)
        self.puts.append((calendar_id, key, raw))
        if key in self.resources:
            return 412, None
        self.resources[key] = raw
        return 201, None

    def prepare(self, number=1, **changes):
        return self.service.prepare(f'synthetic-booking-{number:04d}', PERSONAL,
                                    EventSpec(**{**EVENT, **changes}))

    def test_owner_connection_creates_timed_and_all_day_without_terminal_approval(self):
        for number, fields in ((1, {}), (2, {'all_day': True, 'start': '2026-11-01', 'end': '2026-11-02'})):
            preview = self.prepare(number, **fields)
            self.assertNotIn('approval_fingerprint', preview)
            self.assertFalse(preview['human_approval_verified'])
            key = preview['proposal']['operation_id']
            receipt = self.service.commit(key)
            self.assertEqual(receipt['status'], 'verified')
            self.assertEqual(receipt['authorization_mode'], 'radar_owner_connection')
            self.assertFalse(receipt['human_approval_verified'])
            self.assertEqual(receipt['event_uid'], key + '@inboxtether')
            self.assertEqual(self.service.commit(key), receipt)
        self.assertEqual(len(self.puts), 2)
        self.assertIn(b'DTEND;VALUE=DATE:20261102', self.puts[-1][2])
        with self.store.db() as db:
            audit = [dict(row) for row in db.execute('SELECT * FROM radar_create_audit')]
        self.assertEqual(len(audit), 2)
        self.assertTrue(all(row['attempt'] == 1 and row['state'] == 'verified'
                            and row['outcome'] == 'accepted' for row in audit))
        self.assertNotIn(EVENT['title'], str(audit))
        self.assertNotIn(PERSONAL, str(audit))

    def test_modes_cannot_share_or_repurpose_proposals(self):
        terminal = CreationService(self.transport, self.store, {PERSONAL})
        pending = terminal.prepare(REQUEST, PERSONAL, EventSpec(**EVENT))
        with self.assertRaisesRegex(CalendarError, 'different authorization mode'):
            self.service.commit(pending['proposal']['operation_id'])
        with self.assertRaisesRegex(CalendarError, 'different authorization mode'):
            self.prepare()
        radar = self.prepare(2)['proposal']['operation_id']
        with self.assertRaisesRegex(CalendarError, 'different authorization mode'):
            terminal.commit(radar)
        item = self.store.get(radar)
        with self.assertRaisesRegex(CalendarError, 'changed or expired'):
            self.store.approve(radar, item['fingerprint'])
        self.transport.exchange.assert_not_called()

    def test_rate_limits_are_durable_and_replays_do_not_count(self):
        self.service.radar_limits = (1, 2)
        now = 1_800_000_000
        with patch('calendar_create.time.time', return_value=now):
            first = self.prepare()['proposal']['operation_id']
            second = self.prepare(2)['proposal']['operation_id']
            receipt = self.service.commit(first)
            self.service = CreationService(self.transport, Store(self.store.directory), {PERSONAL},
                                           radar_limits=(1, 2))
            self.assertEqual(self.service.commit(first), receipt)
            with self.assertRaisesRegex(CalendarError, 'rate limit reached'):
                self.service.commit(second)
            self.assertEqual(self.store.get(second)['attempts'], 0)
        with patch('calendar_create.time.time', return_value=now + 3601):
            self.service.commit(self.prepare(3)['proposal']['operation_id'])
        with patch('calendar_create.time.time', return_value=now + 7202):
            fourth = self.prepare(4)['proposal']['operation_id']
            with self.assertRaisesRegex(CalendarError, 'rate limit reached'):
                self.service.commit(fourth)
        self.assertEqual(len(self.puts), 2)

    def test_reconcile_cannot_put_and_an_uncertain_retry_counts(self):
        self.service.radar_limits = (1, 2)
        key = self.prepare()['proposal']['operation_id']
        self.assertEqual(self.service.commit(key, allow_write=False)['status'], 'pending')
        self.transport.exchange.assert_not_called()
        self.transport.exchange.side_effect = [(404, None), CalendarError('Timeout'), (404, None),
                                              (404, None), (404, None)]
        self.assertTrue(self.service.commit(key)['retry_allowed'])
        self.assertTrue(self.service.commit(key, allow_write=False)['retry_allowed'])
        with self.assertRaisesRegex(CalendarError, 'rate limit reached'):
            self.service.commit(key)
        self.assertEqual(sum(len(call.args) == 3 for call in self.transport.exchange.call_args_list), 1)
        with self.store.db() as db:
            self.assertEqual(tuple(db.execute('SELECT state, outcome FROM radar_create_audit').fetchone()),
                             ('uncertain', 'unknown'))

    def test_retry_uses_the_same_payload_and_is_audited_as_a_second_attempt(self):
        key = self.prepare()['proposal']['operation_id']

        def lose_first_attempt(calendar_id, operation_id, raw=None):
            if raw is not None and not self.puts:
                self.puts.append((calendar_id, operation_id, raw))
                raise CalendarError('Timeout')
            return self.exchange(calendar_id, operation_id, raw)

        self.transport.exchange.side_effect = lose_first_attempt
        self.assertEqual(self.service.commit(key)['status'], 'uncertain')
        self.assertTrue(self.service.commit(key, allow_write=False)['retry_allowed'])
        self.assertEqual(self.service.commit(key)['status'], 'verified')
        self.assertEqual(self.puts, [self.puts[0]] * 2)
        with self.store.db() as db:
            audit = [tuple(row) for row in db.execute('SELECT attempt, state FROM radar_create_audit ORDER BY attempt')]
        self.assertEqual(audit, [(1, 'uncertain'), (2, 'verified')])

    def test_expiry_and_revocation_fail_closed(self):
        proposal = self.prepare()['proposal']
        with patch('calendar_create.time.time', return_value=proposal['expires_at']):
            with self.assertRaisesRegex(CalendarError, 'expired'):
                self.service.commit(proposal['operation_id'])
        self.service.allowed = set()
        with self.assertRaisesRegex(CalendarError, 'no longer authorized'):
            self.service.commit(proposal['operation_id'])
        self.transport.exchange.assert_not_called()

    @patch.dict(os.environ, {
        'INBOXTETHER_CALDAV_HOME_URL': 'https://mail.example.com' + HOME,
        'INBOXTETHER_CALDAV_ACCOUNT': 'user@example.com',
        'INBOXTETHER_CALDAV_PASSWORD_FILE': '/private/read',
        'INBOXTETHER_CALDAV_CREATE_PASSWORD_FILE': '/private/write',
        'INBOXTETHER_CALDAV_CREATE_IDS': json.dumps([PERSONAL]),
    }, clear=True)
    def test_owner_launcher_is_separate_and_requires_both_flags(self):
        def tools(app):
            return {tool.name: tool for tool in asyncio.run(app.list_tools())}

        commit = 'calendar_commit_create'
        self.assertNotIn(commit, tools(calendar_owner_connection.create_server()))
        with patch.dict(os.environ, {'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED': '1'}):
            self.assertNotIn(commit, tools(calendar_owner_connection.create_server()))
            with patch.dict(os.environ, {'INBOXTETHER_CALDAV_CREATE_ENABLED': '1',
                                         'INBOXTETHER_CALDAV_CREATE_STATE_DIR': str(self.store.directory)}):
                ordinary = tools(server.create_server())
                self.assertIn('search_messages', ordinary)
                self.assertNotIn(commit, ordinary)
                with self.assertRaisesRegex(CalendarError, 'disabled on this connection'):
                    CreationService.load()
                available = tools(calendar_owner_connection.create_server())
                self.assertEqual(set(available), {
                    'calendar_list_calendars', 'calendar_list_events', 'calendar_get_event',
                    'calendar_search_events', 'calendar_free_busy',
                })
                with patch.dict(os.environ, {'INBOXTETHER_CALDAV_RADAR_MAX_PUTS_PER_DAY': '51'}):
                    with self.assertRaisesRegex(CalendarError, 'limit per day'):
                        CreationService.load(owner_connection=True)
