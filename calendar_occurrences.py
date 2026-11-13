"""Bounded occurrence search and availability for fully visible CalDAV calendars."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sogo_calendar import CalendarError, utc_range


UTC = timezone.utc
MAX_OCCURRENCES = 1000
MAX_MATCHES = 200


def window(start, end, zone):
    bounds = utc_range(start, end)
    try:
        local_zone = ZoneInfo(zone)
        first, last = (datetime.strptime(bounds[k], '%Y%m%dT%H%M%SZ').replace(tzinfo=UTC)
                       for k in ('start', 'end'))
        # Pad for date-only and floating values, then filter by exact UTC overlap.
        return first, last, local_zone, first - timedelta(days=1), last + timedelta(days=1)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        raise CalendarError('Use a valid IANA timezone and a supported date range.') from None


def instant(value, zone):
    if type(value) is date:
        value = datetime.combine(value, time.min, tzinfo=zone)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    return value.astimezone(UTC)


def property_value(event, field):
    return str(event.get(field, '')).upper()


def validate_series(events, zone):
    masters = [event for event in events if 'RECURRENCE-ID' not in event]
    if len(masters) != 1:
        raise CalendarError('Calendar contains a missing or duplicate event master.')
    seen = set()
    dates = 0
    for event in events:
        if event.errors:
            raise CalendarError('Calendar contains malformed event data.')
        for field in ('DTSTART', 'DTEND', 'RECURRENCE-ID'):
            if field in event:
                prop = event[field]
                if prop.params.get('TZID') and isinstance(prop.dt, datetime) and prop.dt.tzinfo is None:
                    raise CalendarError('Calendar contains an unresolved event timezone.')
        if 'RECURRENCE-ID' in event:
            prop = event['RECURRENCE-ID']
            key = instant(prop.dt, zone)
            if key in seen or prop.params.get('RANGE'):
                raise CalendarError('Calendar contains an ambiguous recurrence exception.')
            seen.add(key)
        if property_value(event, 'STATUS') != 'CANCELLED':
            start, end = event.start, event.end
            if type(start) is not type(end) or instant(end, zone) < instant(start, zone):
                raise CalendarError('Calendar contains an invalid event interval.')
        for field in ('EXDATE', 'RDATE'):
            groups = event.get(field, [])
            if not isinstance(groups, list):
                groups = [groups]
            for group in groups:
                dates += len(group.dts)
                if dates > MAX_OCCURRENCES:
                    raise CalendarError('Calendar contains too many explicit recurrence dates.')
                for item in group.dts:
                    if (isinstance(item.dt, tuple) or (group.params.get('TZID')
                            and isinstance(item.dt, datetime) and item.dt.tzinfo is None)):
                        raise CalendarError('Calendar contains an unsupported explicit recurrence date.')
        rule = event.get('RRULE')
        if rule is not None:
            if (rule.get('FREQ', [''])[0] not in {'HOURLY', 'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'}
                    or len(rule.get('BYMINUTE', [])) > 1 or len(rule.get('BYSECOND', [])) > 1
                    or event.end - event.start > timedelta(days=31)):
                raise CalendarError('Calendar contains a recurrence above the supported complexity limit.')
        if 'EXRULE' in event:
            raise CalendarError('Calendar contains an unsupported exclusion rule.')
    return masters[0]


def occurrences(resources, bounds):
    try:
        from icalendar import Calendar
        import recurring_ical_events
    except ImportError:
        raise CalendarError('Install the optional calendar dependencies to use search and free/busy.') from None

    first, last, zone, expanded_first, expanded_last = bounds
    seen = set()
    count = 0
    try:
        for resource in resources:
            calendar = Calendar.from_ical(resource['icalendar'])
            if calendar.errors:
                raise CalendarError('Calendar contains malformed data.')
            resource_zone = ZoneInfo(str(calendar['X-WR-TIMEZONE'])) if 'X-WR-TIMEZONE' in calendar else zone
            events = calendar.walk('VEVENT')
            if not events and calendar.walk('VTODO') and not calendar.walk('VFREEBUSY'):
                continue
            if not events or len(events) > MAX_OCCURRENCES or calendar.walk('VFREEBUSY'):
                raise CalendarError('Calendar contains an unsupported calendar resource.')
            uids = {str(event['UID']) for event in events}
            if len(uids) != 1 or not next(iter(uids)) or seen.intersection(uids):
                raise CalendarError('Calendar contains missing or duplicate event identifiers.')
            seen.update(uids)
            master = validate_series(events, resource_zone)
            if property_value(master, 'STATUS') == 'CANCELLED':
                continue
            # Some cancellation exceptions omit DTSTART. Exclude the original slot
            # directly rather than depending on the expansion library to read it.
            for event in events:
                if property_value(event, 'STATUS') == 'CANCELLED' and 'RECURRENCE-ID' in event:
                    master.add('EXDATE', event.decoded('RECURRENCE-ID'))
                    calendar.subcomponents.remove(event)
            for event in recurring_ical_events.of(calendar, skip_bad_series=False).between(
                expanded_first, expanded_last,
            ):
                count += 1
                if count > MAX_OCCURRENCES:
                    raise CalendarError('Calendar exceeds the occurrence limit. Use a shorter window.')
                start_value = event.decoded('DTSTART')
                start = instant(start_value, resource_zone)
                end = instant(event.decoded('DTEND'), resource_zone)
                if end < start:
                    raise CalendarError('Calendar contains an event with a reversed interval.')
                if (start < last and end > first) or (start == end and first <= start < last):
                    yield resource['event_id'], event, start, end, type(start_value) is date
    except CalendarError:
        raise
    except Exception:
        raise CalendarError('Calendar contains an event that could not be interpreted safely.') from None


def selected_paths(client, calendar_ids):
    inventory = client.calendar_selection(calendar_ids)
    if any(key not in inventory for key in calendar_ids):
        raise CalendarError('A selected calendar is absent or inaccessible.')
    return calendar_ids


def search(client, calendar_ids, start, end, text, zone):
    term = text.strip().casefold()
    if not 1 <= len(term) <= 200:
        raise CalendarError('Search text must contain 1 to 200 characters.')
    bounds = window(start, end, zone)
    matches = []
    for key in selected_paths(client, calendar_ids):
        for event_id, event, first, last, all_day in occurrences(client.complete_resources(key), bounds):
            if not any(term in str(event.get(field, '')).casefold()
                       for field in ('SUMMARY', 'DESCRIPTION', 'LOCATION')):
                continue
            if len(matches) >= MAX_MATCHES:
                raise CalendarError('Search exceeds the result limit. Narrow the text or time window.')
            recurrence_id = event.get('RECURRENCE-ID')
            matches.append({'calendar_id': key, 'event_id': event_id,
                            'recurrence_id': recurrence_id.dt.isoformat() if recurrence_id else None,
                            'summary': str(event.get('SUMMARY', ''))[:500],
                            'start': first.isoformat(), 'end': last.isoformat(), 'all_day': all_day})
    return {'events': sorted(matches, key=lambda row: (row['start'], row['calendar_id'], row['event_id']))}


def is_busy(event, include_tentative):
    return (property_value(event, 'TRANSP') != 'TRANSPARENT'
            and (include_tentative or property_value(event, 'STATUS') != 'TENTATIVE'))


def encode_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return [{'start': start.isoformat(), 'end': end.isoformat()} for start, end in merged]


def free_busy(client, calendar_ids, start, end, zone, include_tentative):
    bounds = window(start, end, zone)
    first, last = bounds[:2]
    calendars = []
    combined = []
    for key in selected_paths(client, calendar_ids):
        intervals = [
            (max(first, begin), min(last, stop))
            for _, event, begin, stop, _ in occurrences(client.complete_resources(key), bounds)
            if begin < stop and is_busy(event, include_tentative)
        ]
        combined.extend(intervals)
        if len(combined) > MAX_OCCURRENCES:
            raise CalendarError('Availability exceeds the interval limit. Use a shorter window.')
        calendars.append({'calendar_id': key, 'busy': encode_intervals(intervals)})
    return {'available': not combined, 'start': first.isoformat(), 'end': last.isoformat(),
            'busy': encode_intervals(combined), 'calendars': calendars}
