"""Standalone operations on the private calendar-only owner connection."""
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
import secrets
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError, WithJsonSchema

from calendar_create import (
    DATE, TIMESTAMP, MAX_EVENT_BYTES, TTL, RADAR_MODE, CreateTransport, EventSpec, Store,
    creation_enabled, event_times, event_uid, fingerprint, matches_event, pack, radar_rate_limits,
    render, require, safe_tool, standalone_calendar, strong_etag, validate_event,
)
from sogo_calendar import CalendarError, NOTICE
from calendar_invitations import attendee_addresses, email_address, invitation_key, matches_creation, render_invitation


class OwnerEventSpec(EventSpec):
    end: str | None = Field(default=None, max_length=25)
    duration_minutes: int | None = Field(default=None, ge=1, le=31 * 24 * 60)
    duration_days: int | None = Field(default=None, ge=1, le=31)
    attendees: list[str] = Field(default_factory=list, max_length=10)


ToolEvent = Annotated[Any, WithJsonSchema(OwnerEventSpec.model_json_schema())]
EVENT_FIELDS = (
    ('SUMMARY', 'title', ''), ('DESCRIPTION', 'description', ''), ('LOCATION', 'location', ''),
    ('CLASS', 'classification', 'PUBLIC'), ('TRANSP', 'transparency', 'OPAQUE'),
)
TERMINAL = {'verified', 'conflict', 'rejected', 'integrity_failure'}


def normalized_event(value):
    try:
        spec = OwnerEventSpec.model_validate(value)
        require(sum(field is not None for field in (spec.end, spec.duration_minutes, spec.duration_days)) == 1,
                'Supply exactly one end, timed duration in minutes, or all-day duration in days.')
        end = spec.end
        if spec.duration_days is not None:
            require(spec.all_day and DATE.fullmatch(spec.start), 'Use days and a date for an all-day duration.')
            end = (date.fromisoformat(spec.start) + timedelta(days=spec.duration_days)).isoformat()
        if spec.duration_minutes is not None:
            require(not spec.all_day and TIMESTAMP.fullmatch(spec.start),
                    'Use minutes and an offset-bearing timestamp for a timed duration.')
            start = datetime.fromisoformat(spec.start.replace('Z', '+00:00'))
            end = (start.astimezone(timezone.utc) + timedelta(minutes=spec.duration_minutes)).astimezone(
                ZoneInfo(spec.timezone)).isoformat(timespec='seconds')
        addresses = attendee_addresses(spec.attendees)
        fields = spec.model_dump(exclude={'duration_minutes', 'duration_days', 'attendees'})
        result = validate_event(EventSpec.model_validate({**fields, 'end': end}))
        return {**result, 'attendees': addresses} if addresses else result
    except (ValidationError, ValueError, KeyError, OverflowError):
        raise CalendarError('Calendar event contains invalid or unsupported fields.') from None


def snapshot(raw, expected_uid, fallback_timezone):
    try:
        calendar, item = standalone_calendar(raw)
        require(str(item['UID']) == expected_uid, 'Calendar resource identity changed.')
        start, end = (item.decoded(field) for field in ('DTSTART', 'DTEND'))
        require((type(start) is date and type(end) is date) or (
            isinstance(start, datetime) and start.utcoffset() is not None
            and isinstance(end, datetime) and end.utcoffset() is not None), 'Unsupported stored event time.')
        details = {key: str(item.get(field, default)) for field, key, default in EVENT_FIELDS}
        zone = str(item['DTSTART'].params.get('TZID') or fallback_timezone)
        zoneinfo = ZoneInfo(zone)
        if isinstance(start, datetime):
            start, end = start.astimezone(zoneinfo), end.astimezone(zoneinfo)
        details.update(start=start.isoformat(), end=end.isoformat(), all_day=type(start) is date,
                       timezone=zone)
        return calendar, item, details
    except CalendarError:
        raise
    except Exception:
        raise CalendarError('Stored event could not be interpreted safely.') from None


def update_payload(calendar, item, spec, now):
    start, end = event_times(spec)
    sequence = int(item.get('SEQUENCE', 0))
    require(0 <= sequence < 2147483647, 'Stored event sequence is unsupported.')
    for field, value in [('DTSTART', start), ('DTEND', end),
                         ('DTSTAMP', datetime.fromtimestamp(now, timezone.utc)),
                         ('LAST-MODIFIED', datetime.fromtimestamp(now, timezone.utc)),
                         ('SEQUENCE', sequence + 1),
                         *((field, spec[key]) for field, key, _ in EVENT_FIELDS)]:
        item.pop(field, None)
        if value != '':
            item.add(field, value)
    return calendar.to_ical()


class OwnerStore(Store):
    lock_name = 'calendar-owner.lock'
    database_name = 'calendar-owner.sqlite3'

    def valid_payload(self, manifest, raw):
        return not raw if manifest['operation'] == 'cancel' else matches_creation(raw, manifest)

    def invitation_operation(self, key):
        with self.db() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='owner_invitations'").fetchone()
            row = db.execute('SELECT operation_id FROM owner_invitations WHERE fingerprint=?', (key,)).fetchone() if exists else None
        return row['operation_id'] if row else None

    def reserve_resource(self, db, manifest):
        if manifest['operation'] == 'create':
            db.execute('''CREATE TABLE IF NOT EXISTS owner_resources (
                event_id TEXT NOT NULL, route TEXT NOT NULL, uid TEXT UNIQUE NOT NULL,
                operation_id TEXT UNIQUE NOT NULL, PRIMARY KEY (route, event_id)
            )''')
            db.execute('INSERT INTO owner_resources VALUES (?, ?, ?, ?)',
                       (manifest['event_id'], manifest['route'], manifest['uid'], manifest['operation_id']))
            if manifest.get('invitation'):
                db.execute('''CREATE TABLE IF NOT EXISTS owner_invitations (
                    fingerprint TEXT PRIMARY KEY, operation_id TEXT UNIQUE NOT NULL
                )''')
                db.execute('INSERT INTO owner_invitations VALUES (?, ?)',
                           (manifest['invitation_key'], manifest['operation_id']))

    def managed(self, route, event_id):
        with self.db() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='owner_resources'").fetchone()
            row = db.execute('SELECT operation_id FROM owner_resources WHERE route=? AND event_id=?',
                             (route, event_id)).fetchone() if exists else None
        item = self.get(row['operation_id']) if row else None
        require(item and item['state'] == 'verified', 'Only a verified event created by this worker can be changed.')
        return item['manifest']

    def assert_target_resolved(self, route, event_id, except_id=None):
        """A new request ID must not bypass recovery of an attempted mutation."""
        with self.db() as db:
            keys = [row['id'] for row in db.execute(
                "SELECT id FROM creations WHERE attempts>0 AND state IN ('attempting', 'uncertain')")]
        for key in keys:
            if key == except_id:
                continue
            manifest = self.get(key)['manifest']
            require((manifest['route'], manifest['event_id']) != (route, event_id),
                    'This event has an unresolved write. Reconcile its original operation; do not submit another.')

    def event_timezone(self, route, event_id, created):
        # Read the newest verified edit, without changing or migrating Phase 1 rows.
        with self.db() as db:
            keys = [row['id'] for row in db.execute(
                "SELECT id FROM creations WHERE state='verified' ORDER BY rowid")]
        latest = created
        for key in keys:
            manifest = self.get(key)['manifest']
            if (manifest['operation'] == 'update' and manifest['route'] == route
                    and manifest['event_id'] == event_id
                    and manifest['created_at'] >= latest['created_at']):
                latest = manifest
        return latest['event']['timezone']

    def assert_route_open(self, route):
        with self.db() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='owner_blocked_routes'").fetchone()
            blocked = exists and db.execute('SELECT 1 FROM owner_blocked_routes WHERE route=?', (route,)).fetchone()
        require(not blocked, 'Calendar writes on this account are blocked after an integrity failure.')

    def record(self, manifest, state, outcome, observation='', version=None, *, attempted=True):
        key = manifest['operation_id']
        with self.db() as db:
            db.execute('UPDATE creations SET state=?, outcome=? WHERE id=?', (state, outcome, key))
            if attempted:
                db.execute('''UPDATE radar_create_audit SET state=?, outcome=?
                              WHERE operation_id=? AND attempt=(SELECT attempts FROM creations WHERE id=?)''',
                           (state, outcome, key, key))
            if state == 'integrity_failure':
                db.execute('CREATE TABLE IF NOT EXISTS owner_blocked_routes (route TEXT PRIMARY KEY)')
                db.execute('INSERT OR IGNORE INTO owner_blocked_routes VALUES (?)', (manifest['route'],))
            if observation:
                db.execute('''CREATE TABLE IF NOT EXISTS owner_observations (
                    id TEXT PRIMARY KEY, observed_at INTEGER, observation TEXT, version TEXT
                )''')
                db.execute('INSERT OR REPLACE INTO owner_observations VALUES (?, ?, ?, ?)',
                           (key, int(datetime.now(timezone.utc).timestamp()), observation, version))

    def observation(self, key):
        with self.db() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='owner_observations'").fetchone()
            row = db.execute('SELECT * FROM owner_observations WHERE id=?', (key,)).fetchone() if exists else None
        return dict(row) if row else {}


class OwnerOperations:
    def __init__(self, accounts, store, enabled, limits, invitations=None):
        self.accounts = accounts
        self.store = store
        self.enabled = enabled
        self.limits = limits
        self.invitations = invitations

    def authorize_invitation(self, canonical, attendees):
        require(self.invitations is not None, 'Invitations are disabled on this calendar.')
        account, _ = self.accounts.targets[canonical]
        organizer = email_address(account.reader.username)
        self.invitations.authorize(canonical, attendees, organizer)
        return {'organizer': organizer}

    def destination(self, calendar_id, operation):
        key = self.accounts.resolve(calendar_id)
        account, path = self.accounts.targets[key]
        require(path in account.permissions[operation], 'Calendar is not allowlisted for this operation.')
        reader = account.reader
        transport = CreateTransport(reader.base_url, reader.username, account.write_secret)
        route = fingerprint(pack([reader.host, reader.port, reader.username.casefold(), reader.home]))
        return key, path, transport, route

    def prepare(self, operation, request_id, calendar_id, *, event=None, event_id=None):
        require(operation in self.enabled, 'Calendar operation is disabled.')
        require(re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id), 'Use a stable request ID of 16 to 80 characters.')
        key = fingerprint(pack([RADAR_MODE, request_id]))
        canonical, path, transport, route = self.destination(calendar_id, operation)
        spec = normalized_event(event) if operation != 'cancel' else None
        invitation = None
        if spec and spec.get('attendees'):
            require(operation == 'create', 'Attendees are supported only on newly created events.')
            invitation = self.authorize_invitation(canonical, spec['attendees'])
        with self.store.locked():
            previous = self.store.get(key)
            if previous:
                manifest = previous['manifest']
                require((manifest['operation'], manifest['calendar_id'], manifest['route'], manifest.get('event'))
                        == (operation, canonical, route, spec)
                        and (operation == 'create' or event_id == manifest['event_id']),
                        'Request ID is already bound to a different calendar operation.')
                return {'status': previous['state'], 'proposal': manifest, 'human_approval_verified': False,
                        'notice': NOTICE}
            if invitation:
                proposal = {'route': route, 'calendar_id': canonical, 'event': spec, 'invitation': invitation}
                duplicate = self.store.invitation_operation(invitation_key(proposal))
                require(not duplicate, 'These invitation details already have an operation. Reuse or reconcile '
                        + str(duplicate) + '; do not resend.')
            self.store.assert_route_open(route)
            transport.calendar_path(path)
            now = int(datetime.now(timezone.utc).timestamp())
            manifest = {'operation_id': key, 'operation': operation, 'calendar_id': canonical,
                        'route': route, 'created_at': now, 'expires_at': now + TTL, 'event': spec}
            if operation == 'create':
                resource_id = secrets.token_hex(32)
                manifest.update(event_id=path + resource_id + '.ics', uid=event_uid(resource_id))
                if invitation:
                    manifest['invitation'] = invitation
                    manifest['invitation_key'] = invitation_key(manifest)
                raw = render_invitation(manifest) if invitation else render(manifest)
            else:
                created = self.store.managed(route, event_id)
                uid = created['uid']
                self.store.assert_target_resolved(route, event_id)
                status, before, etag = transport.exchange_resource('GET', path, event_id)
                require(status == 200 and strong_etag(etag), 'Current event or strong version is unavailable.')
                calendar, item, details = snapshot(
                    before, uid, self.store.event_timezone(route, event_id, created))
                manifest.update(event_id=event_id, uid=uid, before=details, expected_etag=etag,
                                expected_digest=fingerprint(before))
                raw = b''
                if operation == 'update':
                    require(not matches_event(before, manifest), 'The proposed event already matches the stored event.')
                    raw = update_payload(calendar, item, spec, now)
            require(len(raw) <= MAX_EVENT_BYTES and self.store.valid_payload(manifest, raw),
                    'Calendar operation contains unsupported event data.')
            manifest['payload_sha256'] = fingerprint(raw)
            self.store.insert(manifest, raw)
            return {'status': 'pending', 'proposal': manifest, 'human_approval_verified': False, 'notice': NOTICE}

    def item(self, key, operation=None):
        item = self.store.get(key)
        require(item is not None, 'Calendar operation was not found.')
        manifest = item['manifest']
        action = manifest['operation']
        require(operation is None or action == operation, 'Operation ID belongs to a different action.')
        _, path, transport, route = self.destination(manifest['calendar_id'], action)
        require(route == manifest['route'], 'Calendar operation account configuration changed.')
        return item, path, transport

    def receipt(self, item):
        manifest = item['manifest']
        result = {key: manifest[key] for key in ('operation', 'operation_id', 'calendar_id', 'event_id', 'uid')}
        result['event_uid'] = result.pop('uid')
        observed = self.store.observation(manifest['operation_id'])
        state = 'uncertain' if item['state'] == 'attempting' else item['state']
        result.update(status=state, outcome=item['outcome'], attempts=item['attempts'], retry_allowed=False,
                      human_approval_verified=False, authorization_mode=RADAR_MODE)
        if manifest['event']:
            result['timezone'] = manifest['event']['timezone']
        if observed:
            result.update(observation=observed['observation'], observed_at=observed['observed_at'],
                          version=observed['version'])
        if manifest.get('invitation'):
            result['event_creation'] = state
            result['invitations'] = {
                'recipient_count': len(manifest['event']['attendees']),
                'dispatch': 'unknown' if item['attempts'] else 'not_attempted',
                'email_delivery': 'unverified', 'resend_allowed': False,
            }
        return result

    @staticmethod
    def observe(manifest, path, transport):
        try:
            transport.calendar_path(path)
            status, raw, etag = transport.exchange_resource('GET', path, manifest['event_id'])
            if status == 404:
                return 'missing', None
            if status == 200:
                if manifest['operation'] == 'cancel':
                    return ('present' if fingerprint(raw) == manifest['expected_digest'] else 'changed'), etag
                if matches_creation(raw, manifest):
                    return 'matches', etag
                if (manifest['operation'] == 'update'
                        and fingerprint(raw) == manifest['expected_digest']):
                    return 'unchanged', etag
                return 'changed', etag
        except CalendarError:
            pass
        return 'unreadable', None

    def reconcile(self, item, path, transport):
        manifest = item['manifest']
        state, outcome = item['state'], item['outcome']
        observed, etag = self.observe(manifest, path, transport)
        if state in TERMINAL and self.store.observation(manifest['operation_id']):
            return {**self.receipt(item), 'current_observation': observed,
                    'current_observed_at': int(datetime.now(timezone.utc).timestamp()),
                    'current_version': etag if strong_etag(etag) else None}
        if state not in TERMINAL:
            if outcome == 'precondition':
                state = 'conflict'
            elif outcome == 'rejected':
                state = 'rejected'
            elif ((observed == 'matches' and manifest['operation'] != 'cancel')
                  or (observed == 'missing' and manifest['operation'] == 'cancel' and outcome == 'accepted')):
                state = 'verified'
            else:
                state = 'uncertain'
        self.store.record(manifest, state, outcome, observed, etag if strong_etag(etag) else None)
        return self.receipt(self.store.get(manifest['operation_id']))

    def commit(self, key, operation, *, write=True):
        with self.store.locked():
            item, path, transport = self.item(key, operation)
            manifest = item['manifest']
            if item['state'] in TERMINAL or item['attempts']:
                return self.reconcile(item, path, transport) if not write and item['attempts'] else self.receipt(item)
            if not write:
                return self.receipt(item)
            require(operation in self.enabled, 'Calendar operation is disabled.')
            if manifest.get('invitation'):
                current_invitation = self.authorize_invitation(manifest['calendar_id'], manifest['event']['attendees'])
                require(current_invitation == manifest['invitation'], 'Invitation organizer configuration changed.')
            self.store.assert_route_open(manifest['route'])
            if operation != 'create':
                self.store.assert_target_resolved(manifest['route'], manifest['event_id'], key)
            require(datetime.now(timezone.utc).timestamp() < manifest['expires_at'], 'Calendar proposal expired.')
            transport.calendar_path(path)
            status, before, etag = transport.exchange_resource('GET', path, manifest['event_id'])
            if operation == 'create':
                require(status in (200, 404), 'Could not verify that the calendar resource is absent.')
                current = status == 404
            else:
                require(status in (200, 404), 'Could not read the current calendar resource.')
                current = (status == 200 and etag == manifest['expected_etag']
                           and fingerprint(before) == manifest['expected_digest'])
            if not current:
                self.store.record(manifest, 'conflict', 'preflight_conflict', attempted=False)
                return self.receipt(self.store.get(key))
            require(datetime.now(timezone.utc).timestamp() < manifest['expires_at'], 'Calendar proposal expired.')
            self.store.claim_radar_attempt(key, self.limits)
            status = None
            try:
                status, _, _ = transport.exchange_resource(
                    'DELETE' if operation == 'cancel' else 'PUT', path, manifest['event_id'],
                    item['raw'] if operation != 'cancel' else None, etag=manifest.get('expected_etag'),
                    **({'scheduling': True} if manifest.get('invitation') else {}))
            except CalendarError:
                pass
            if (operation == 'create' and status in (200, 204)) or (operation != 'create' and status == 201):
                self.store.record(manifest, 'integrity_failure', 'unexpected_write_status')
            else:
                accepted = (201,) if operation == 'create' else (200, 204)
                if status in accepted:
                    outcome = 'accepted'
                elif status in (409, 412):
                    outcome = 'precondition'
                elif status in (400, 401, 403, 404, 405, 415, 422):
                    outcome = 'rejected'
                else:
                    outcome = 'unknown'
                self.store.record(manifest, 'attempting', outcome)
            return self.reconcile(self.store.get(key), path, transport)


def register_owner_operations(server, accounts, *, invitations=None):
    from mcp.types import ToolAnnotations

    enabled = {action for action, active in {
        'create': creation_enabled(True),
        'update': os.environ.get('INBOXTETHER_CALDAV_RADAR_UPDATE_ENABLED') == '1',
        'cancel': os.environ.get('INBOXTETHER_CALDAV_RADAR_CANCEL_ENABLED') == '1',
    }.items() if active and any(account.permissions[action] for account in accounts.accounts.values())}
    for action in ('update', 'cancel'):
        require(action not in enabled or os.environ.get(
            'INBOXTETHER_CALDAV_RADAR_' + action.upper() + '_CONDITIONAL_VERIFIED') == '1',
            'Conditional ' + action + ' has not been validated on this calendar route. Keep it disabled.')
    directory = Path(os.environ.get('INBOXTETHER_CALDAV_RADAR_STATE_DIR', ''))
    if not enabled and not directory.is_absolute():
        return
    require(directory.is_absolute(), 'Configure an absolute private owner calendar state directory.')
    service = OwnerOperations(accounts, OwnerStore(directory), enabled, radar_rate_limits(), invitations)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
    prepare = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)

    if 'create' in enabled:
        @server.tool(annotations=prepare)
        @safe_tool
        def calendar_prepare_create(request_id: str, calendar_id: str, event: ToolEvent) -> dict:
            """Gather missing details and prepare one standalone event without a CalDAV write.

            Show calendar, exact dates/times/timezone, relevant details and every explicit attendee
            email address; obtain conversational confirmation before commit. Attendees require the
            opt-in controlled-recipient policy. The organizer is pinned to the calendar account.
            """
            return service.prepare('create', request_id, calendar_id, event=event)

        @server.tool(annotations=write)
        @safe_tool
        def calendar_commit_create(operation_id: str) -> dict:
            """Commit the reviewed creation once; opted-in attendees may receive SOGo invitations.

            Event verification does not prove invitation dispatch or email delivery. Never resend
            or use a fresh request ID after uncertainty; reconcile the original operation by GET.
            """
            return service.commit(operation_id, 'create')

    if 'update' in enabled:
        @server.tool(annotations=prepare)
        @safe_tool
        def calendar_prepare_update(request_id: str, calendar_id: str, event_id: str, event: ToolEvent) -> dict:
            """Locate one exact worker-created standalone event first; resolve ambiguity with the owner.

            Supply ALL replacement fields, retaining unchanged details. Show current and proposed
            details, including timezone, and obtain conversational confirmation before commit.
            No CalDAV write occurs here. Attendees and recurrence are unsupported.
            """
            return service.prepare('update', request_id, calendar_id, event_id=event_id, event=event)

        @server.tool(annotations=write)
        @safe_tool
        def calendar_commit_update(operation_id: str) -> dict:
            """Commit the reviewed update only against the prepared event version."""
            return service.commit(operation_id, 'update')

    if 'cancel' in enabled:
        @server.tool(annotations=prepare)
        @safe_tool
        def calendar_prepare_cancel(request_id: str, calendar_id: str, event_id: str) -> dict:
            """Resolve one exact worker-created standalone event before preparing its removal.

            Show all current details and explain removal; obtain conversational confirmation.
            No CalDAV write occurs here. Do not infer a target from an ambiguous title.
            Attendees and recurrence are unsupported; this sends no invitation notices.
            """
            return service.prepare('cancel', request_id, calendar_id, event_id=event_id)

        @server.tool(annotations=write)
        @safe_tool
        def calendar_commit_cancel(operation_id: str) -> dict:
            """Cancel only the reviewed standalone event at its prepared version."""
            return service.commit(operation_id, 'cancel')

    @server.tool(annotations=prepare)
    @safe_tool
    def calendar_reconcile_operation(operation_id: str) -> dict:
        """Read the exact resource to reconcile an attempted operation. May update the local receipt only."""
        return service.commit(operation_id, None, write=False)
