import asyncio
import json
import os
import unittest
from unittest.mock import Mock, patch

import server
from calendar_occurrences import free_busy, search
from sogo_calendar import CalendarError, SogoCalendar
from test_sogo_calendar import CALENDAR, EVENT, HOME, INVENTORY, PERSONAL, SHARED, multistatus, row


START = '2026-11-01T00:00:00-05:00'
END = '2026-11-05T00:00:00-06:00'
ZONE = 'America/Chicago'


def component(uid, fields):
    return f'BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:20261001T000000Z\n{fields}\nEND:VEVENT\n'


def resource(key, *events):
    return {'event_id': key, 'icalendar': (
        'BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic//EN\n'
        + ''.join(events) + 'END:VCALENDAR'
    )}


SERIES = resource(
    'series.ics',
    component('series', 'DTSTART;TZID=America/Chicago:20261031T140000\n'
              'DTEND;TZID=America/Chicago:20261031T143000\nRRULE:FREQ=DAILY;COUNT=4\nSUMMARY:Daily'),
    component('series', 'RECURRENCE-ID;TZID=America/Chicago:20261031T140000\n'
              'DTSTART;TZID=America/Chicago:20261103T160000\n'
              'DTEND;TZID=America/Chicago:20261103T163000\nSUMMARY:Moved appointment'),
    component('series', 'RECURRENCE-ID;TZID=America/Chicago:20261102T140000\nSTATUS:CANCELLED'),
)


class OccurrenceTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec=SogoCalendar)
        self.client.calendar_selection.return_value = {PERSONAL: {}, SHARED: {}}
        self.client.complete_resources.return_value = []

    def availability(self, ids=None, tentative=True):
        return free_busy(self.client, ids or [PERSONAL], START, END, ZONE, tentative)

    def test_search_expands_moved_and_cancelled_instances(self):
        self.client.complete_resources.return_value = [SERIES]
        events = search(self.client, [PERSONAL], START, END, 'daily', ZONE)['events']
        self.assertEqual([e['start'] for e in events],
                         ['2026-11-01T20:00:00+00:00', '2026-11-03T20:00:00+00:00'])
        moved = search(self.client, [PERSONAL], START, END, ' MoVeD ', ZONE)['events']
        self.assertEqual([(e['start'], e['recurrence_id']) for e in moved],
                         [('2026-11-03T22:00:00+00:00', '2026-10-31T14:00:00-05:00')])

    def test_all_day_uses_exclusive_local_end_across_dst(self):
        self.client.complete_resources.return_value = [resource('all-day.ics', component(
            'all-day', 'DTSTART;VALUE=DATE:20261101\nSUMMARY:All day\nLOCATION:Studio',
        ))]
        result = self.availability()
        self.assertFalse(result['available'])
        self.assertEqual(result['busy'], [{
            'start': '2026-11-01T05:00:00+00:00', 'end': '2026-11-02T06:00:00+00:00',
        }])
        events = search(self.client, [PERSONAL], START, END, 'studio', ZONE)['events']
        self.assertTrue(events[0]['all_day'])
        self.assertNotIn('location', events[0])

    def test_merged_availability_across_calendars_and_policy(self):
        first = resource('one.ics', component('one', 'DTSTART:20261102T080000Z\nDTEND:20261102T100000Z'))
        second = resource('two.ics', component('two', 'DTSTART:20261102T090000Z\nDTEND:20261102T110000Z'))
        tentative = resource('three.ics', component(
            'three', 'DTSTART:20261102T110000Z\nDTEND:20261102T120000Z\nSTATUS:TENTATIVE',
        ))
        transparent = resource('four.ics', component(
            'four', 'DTSTART:20261102T120000Z\nDTEND:20261102T140000Z\nTRANSP:TRANSPARENT',
        ))
        self.client.complete_resources.side_effect = lambda key: (
            [first] if key == PERSONAL else [second, tentative, transparent]
        )
        result = self.availability([PERSONAL, SHARED])
        self.assertEqual(result['busy'], [{
            'start': '2026-11-02T08:00:00+00:00', 'end': '2026-11-02T12:00:00+00:00',
        }])
        self.assertEqual(len(result['calendars']), 2)
        self.assertNotIn('event_id', str(result))
        result = self.availability([PERSONAL, SHARED], tentative=False)
        self.assertEqual(result['busy'][0]['end'], '2026-11-02T11:00:00+00:00')

    def test_clips_floating_events_and_ignores_end_boundary(self):
        self.client.complete_resources.return_value = [
            resource('floating.ics', component('floating', 'DTSTART:20261031T233000\nDURATION:PT1H')),
            resource('outside.ics', component('outside', 'DTSTART:20261105T000000\nDURATION:PT1H')),
        ]
        self.assertEqual(self.availability()['busy'], [{
            'start': '2026-11-01T05:00:00+00:00', 'end': '2026-11-01T05:30:00+00:00',
        }])

    def test_explicit_dates_and_cancelled_master(self):
        self.client.complete_resources.return_value = [
            resource('dates.ics', component(
                'dates', 'DTSTART:20261101T120000Z\nDURATION:PT1H\nSUMMARY:Consultation\n'
                'RDATE:20261102T120000Z,20261103T120000Z\nEXDATE:20261102T120000Z',
            )),
            resource('cancelled.ics', component(
                'cancelled', 'DTSTART:20261101T140000Z\nDURATION:PT1H\nSUMMARY:Consultation\n'
                'RRULE:FREQ=DAILY;COUNT=3\nSTATUS:CANCELLED',
            )),
        ]
        events = search(self.client, [PERSONAL], START, END, 'consultation', ZONE)['events']
        self.assertEqual([e['start'] for e in events],
                         ['2026-11-01T12:00:00+00:00', '2026-11-03T12:00:00+00:00'])

    def test_calendar_supplied_timezone_interprets_floating_times(self):
        item = resource('floating.ics', component('floating', 'DTSTART:20261102T090000\nDURATION:PT1H'))
        item['icalendar'] = item['icalendar'].replace('VERSION:2.0', 'VERSION:2.0\nX-WR-TIMEZONE:Europe/Paris')
        self.client.complete_resources.return_value = [item]
        self.assertEqual(self.availability()['busy'], [{
            'start': '2026-11-02T08:00:00+00:00', 'end': '2026-11-02T09:00:00+00:00',
        }])

    def test_empty_success_and_inaccessible_or_failed_calendar(self):
        self.assertTrue(self.availability([PERSONAL, SHARED])['available'])
        with self.assertRaisesRegex(CalendarError, 'absent or inaccessible'):
            self.availability([PERSONAL, 'missing'])
        self.client.complete_resources.side_effect = [[], CalendarError('CalDAV connection failed or timed out.')]
        with self.assertRaisesRegex(CalendarError, 'timed out'):
            self.availability([PERSONAL, SHARED])

    def test_malformed_unknown_timezone_and_complex_rule_fail_closed(self):
        for data in ('not iCalendar', resource('event.ics', component(
            'event', 'DTSTART;TZID=Invalid/Zone:20261101T140000\nDURATION:PT1H',
        ))['icalendar'], resource('event.ics', component(
            'event', 'DTSTART:20261101T140000Z\nRRULE:FREQ=SECONDLY',
        ))['icalendar']):
            with self.subTest(data=data):
                self.client.complete_resources.return_value = [{'event_id': 'event.ics', 'icalendar': data}]
                with self.assertRaises(CalendarError):
                    self.availability()


def calendar_inventory(etag='&quot;1&quot;'):
    return multistatus(row(PERSONAL, CALENDAR), row(EVENT, f'<D:resourcetype/><D:getetag>{etag}</D:getetag>'))


class CompleteReadTests(unittest.TestCase):
    def setUp(self):
        self.client = SogoCalendar('https://mail.example.com' + HOME, 'user@example.com', 'private-file')

    def test_inventory_and_versions_are_checked(self):
        data = SERIES['icalendar']
        response = multistatus(row(EVENT, f'<C:calendar-data>{data}</C:calendar-data><D:getetag>"1"</D:getetag>'))
        for final, feed, expected in (
            (calendar_inventory(), response, None),
            (calendar_inventory('"2"'), response, 'changed during the check'),
            (calendar_inventory(), response.replace(b'"1"', b'"2"'), 'changed during the check'),
            (calendar_inventory(), multistatus(), 'did not return'),
        ):
            with self.subTest(expected=expected), patch.object(
                self.client, 'request', side_effect=[calendar_inventory(), feed, final],
            ):
                if expected:
                    with self.assertRaisesRegex(CalendarError, expected):
                        self.client.complete_resources(PERSONAL)
                else:
                    self.assertEqual(self.client.complete_resources(PERSONAL)[0]['icalendar'], data)

    def test_empty_inventory_is_checked_twice(self):
        empty = multistatus(row(PERSONAL, CALENDAR))
        with patch.object(self.client, 'request', side_effect=[empty, empty]) as request:
            self.assertEqual(self.client.complete_resources(PERSONAL), [])
            self.assertEqual([call.args[0] for call in request.call_args_list], ['PROPFIND', 'PROPFIND'])

    def test_incomplete_inventory_does_not_look_empty(self):
        responses = (multistatus(), multistatus(row(PERSONAL, CALENDAR),
                                              row(EVENT, '<D:resourcetype/>', '403 Forbidden')))
        for response in responses:
            with patch.object(self.client, 'request', return_value=response):
                with self.assertRaises(CalendarError):
                    self.client.complete_resources(PERSONAL)

    @patch.dict(os.environ, {
        'INBOXTETHER_CALDAV_HOME_URL': 'https://mail.example.com' + HOME,
        'INBOXTETHER_CALDAV_ACCOUNT': 'user@example.com',
        'INBOXTETHER_CALDAV_PASSWORD_FILE': 'private-file',
        'INBOXTETHER_CALDAV_FULL_VISIBILITY_IDS': '[]',
    }, clear=True)
    def test_mcp_rejects_unverified_calendar_before_network(self):
        app = server.create_server()
        with patch.object(SogoCalendar, 'request') as request:
            with self.assertRaisesRegex(Exception, 'not configured for full-visibility'):
                asyncio.run(app.call_tool('calendar_free_busy', {
                    'calendar_ids': [PERSONAL], 'start': START, 'end': END,
                }))
            request.assert_not_called()

    @patch.dict(os.environ, {
        'INBOXTETHER_CALDAV_HOME_URL': 'https://mail.example.com' + HOME,
        'INBOXTETHER_CALDAV_ACCOUNT': 'user@example.com',
        'INBOXTETHER_CALDAV_PASSWORD_FILE': 'private-file',
        'INBOXTETHER_CALDAV_FULL_VISIBILITY_IDS': json.dumps([PERSONAL]),
    }, clear=True)
    def test_mcp_search_and_availability_use_versioned_reads(self):
        data = SERIES['icalendar']
        feed = multistatus(row(EVENT, f'<C:calendar-data>{data}</C:calendar-data><D:getetag>"1"</D:getetag>'))
        replies = [INVENTORY, calendar_inventory(), feed, calendar_inventory()]
        app = server.create_server()

        async def run():
            tools = {tool.name: tool for tool in await app.list_tools()}
            args = {'calendar_ids': [PERSONAL], 'start': START, 'end': END}
            for name, extra in (('calendar_search_events', {'text': 'moved'}), ('calendar_free_busy', {})):
                self.assertTrue(tools[name].annotations.readOnlyHint)
                with patch.object(SogoCalendar, 'request', side_effect=replies) as request:
                    result = await app.call_tool(name, {**args, **extra})
                    self.assertIn('2026-11-03T22:00:00+00:00', str(result))
                    self.assertEqual([call.args[0] for call in request.call_args_list],
                                     ['PROPFIND', 'PROPFIND', 'REPORT', 'PROPFIND'])
                    if name == 'calendar_free_busy':
                        self.assertNotIn('Moved appointment', str(result))
        asyncio.run(run())

    def test_bad_selections_fail_before_discovery(self):
        with patch.object(self.client, 'request', return_value=INVENTORY) as request:
            for ids in ([], [PERSONAL, PERSONAL], [str(i) for i in range(11)]):
                with self.assertRaisesRegex(CalendarError, '1 to 10 distinct'):
                    self.client.calendar_selection(ids)
            request.assert_not_called()
