import os
import unittest
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as XML

import server
from sogo_calendar import CAL, DAV, CalendarError, MAX_RESPONSE, SogoCalendar, parse_multistatus


HOME = '/SOGo/dav/user@example.com/Calendar/'
PERSONAL = HOME + 'personal/'
SHARED = HOME + 'shared/'
EVENT = PERSONAL + 'abc.ics'
START = '2026-11-01T01:30:00-05:00'
END = '2026-11-01T01:30:00-06:00'
ICS = (
    'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:abc\n'
    'DTSTART;VALUE=DATE:20261101\nRRULE:FREQ=WEEKLY;COUNT=3\n'
    'EXDATE;VALUE=DATE:20261108\nEND:VEVENT\nEND:VCALENDAR'
)


def multistatus(*rows):
    return ('<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            + ''.join(rows) + '</D:multistatus>').encode()


def row(path, props, status='200 OK'):
    return (f'<D:response><D:href>{path}</D:href><D:propstat><D:prop>{props}</D:prop>'
            f'<D:status>HTTP/1.1 {status}</D:status></D:propstat></D:response>')


COLLECTION = '<D:resourcetype><D:collection/></D:resourcetype>'
CALENDAR = '<D:resourcetype><D:collection/><C:calendar/></D:resourcetype>'
INVENTORY = multistatus(
    row(HOME.rstrip('/').replace('@', '%40'), COLLECTION),
    row('personal/', CALENDAR + '<D:displayname>Personal</D:displayname>'),
    row('https://mail.example.com' + SHARED, CALENDAR),
    row('inbox/', COLLECTION),
)


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.client = SogoCalendar('https://mail.example.com' + HOME, 'user@example.com', 'private-file')

    def test_discovery(self):
        with patch.object(self.client, 'request', return_value=INVENTORY) as request:
            self.assertEqual(self.client.calendars(), {
                PERSONAL: {'calendar_id': PERSONAL, 'name': 'Personal'},
                SHARED: {'calendar_id': SHARED, 'name': None},
            })
        self.assertEqual(request.call_args.args, ('PROPFIND', HOME))

    def test_invalid_discovery_does_not_return_empty_inventory(self):
        for response in (multistatus(), multistatus(row(HOME, COLLECTION, '403 Forbidden'))):
            with self.subTest(response=response), patch.object(self.client, 'request', return_value=response):
                with self.assertRaises(CalendarError):
                    self.client.calendars()

    def test_listing_uses_actual_offsets_and_preserves_source_data(self):
        feed = multistatus(row(EVENT, f'<C:calendar-data>{ICS}</C:calendar-data>'))
        with patch.object(self.client, 'request', side_effect=[INVENTORY, feed]) as request:
            self.assertEqual(self.client.events(PERSONAL, START, END),
                             [{'event_id': EVENT, 'icalendar': ICS}])
        self.assertEqual(request.call_args.args, ('REPORT', PERSONAL))
        query = request.call_args.kwargs['document']
        expected = {'start': '20261101T063000Z', 'end': '20261101T073000Z'}
        self.assertEqual(query.find('.//' + CAL + 'time-range').attrib, expected)

    def test_list_rejects_partial_rows(self):
        feed = multistatus(row(EVENT, '<C:calendar-data/>', '404 Not Found'))
        with patch.object(self.client, 'request', side_effect=[INVENTORY, feed]):
            with self.assertRaisesRegex(CalendarError, 'incomplete event data'):
                self.client.events(PERSONAL, START, END)

    def test_get_fetches_only_a_resource_in_the_selected_calendar(self):
        feed = multistatus(row(EVENT, f'<C:calendar-data>{ICS}</C:calendar-data>'))
        with patch.object(self.client, 'request', side_effect=[INVENTORY, feed]) as request:
            self.assertEqual(self.client.event(PERSONAL, EVENT)['icalendar'], ICS)
            self.assertEqual(request.call_args.args, ('REPORT', PERSONAL))
            query = request.call_args.kwargs['document']
            self.assertEqual(query.tag, CAL + 'calendar-multiget')
            self.assertEqual(query.findtext(DAV + 'href'), EVENT)
        with patch.object(self.client, 'request', side_effect=[INVENTORY, feed]):
            with self.assertRaisesRegex(CalendarError, 'did not return the requested event'):
                self.client.event(PERSONAL, PERSONAL + 'other.ics')
        for value in (SHARED + 'abc.ics', '../abc.ics', '%2e%2e/abc.ics',
                      'https://other.example.com' + EVENT, 'nested/abc.ics', EVENT + '?q=x'):
            with self.subTest(value=value), patch.object(self.client, 'request', return_value=INVENTORY) as request:
                with self.assertRaises(CalendarError):
                    self.client.event(PERSONAL, value)
                self.assertEqual(request.call_count, 1)

    def test_invalid_time_window_is_rejected_before_network(self):
        with patch.object(self.client, 'request') as request:
            with self.assertRaises(CalendarError):
                self.client.events(PERSONAL, '2026-11-01T01:30:00', END)
            with self.assertRaises(CalendarError):
                self.client.events(PERSONAL, END, START)
            request.assert_not_called()

    def test_xml_entities_are_rejected(self):
        with self.assertRaisesRegex(CalendarError, 'Invalid CalDAV XML'):
            parse_multistatus(b'<!DOCTYPE x [<!ENTITY y "x">]><x>&y;</x>')

    @patch('sogo_calendar.read_secret', return_value='synthetic-password')
    @patch('sogo_calendar.HTTPSConnection')
    def test_request_is_bounded_and_does_not_follow_redirects(self, https, secret):
        response = MagicMock(status=207)
        response.getheader.return_value = 'identity'
        response.read.return_value = b'x' * (MAX_RESPONSE + 1)
        https.return_value.getresponse.return_value.__enter__.return_value = response
        propfind = XML.Element(DAV + 'propfind')
        with self.assertRaisesRegex(CalendarError, 'exceeds safety limit'):
            self.client.request('PROPFIND', HOME, document=propfind)
        response.read.assert_called_once_with(MAX_RESPONSE + 1)
        headers = https.return_value.request.call_args.kwargs['headers']
        self.assertTrue(headers['Authorization'].startswith('Basic '))
        self.assertEqual(headers['Depth'], '1')
        response.status = 302
        with self.assertRaisesRegex(CalendarError, 'HTTP 302'):
            self.client.request('PROPFIND', HOME, document=propfind)
        self.assertEqual(https.call_count, 2)
        response.status = 401
        with self.assertRaisesRegex(CalendarError, 'authentication failed'):
            self.client.request('PROPFIND', HOME, document=propfind)
        https.return_value.request.side_effect = TimeoutError('private response details')
        with self.assertRaisesRegex(CalendarError, '^CalDAV connection failed or timed out\\.$'):
            self.client.request('PROPFIND', HOME, document=propfind)
        secret.reset_mock()
        with self.assertRaisesRegex(CalendarError, 'read-only guard'):
            self.client.request('PUT', EVENT, document=propfind)
        secret.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    def test_tools_are_opt_in(self):
        def names():
            return set(server.create_server()._tool_manager._tools)

        before = names()
        with patch.dict(os.environ, {
            'INBOXTETHER_CALDAV_HOME_URL': 'https://mail.example.com' + HOME,
            'INBOXTETHER_CALDAV_ACCOUNT': 'user@example.com',
            'INBOXTETHER_CALDAV_PASSWORD_FILE': 'private-file',
        }):
            self.assertEqual(names() - before, {
                'calendar_list_calendars', 'calendar_list_events', 'calendar_get_event',
                'calendar_search_events', 'calendar_free_busy',
            })
            self.assertTrue(before <= names())
