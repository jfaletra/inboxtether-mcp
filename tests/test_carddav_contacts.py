import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as X

from mcp.server.fastmcp import FastMCP

from calendar_accounts import CalendarAccounts
from carddav_contacts import (
    CARD, DAV, MAX_BOOK_CONTACTS, MAX_CONTACTS, MAX_CARD_BYTES, MAX_RESPONSE, ContactAccounts, ContactError,
    SogoContacts, parse_contact, register, register_configured,
)

HOME = '/SOGo/dav/user@example.com/Contacts/'
BOOK = HOME + 'personal/'
HIDDEN = HOME + 'hidden/'
ACCOUNT = 'owner'
BOOK_ID = ACCOUNT + ':' + BOOK


def card(name='Nick Example', emails=('nick@example.net',), extra='', version='3.0'):
    return ('BEGIN:VCARD\r\nVERSION:' + version + '\r\nFN:' + name
            + '\r\nN:Example;Nick;;;\r\n'
            + ''.join('EMAIL;TYPE=INTERNET:' + email + '\r\n' for email in emails)
            + extra + 'END:VCARD\r\n')


def sogo_card(given, family, email):
    # Reproduce the reported live shape, not a copy of a private server payload:
    # vCard 3.0, LF only, no FN, N with two components, one explicit EMAIL.
    return f'BEGIN:VCARD\nVERSION:3.0\nN:{family};{given}\nEMAIL:{email}\nEND:VCARD\n'


def multistatus(rows):
    root = X.Element(DAV + 'multistatus')
    for path, fields in rows:
        row = X.SubElement(root, DAV + 'response')
        X.SubElement(row, DAV + 'href').text = path
        propstat = X.SubElement(row, DAV + 'propstat')
        X.SubElement(propstat, DAV + 'status').text = 'HTTP/1.1 200 OK'
        prop = X.SubElement(propstat, DAV + 'prop')
        for tag, value in fields.items():
            field = X.SubElement(prop, tag)
            if isinstance(value, tuple):
                X.SubElement(field, value[0]).text = value[1]
            else:
                field.text = value
    return X.tostring(root)


def principal(path=HOME.removesuffix('Contacts/')):
    return multistatus([(HOME, {DAV + 'current-user-principal': (DAV + 'href', path)})])


def discovery():
    return multistatus([(HOME, {}), (BOOK, {DAV + 'resourcetype': (CARD + 'addressbook', None),
                                                    DAV + 'displayname': 'Personal'}),
                        (HIDDEN, {DAV + 'resourcetype': (CARD + 'addressbook', None),
                                  DAV + 'displayname': 'DO NOT EXPOSE'})])


def contact_rows(values):
    return multistatus([(BOOK + str(i) + '.vcf', {CARD + 'address-data': value, DAV + 'getetag': '"v1"'})
                        for i, value in enumerate(values)])


def calendars():
    records = []
    for key, domain in ((ACCOUNT, 'mail.example.com'), ('other', 'mail.example.net')):
        records.append({'id': key, 'home_url': 'https://' + domain + HOME.replace('/Contacts/', '/Calendar/'),
                        'username': 'user@example.com', 'password_file': '/protected/' + key,
                        'read_ids': [BOOK.replace('/Contacts/', '/Calendar/')], 'aliases': {}})
    return CalendarAccounts(json.dumps(records))


def configured(two=False):
    records = [{'account_id': ACCOUNT, 'home_url': 'https://mail.example.com' + HOME, 'read_ids': [BOOK]}]
    if two:
        records.append({'account_id': 'other', 'home_url': 'https://mail.example.net' + HOME, 'read_ids': [BOOK]})
    return ContactAccounts({'enabled': True, 'accounts': records}, calendars())


class VCardTests(unittest.TestCase):
    def test_v3_v4_and_multiple_addresses_are_retained_without_choosing_pref(self):
        for version in ('3.0', '4.0'):
            with self.subTest(version=version):
                value = parse_contact(card(emails=('nick@example.net', 'nick@work.example', 'nick@example.net'),
                                           extra='EMAIL;PREF=1:nick@preferred.example\r\n', version=version))
                self.assertEqual(value['name'], 'Nick Example')
                self.assertEqual(value['emails'], ['nick@example.net', 'nick@work.example', 'nick@preferred.example'])
                self.assertEqual((value['given_name'], value['family_name']), ('Nick', 'Example'))

    def test_grouped_email_quoted_parameters_folding_and_escaped_text(self):
        raw = card('Nick\\, Exam\r\n ple', emails=(), extra='item1.EMAIL;TYPE="work,internet":nick@example.net\r\n')
        value = parse_contact(raw)
        self.assertEqual(value['name'], 'Nick, Example')
        self.assertEqual(value['emails'], ['nick@example.net'])

    def test_non_ascii_name_and_casefolding(self):
        value = parse_contact(card('Nİck José'))
        self.assertIn('ni̇ck josé', value['_names'])

    def test_invalid_email_is_never_guessed_or_parsed_from_display_name(self):
        value = parse_contact(card(emails=('Nick <nick@example.net>', 'mailto:nick@example.net', 'bad address')))
        self.assertEqual(value['emails'], [])
        self.assertEqual(value['unusable_email_count'], 3)

    def test_no_email_remains_a_contact_with_no_resolved_recipient(self):
        self.assertEqual(parse_contact(card(emails=()))['emails'], [])

    def test_unsupported_encoding_and_malformed_cards_fail_closed(self):
        values = [card(version='2.1'), card().replace('FN:', 'FN;ENCODING=QUOTED-PRINTABLE:'),
                  card().replace('FN:', 'FN;CHARSET=ISO-8859-1:'), card() + card(),
                  card().replace('N:Example;Nick;;;', 'N:a;b;c;d;e;f'), card().replace('FN:', 'FN:\x00'),
                  card().replace('FN:', 'FN:Other\r\nFN:'), card().replace('VERSION:3.0', 'VERSION:3.0\r\nVERSION:4.0'),
                  ' ' + card(), card().replace('FN:', 'FN;TYPE="broken:'), 'x' * (MAX_CARD_BYTES + 1)]
        for raw in values:
            with self.subTest(raw=raw[:40]), self.assertRaises(ContactError):
                parse_contact(raw)

    def test_groups_are_not_individual_candidates(self):
        self.assertEqual(parse_contact(card(extra='KIND:group\r\n'))['kind'], 'group')

    def test_sogo_no_fn_and_short_n_preserve_the_two_fixture_names_and_emails(self):
        for given, family, email in [('Alex', 'Example', 'recipient@example.net'),
                                     ('Robin', 'Sample', 'info@example.com')]:
            with self.subTest(given=given):
                result = parse_contact(sogo_card(given, family, email))
                self.assertEqual(result['name'], given + ' ' + family)
                self.assertEqual(result['given_name'], given)
                self.assertEqual(result['family_name'], family)
                self.assertEqual(result['emails'], [email])
                self.assertIn((given + ' ' + family).casefold(), result['_names'])
                self.assertIn(given.casefold(), result['_names'])

    def test_omitted_trailing_components_do_not_reorder_or_invent_name_fields(self):
        for structured in ('Example', 'Example;Alex', 'Example;Alex;', 'Example;Alex;;', 'Example;Alex;;;'):
            with self.subTest(structured=structured):
                raw = sogo_card('Alex', 'Example', 'recipient@example.net').replace('N:Example;Alex', 'N:' + structured)
                result = parse_contact(raw)
                self.assertEqual(result['family_name'], 'Example')
                self.assertEqual(result['given_name'], '' if structured == 'Example' else 'Alex')
                self.assertEqual(result['emails'], ['recipient@example.net'])

    def test_short_names_keep_escape_and_excess_component_guards(self):
        raw = sogo_card('Alex', 'Example', 'recipient@example.net')
        escaped = parse_contact(raw.replace('N:Example;Alex', r'N:Example\;Family;Alex'))
        self.assertEqual(escaped['family_name'], 'Example;Family')
        for value in ('one;two;three;four;five;six', 'Example;Alex' + '\\'):
            with self.subTest(value=value), self.assertRaises(ContactError):
                parse_contact(raw.replace('N:Example;Alex', 'N:' + value))


class CarddavWireTests(unittest.TestCase):
    def setUp(self):
        self.client = SogoContacts('https://mail.example.com' + HOME, 'user@example.com', '/protected/owner', [BOOK])

    def test_read_only_guard_rejects_writes_and_unlisted_paths_before_reading_secret(self):
        with patch('carddav_contacts.read_secret') as secret, patch('carddav_contacts.HTTPSConnection') as connect:
            for method, path, tag in [('PUT', BOOK + 'x.vcf', CARD + 'addressbook-query'),
                                      ('DELETE', BOOK + 'x.vcf', DAV + 'propfind'),
                                      ('PATCH', BOOK, DAV + 'propfind'),
                                      ('REPORT', HIDDEN, CARD + 'addressbook-query'),
                                      ('REPORT', BOOK, CARD + 'addressbook-multiget'),
                                      ('PROPFIND', BOOK, DAV + 'propfind')]:
                with self.subTest(method=method, path=path), self.assertRaises(ContactError):
                    self.client.request(method, path, document=X.Element(tag))
            secret.assert_not_called()
            connect.assert_not_called()

    @patch('carddav_contacts.read_secret', return_value='synthetic-only')
    @patch('carddav_contacts.HTTPSConnection')
    def test_wire_sends_only_read_requests_and_sanitizes_failures(self, connect, secret):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status = 207
        response.getheader.return_value = 'identity'
        response.read.return_value = b'result'
        self.assertEqual(self.client.request('REPORT', BOOK, document=X.Element(CARD + 'addressbook-query')), b'result')
        args, kwargs = connect.return_value.request.call_args
        self.assertEqual(args, ('REPORT', BOOK))
        self.assertEqual(kwargs['headers']['Depth'], '1')
        self.assertEqual(kwargs['headers']['Authorization'], 'Basic dXNlckBleGFtcGxlLmNvbTpzeW50aGV0aWMtb25seQ==')
        self.assertEqual(connect.call_args.args, ('mail.example.com', 443))
        response.read.assert_called_with(MAX_RESPONSE + 1)
        for status in (401, 403, 302, 500, 507):
            response.status = status
            with self.subTest(status=status), self.assertRaises(ContactError) as error:
                self.client.request('REPORT', BOOK, document=X.Element(CARD + 'addressbook-query'))
            self.assertNotIn('synthetic-only', str(error.exception))
        response.status = 207
        response.read.return_value = b'x' * (MAX_RESPONSE + 1)
        with self.assertRaisesRegex(ContactError, 'safety limit'):
            self.client.request('REPORT', BOOK, document=X.Element(CARD + 'addressbook-query'))
        connect.return_value.request.side_effect = TimeoutError('sensitive upstream diagnostic')
        with self.assertRaisesRegex(ContactError, '^CardDAV connection failed or timed out.$'):
            self.client.request('REPORT', BOOK, document=X.Element(CARD + 'addressbook-query'))

    def test_discovery_verifies_principal_and_exposes_only_allowlisted_book(self):
        with patch.object(self.client, 'request', side_effect=[principal(), discovery()]) as request:
            self.assertEqual(self.client.address_books(), {BOOK: {'name': 'Personal'}})
            self.assertEqual(request.call_args_list[0].kwargs['depth'], '0')
        for identity in ('/SOGo/dav/other@example.com/', 'https://evil.example/SOGo/dav/user@example.com/',
                         '/SOGo/dav/user@example.com/?secret=1', ''):
            with self.subTest(identity=identity), patch.object(self.client, 'request', return_value=principal(identity)), \
                    self.assertRaises(ContactError):
                self.client.address_books()

    def test_missing_principal_or_untrusted_discovery_xml_is_rejected(self):
        for raw in (multistatus([(HOME, {})]), b'<!DOCTYPE x><x/>', b'<html>login</html>', b'not xml'):
            with self.subTest(raw=raw), patch.object(self.client, 'request', return_value=raw), self.assertRaises(ContactError):
                self.client.address_books()

    def test_name_query_projects_only_needed_properties_and_locally_checks_matches(self):
        with patch.object(self.client, 'request', return_value=contact_rows([card(), card('Someone Else').replace('N:Example;Nick;;;', 'N:Else;Someone;;;')])) as request:
            rows = self.client.search_book(BOOK, 'nICK', 'exact')
            self.assertEqual(len(rows), 1)
            document = request.call_args.kwargs['document']
            data = document.find(DAV + 'prop').find(CARD + 'address-data')
            self.assertEqual({item.attrib['name'] for item in data}, {'VERSION', 'FN', 'N', 'EMAIL', 'KIND', 'X-ADDRESSBOOKSERVER-KIND'})
            self.assertNotIn('NOTE', X.tostring(document).decode())
            self.assertIsNone(document.find(CARD + 'filter'))
            self.assertEqual(document.findall('.//' + CARD + 'text-match'), [])
            self.assertEqual(document.find(CARD + 'limit').findtext(CARD + 'nresults'), '2001')

    def test_given_and_full_names_work_when_server_filters_only_surnames(self):
        fixtures = [('Example', sogo_card('Alex', 'Example', 'recipient@example.net')),
                    ('Sample', sogo_card('Robin', 'Sample', 'info@example.com'))]
        def sogo_report(_method, _path, *, document):
            # The old FN/N filter lost first/full-name results before local matching.
            filters = document.findall('.//' + CARD + 'text-match')
            requested = filters[0].text.casefold() if filters else None
            return contact_rows([raw for family, raw in fixtures
                                 if requested is None or requested in family.casefold()])
        with patch.object(self.client, 'request', side_effect=sogo_report):
            for query, mode, expected, email in [
                    ('Alex Example', 'exact', 'Alex Example', 'recipient@example.net'),
                    ('aLEX', 'partial', 'Alex Example', 'recipient@example.net'),
                    ('Example', 'partial', 'Alex Example', 'recipient@example.net'),
                    ('Robin Sample', 'exact', 'Robin Sample', 'info@example.com'),
                    ('Robin', 'partial', 'Robin Sample', 'info@example.com'),
                    ('Sample', 'partial', 'Robin Sample', 'info@example.com')]:
                with self.subTest(query=query):
                    rows = self.client.search_book(BOOK, query, mode)
                    self.assertEqual([(row['name'], row['emails']) for row in rows], [(expected, [email])])
            self.assertEqual(self.client.search_book(BOOK, 'Al', 'exact'), [])
            self.assertEqual(self.client.search_book(BOOK, 'Unknown', 'partial'), [])

    def test_unfiltered_book_limit_fails_before_reporting_a_unique_or_empty_match(self):
        raw = contact_rows([sogo_card('Robin', 'Sample', 'info@example.com')] * MAX_BOOK_CONTACTS
                           + [sogo_card('Alex', 'Example', 'recipient@example.net')])
        with patch.object(self.client, 'request', return_value=raw):
            for query in ('Alex', 'Nobody'):
                with self.subTest(query=query), self.assertRaisesRegex(ContactError, 'lookup is incomplete'):
                    self.client.search_book(BOOK, query, 'partial')

    def test_full_scan_keeps_a_unique_match_at_the_100_resource_boundary(self):
        raw = contact_rows([sogo_card('Robin', 'Sample', 'info@example.com')] * 99
                           + [sogo_card('Alex', 'Example', 'recipient@example.net')])
        with patch.object(self.client, 'request', return_value=raw):
            rows = self.client.search_book(BOOK, 'Alex Example', 'exact')
        self.assertEqual([(row['name'], row['emails']) for row in rows], [('Alex Example', ['recipient@example.net'])])

    def test_large_books_find_exact_and_partial_matches_at_the_end_with_all_addresses(self):
        target = sogo_card('Nick', 'Example', 'nick@example.net').replace(
            'END:VCARD', 'EMAIL:nick@work.example\nEND:VCARD')
        for size in (101, 500, 2000):
            raw = contact_rows([sogo_card('Other', 'Person', 'other@example.net')] * (size - 1) + [target])
            for name, match in (('Nick Example', 'exact'), ('nICK', 'partial'), ('Example', 'partial')):
                with self.subTest(size=size, name=name), patch.object(self.client, 'request', return_value=raw):
                    rows = self.client.search_book(BOOK, name, match)
                    self.assertEqual([(row['name'], row['emails']) for row in rows],
                                     [('Nick Example', ['nick@example.net', 'nick@work.example'])])

    def test_malformed_contact_after_100_cannot_yield_a_unique_or_empty_match(self):
        raw = contact_rows([card()] + [sogo_card('Other', 'Person', 'other@example.net')] * 498
                           + [card(version='2.1')])
        for name in ('Nick', 'Nobody'):
            with self.subTest(name=name), patch.object(self.client, 'request', return_value=raw), self.assertRaises(ContactError):
                self.client.search_book(BOOK, name, 'partial')

    def test_server_truncation_rejects_valid_matches_with_or_without_error_marker(self):
        for marker in (False, True):
            root = X.fromstring(contact_rows([card()]))
            row = X.SubElement(root, DAV + 'response')
            X.SubElement(row, DAV + 'href').text = BOOK
            X.SubElement(row, DAV + 'status').text = 'HTTP/1.1 507 Insufficient Storage'
            if marker:
                X.SubElement(X.SubElement(row, DAV + 'error'), DAV + 'number-of-matches-within-limits')
            for name in ('Nick', 'Nobody'):
                with self.subTest(marker=marker, name=name), patch.object(self.client, 'request', return_value=X.tostring(root)), self.assertRaises(ContactError):
                    self.client.search_book(BOOK, name, 'partial')

    def test_root_level_errors_and_invalid_root_children_cannot_hide_incomplete_results(self):
        for tag in ('error', 'status', 'unexpected'):
            root = X.fromstring(contact_rows([card()]))
            child = X.SubElement(root, DAV + tag)
            if tag == 'error':
                X.SubElement(child, DAV + 'number-of-matches-within-limits')
            with self.subTest(tag=tag), patch.object(self.client, 'request', return_value=X.tostring(root)), \
                    self.assertRaisesRegex(ContactError, 'incomplete contact scan'):
                self.client.search_book(BOOK, 'Nick', 'partial')

    def test_standard_multistatus_description_does_not_invalidate_a_complete_scan(self):
        root = X.fromstring(contact_rows([card()]))
        X.SubElement(root, DAV + 'responsedescription').text = 'Complete results'
        with patch.object(self.client, 'request', return_value=X.tostring(root)):
            self.assertEqual(len(self.client.search_book(BOOK, 'Nick', 'partial')), 1)

    def test_exact_does_not_treat_prefix_as_equal(self):
        with patch.object(self.client, 'request', return_value=contact_rows([card('Nicholas').replace('N:Example;Nick;;;', 'N:Example;Nicholas;;;')])):
            self.assertEqual(self.client.search_book(BOOK, 'Nick', 'exact'), [])
            self.assertEqual(len(self.client.search_book(BOOK, 'nich', 'partial')), 1)

    def test_contact_data_limits_duplicates_foreign_hrefs_and_partial_status_rejected(self):
        bad_status = multistatus([(BOOK + 'x.vcf', {CARD + 'address-data': card()})]).replace(b'200 OK', b'507 Limited')
        values = [contact_rows([card()] * (MAX_BOOK_CONTACTS + 1)), bad_status,
                  multistatus([('https://other.example/x.vcf', {CARD + 'address-data': card()})]),
                  multistatus([(BOOK + '../outside.vcf', {CARD + 'address-data': card()})]),
                  multistatus([(BOOK + 'x.vcf', {CARD + 'address-data': card()})] * 2),
                  multistatus([(BOOK + 'x.vcf', {DAV + 'getetag': '"only"'})])]
        for raw in values:
            with self.subTest(raw=raw[:80]), patch.object(self.client, 'request', return_value=raw), self.assertRaises(ContactError):
                self.client.search_book(BOOK, 'Nick', 'partial')


class ContactAccountTests(unittest.TestCase):
    def test_two_domains_have_separate_readers_and_existing_separate_credentials(self):
        accounts = configured(two=True)
        self.assertEqual(accounts.accounts[ACCOUNT].password_file, '/protected/owner')
        self.assertEqual(accounts.accounts['other'].password_file, '/protected/other')
        with patch.object(accounts.accounts[ACCOUNT], 'address_books', return_value={BOOK: {'name': 'Personal'}}), \
                patch.object(accounts.accounts['other'], 'address_books', side_effect=AssertionError('Cross-account read')):
            rows = accounts.address_books(ACCOUNT)
            self.assertEqual(rows[0]['address_book_id'], BOOK_ID)
            self.assertEqual(rows[0]['account_id'], ACCOUNT)

    def test_configuration_cannot_override_credentials_or_use_unknown_accounts_origins_or_principals(self):
        original = {'account_id': ACCOUNT, 'home_url': 'https://mail.example.com' + HOME, 'read_ids': [BOOK]}
        changes = [{'account_id': 'unknown'}, {'password_file': '/another/secret'},
                   {'home_url': 'https://evil.example' + HOME},
                   {'home_url': 'https://mail.example.com' + HOME.replace('user@example.com', 'other@example.com')},
                   {'read_ids': [BOOK, BOOK]}, {'read_ids': [HOME]}, {'read_ids': [HOME + '../personal/']},
                   {'read_ids': ['https://mail.example.com' + BOOK]}, {'read_ids': []},
                   {'read_ids': [HOME + 'shared/nested/']}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ContactError):
                ContactAccounts({'enabled': True, 'accounts': [{**original, **change}]}, calendars())
        with self.assertRaises(ContactError):
            ContactAccounts({'enabled': True, 'accounts': [original, original]}, calendars())

    def test_cross_account_and_unlisted_queries_fail_before_network_or_credential_access(self):
        accounts = configured(two=True)
        with patch.object(SogoContacts, 'request', side_effect=AssertionError('Must not make request')):
            for ids in (['other:' + BOOK], [BOOK_ID, 'other:' + BOOK], [ACCOUNT + ':' + HIDDEN], [BOOK], [], [BOOK_ID, BOOK_ID]):
                with self.subTest(ids=ids), self.assertRaises(ContactError):
                    accounts.search(ACCOUNT, ids, 'Nick')

    def test_invalid_name_mode_limit_or_unknown_account_rejected_without_io(self):
        accounts = configured()
        with patch.object(SogoContacts, 'request', side_effect=AssertionError('Must not make request')):
            for changes in ({'name': ''}, {'name': ' '}, {'name': '\nNick'}, {'name': 'n' * 101},
                            {'match': 'regex'}, {'limit': 0}, {'limit': 51}, {'limit': True}, {'account_id': 'other'}):
                values = dict(account_id=ACCOUNT, address_book_ids=[BOOK_ID], name='Nick')
                with self.subTest(changes=changes), self.assertRaises(ContactError):
                    accounts.search(**{**values, **changes})

    def test_ambiguous_contacts_addresses_missing_or_invalid_addresses_and_groups_need_clarification(self):
        accounts = configured()
        values = [[card(), card()], [card(emails=('nick@example.net', 'nick@work.example'))],
                  [card(emails=())], [card(emails=('nick@example.net', 'invalid'))], [card(extra='KIND:group\r\n')]]
        for cards in values:
            with self.subTest(cards=cards), patch.object(SogoContacts, 'request', side_effect=[principal(), discovery(), contact_rows(cards)]):
                result = accounts.search(ACCOUNT, [BOOK_ID], 'Nick')
                self.assertTrue(result['requires_clarification'])
                self.assertTrue(result['requires_recipient_confirmation'])
                self.assertFalse(result['invitation_authorized'])

    def test_single_candidate_still_needs_owner_confirmation_and_returns_no_raw_card(self):
        accounts = configured()
        with patch.object(SogoContacts, 'request', side_effect=[principal(), discovery(), contact_rows([card(extra='NOTE:private note\r\nTEL:1234\r\n')])]):
            result = accounts.search(ACCOUNT, [BOOK_ID], 'Nick')
        self.assertFalse(result['requires_clarification'])
        self.assertTrue(result['requires_recipient_confirmation'])
        self.assertNotIn('private note', json.dumps(result))
        self.assertNotIn('BEGIN:VCARD', json.dumps(result))
        self.assertEqual(result['contacts'][0]['emails'], ['nick@example.net'])
        self.assertEqual(result['contacts'][0]['address_book_id'], BOOK_ID)

    def test_truncation_never_claims_a_unique_resolution(self):
        accounts = configured()
        with patch.object(SogoContacts, 'request', side_effect=[principal(), discovery(), contact_rows([card()] * 2)]):
            result = accounts.search(ACCOUNT, [BOOK_ID], 'Nick', limit=1)
        self.assertEqual(len(result['contacts']), 1)
        self.assertEqual(result['matches'], 2)
        self.assertFalse(result['complete'])
        self.assertTrue(result['truncated'])
        self.assertTrue(result['requires_clarification'])

    def test_large_book_ambiguity_includes_matches_after_100(self):
        accounts = configured()
        raw = contact_rows([card()] + [sogo_card('Other', 'Person', 'other@example.net')] * 498
                           + [card(emails=('nick@work.example', 'nick@second.example'))])
        with patch.object(SogoContacts, 'request', side_effect=[principal(), discovery(), raw]):
            result = accounts.search(ACCOUNT, [BOOK_ID], 'Nick')
        self.assertEqual(result['matches'], 2)
        self.assertTrue(result['complete'])
        self.assertTrue(result['requires_clarification'])
        self.assertEqual(result['contacts'][1]['emails'], ['nick@work.example', 'nick@second.example'])

    def test_large_complete_book_can_report_no_match(self):
        accounts = configured()
        raw = contact_rows([sogo_card('Other', 'Person', 'other@example.net')] * 500)
        with patch.object(SogoContacts, 'request', side_effect=[principal(), discovery(), raw]):
            result = accounts.search(ACCOUNT, [BOOK_ID], 'Nobody')
        self.assertEqual(result['matches'], 0)
        self.assertTrue(result['complete'])
        self.assertFalse(result['truncated'])

    def test_larger_scan_does_not_increase_aggregate_match_or_display_limits(self):
        accounts = configured()
        for count in (100, 101):
            raw = contact_rows([sogo_card('Other', 'Person', 'other@example.net')] * 400 + [card()] * count)
            with self.subTest(count=count), patch.object(SogoContacts, 'request', side_effect=[principal(), discovery(), raw]):
                if count > MAX_CONTACTS:
                    with self.assertRaisesRegex(ContactError, 'Contact query exceeds safety limit'):
                        accounts.search(ACCOUNT, [BOOK_ID], 'Nick', limit=50)
                else:
                    result = accounts.search(ACCOUNT, [BOOK_ID], 'Nick', limit=50)
                    self.assertEqual(result['matches'], 100)
                    self.assertEqual(len(result['contacts']), 50)
                    self.assertFalse(result['complete'])
                    self.assertTrue(result['truncated'])
                    self.assertTrue(result['requires_clarification'])

    def test_empty_book_returns_no_match_not_a_guessed_recipient(self):
        accounts = configured()
        with patch.object(SogoContacts, 'request', side_effect=[principal(), discovery(), contact_rows([])]):
            result = accounts.search(ACCOUNT, [BOOK_ID], 'Nick')
        self.assertEqual(result['contacts'], [])
        self.assertEqual(result['matches'], 0)
        self.assertFalse(result['invitation_authorized'])

    def test_inaccessible_book_fails_closed(self):
        accounts = configured()
        with patch.object(SogoContacts, 'request', side_effect=[principal(), multistatus([(HOME, {})])]) as request, \
                self.assertRaisesRegex(ContactError, 'inaccessible'):
            accounts.search(ACCOUNT, [BOOK_ID], 'Nick')
        self.assertEqual(request.call_count, 2)

    def test_registration_adds_only_two_read_tools_without_io_and_keeps_existing_schemas(self):
        app = FastMCP('Synthetic owner connection')
        @app.tool()
        def existing_tool(event: dict) -> dict:
            return event
        before = {tool.name: tool.model_dump() for tool in asyncio.run(app.list_tools())}
        with patch('carddav_contacts.read_secret', side_effect=AssertionError('No credential read')), \
                patch('carddav_contacts.HTTPSConnection', side_effect=AssertionError('No network')):
            register(app, accounts=configured())
        after = {tool.name: tool.model_dump() for tool in asyncio.run(app.list_tools())}
        self.assertEqual(set(after) - set(before), {'contacts_list_address_books', 'contacts_search'})
        self.assertEqual(after['existing_tool'], before['existing_tool'])
        for name in ('contacts_list_address_books', 'contacts_search'):
            self.assertTrue(after[name]['annotations']['readOnlyHint'])
            self.assertFalse(after[name]['annotations']['destructiveHint'])
        self.assertIn('account_id', after['contacts_search']['inputSchema']['required'])
        self.assertIn('address_book_ids', after['contacts_search']['inputSchema']['required'])

    def test_missing_or_disabled_config_adds_no_tools_and_symlinks_or_writable_files_fail(self):
        # Simulate administrator-owned fixture metadata without requiring root CI.
        # File types and modes remain real, so writable files/symlinks still fail.
        original_lstat = Path.lstat
        def administrator_owned(path, *args, **kwargs):
            info = list(original_lstat(path, *args, **kwargs))
            info[4] = 0
            return os.stat_result(info)
        self.enterContext(patch.object(Path, 'lstat', administrator_owned))
        with tempfile.TemporaryDirectory() as directory:
            app = FastMCP('Synthetic owner')
            path = Path(directory) / 'contacts.json'
            register_configured(app, calendars(), path)
            self.assertEqual(asyncio.run(app.list_tools()), [])
            path.write_text(json.dumps({'enabled': False, 'accounts': []}))
            path.chmod(0o644)
            register_configured(app, calendars(), path)
            self.assertEqual(asyncio.run(app.list_tools()), [])
            path.chmod(0o666)
            with self.assertRaisesRegex(ContactError, 'administrator-controlled'):
                register_configured(app, calendars(), path)
            path.unlink()
            path.symlink_to(Path(directory) / 'target')
            with self.assertRaisesRegex(ContactError, 'administrator-controlled'):
                register_configured(app, calendars(), path)
