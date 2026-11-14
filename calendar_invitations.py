"""Opt-in server scheduling for new standalone events; no mail sender or resend path."""
from dataclasses import dataclass
import re

from calendar_create import fingerprint, matches_event, pack, render, require


def email_address(value):
    # Deliberately accept plain ASCII mailbox addresses, not names, URIs or groups.
    require(isinstance(value, str) and len(value) <= 254 and value.count('@') == 1,
            'Use an explicit plain email address for each attendee.')
    local, domain = value.rsplit('@', 1)
    # Keep mailto construction unambiguous on SOGo: no URI delimiters or percent escapes.
    atom = r'[A-Za-z0-9_+-]+'
    label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    require(len(local) <= 64 and re.fullmatch(atom + r'(?:\.' + atom + r')*', local)
            and re.fullmatch(label + r'(?:\.' + label + r')+', domain),
            'Use an explicit plain email address for each attendee.')
    return local + '@' + domain.lower()


def attendee_addresses(values):
    require(isinstance(values, list) and len(values) <= 10, 'Use at most ten explicit attendee addresses.')
    result = [email_address(value) for value in values]
    require(len({value.casefold() for value in result}) == len(result), 'Attendee addresses must be distinct.')
    return sorted(result, key=str.casefold)


@dataclass(frozen=True)
class InvitationPolicy:
    enabled: bool
    calendars: frozenset[str]
    recipients: frozenset[str]
    max_attendees: int

    def authorize(self, calendar_id, attendees, organizer):
        require(self.enabled and calendar_id in self.calendars, 'Invitations are disabled on this calendar.')
        require(0 < len(attendees) <= self.max_attendees, 'Invitation recipient limit exceeded.')
        require(all(value.casefold() in self.recipients for value in attendees),
                'Invitation recipient is outside the controlled-recipient allowlist.')
        require(organizer.casefold() not in {value.casefold() for value in attendees},
                'Do not add the organizer as an attendee.')


def policy_from_config(value, creation):
    fields = {'enabled', 'account_id', 'calendar_ids', 'allowed_recipients', 'max_attendees'}
    require(isinstance(value, dict) and set(value) == fields and type(value['enabled']) is bool,
            'Invalid invitation pilot policy.')
    paths = value['calendar_ids']
    require(value['account_id'] == creation['account_id'] and isinstance(paths, list) and bool(paths)
            and all(isinstance(path, str) for path in paths) and len(set(paths)) == len(paths)
            and set(paths) <= set(creation['create_ids']),
            'Invitations must stay within the creation account and calendar allowlist.')
    recipients = attendee_addresses(value['allowed_recipients'])
    require((not value['enabled'] or bool(recipients)) and type(value['max_attendees']) is int
            and 1 <= value['max_attendees'] <= 10, 'Configure explicit controlled recipients and a limit of 1 to 10.')
    return InvitationPolicy(value['enabled'], frozenset(value['account_id'] + ':' + path for path in paths),
                            frozenset(a.casefold() for a in recipients), value['max_attendees'])


def invitation_key(manifest):
    event = {**manifest['event'], 'attendees': [a.casefold() for a in manifest['event']['attendees']]}
    return fingerprint(pack([manifest['route'], manifest['calendar_id'],
                             manifest['invitation']['organizer'].casefold(), event]))


def render_invitation(manifest):
    from icalendar import Calendar, vCalAddress

    calendar = Calendar.from_ical(render(manifest))
    event = calendar.walk('VEVENT')[0]
    organizer = vCalAddress('mailto:' + manifest['invitation']['organizer'])
    organizer.params['SCHEDULE-AGENT'] = 'SERVER'
    event.add('organizer', organizer)
    event.add('sequence', 0)
    for address in manifest['event']['attendees']:
        attendee = vCalAddress('mailto:' + address)
        attendee.params.update({'CUTYPE': 'INDIVIDUAL', 'ROLE': 'REQ-PARTICIPANT',
                                'PARTSTAT': 'NEEDS-ACTION', 'RSVP': 'TRUE', 'SCHEDULE-AGENT': 'SERVER'})
        event.add('attendee', attendee)
    return calendar.to_ical()


def matches_invitation(raw, manifest):
    """Verify addresses and event data; storage is not evidence of dispatch or delivery."""
    from icalendar import Calendar

    try:
        require(manifest['operation'] == 'create' and manifest['invitation_key'] == invitation_key(manifest),
                'Invalid invitation proposal.')
        calendar = Calendar.from_ical(raw)
        events = calendar.walk('VEVENT')
        require(len(events) == 1 and not calendar.errors and not any(c.errors for c in calendar.walk()),
                'Expected one well-formed event.')
        event = events[0]
        organizer = event.pop('ORGANIZER')
        require(not isinstance(organizer, list) and str(organizer).lower().startswith('mailto:'),
                'Invalid organizer.')
        require(email_address(str(organizer)[7:]).casefold()
                == manifest['invitation']['organizer'].casefold(), 'Organizer differs.')
        require(not any(key in organizer.params for key in ('SENT-BY', 'DIR'))
                and str(organizer.params.get('SCHEDULE-AGENT', 'SERVER')).upper() == 'SERVER',
                'Unsupported organizer routing.')
        values = event.pop('ATTENDEE')
        values = values if isinstance(values, list) else [values]
        addresses = []
        for value in values:
            require(str(value).lower().startswith('mailto:'), 'Invalid attendee.')
            addresses.append(email_address(str(value)[7:]))
            require(not any(key in value.params for key in ('SENT-BY', 'MEMBER', 'DELEGATED-TO', 'DELEGATED-FROM', 'DIR'))
                    and str(value.params.get('ROLE', 'REQ-PARTICIPANT')).upper() == 'REQ-PARTICIPANT'
                    and str(value.params.get('CUTYPE', 'INDIVIDUAL')).upper() == 'INDIVIDUAL'
                    and str(value.params.get('SCHEDULE-AGENT', 'SERVER')).upper() == 'SERVER'
                    and str(value.params.get('PARTSTAT', 'NEEDS-ACTION')).upper()
                        in ('NEEDS-ACTION', 'ACCEPTED', 'DECLINED', 'TENTATIVE'),
                    'Unsupported attendee routing.')
        require(len(addresses) == len({a.casefold() for a in addresses})
                and {a.casefold() for a in addresses}
                    == {a.casefold() for a in manifest['event']['attendees']}, 'Attendees differ.')
        require(not any(str(key).upper().startswith('X-SOGO-SEND-APPOINTMENT-NOTIFICATIONS') for key in event),
                'Server scheduling was suppressed.')
        return matches_event(calendar.to_ical(), manifest)
    except Exception:
        return False


def matches_creation(raw, manifest):
    return matches_invitation(raw, manifest) if manifest.get('invitation') else matches_event(raw, manifest)
