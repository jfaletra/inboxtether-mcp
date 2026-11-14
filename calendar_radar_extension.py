"""Experimental change-policy hook; not qualified for the tested SOGo route."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat


CONFIG = Path('/etc/inboxtether-calendar-radar/accounts.json')
CREATION = Path('/etc/inboxtether-calendar-radar/creation.json')
CHANGES = Path('/etc/inboxtether-calendar-radar/changes.json')
INVITATIONS = Path('/etc/inboxtether-calendar-radar/invitations.json')
CONTACTS = Path('/etc/inboxtether-calendar-radar/contacts.json')
WRITE_FLAGS = (
    'INBOXTETHER_CALDAV_CREATE_ENABLED', 'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED',
    'INBOXTETHER_CALDAV_RADAR_UPDATE_ENABLED', 'INBOXTETHER_CALDAV_RADAR_CANCEL_ENABLED',
    'INBOXTETHER_CALDAV_RADAR_UPDATE_CONDITIONAL_VERIFIED',
    'INBOXTETHER_CALDAV_RADAR_CANCEL_CONDITIONAL_VERIFIED',
)


def trusted_json(path):
    for item in (path, *path.parents):
        info = item.lstat()
        expected = stat.S_ISREG if item == path else stat.S_ISDIR
        if info.st_uid != 0 or info.st_mode & 0o022 or not expected(info.st_mode):
            raise RuntimeError('Calendar configuration must be administrator-controlled.')
    return json.loads(path.read_text(encoding='utf-8'))


@contextmanager
def registration_environment(settings):
    """The reviewed registration captures its settings before the transport starts."""
    previous = {key: os.environ.get(key) for key in settings}
    try:
        os.environ.update(settings)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def register(app):
    from calendar_accounts import CalendarAccounts
    from calendar_owner_operations import register_owner_operations
    from calendar_invitations import policy_from_config
    from sogo_calendar import register as register_reads

    if any(os.environ.get(flag, '0') != '0' for flag in WRITE_FLAGS):
        raise RuntimeError('Configure the creation pilot in its administrator file, with global write flags off.')
    records = trusted_json(CONFIG)
    read_accounts = CalendarAccounts(json.dumps(records))
    if any(account.write_secret or any(account.permissions.values()) for account in read_accounts.accounts.values()):
        raise RuntimeError('The existing read-account configuration must retain empty write permissions.')
    policy = trusted_json(CREATION)
    required = {'enabled', 'account_id', 'create_ids', 'write_password_file', 'state_directory',
                'max_attempts_per_hour', 'max_attempts_per_day'}
    if (not isinstance(policy, dict) or set(policy) != required or type(policy['enabled']) is not bool
            or any(type(policy[key]) is not int or not 1 <= policy[key] <= 2
                   for key in ('max_attempts_per_hour', 'max_attempts_per_day'))):
        raise RuntimeError('Invalid creation pilot policy or limits above two attempts per window.')
    if policy['account_id'] not in read_accounts.accounts or not policy['create_ids'] or not policy['write_password_file']:
        raise RuntimeError('Configure one known creation account, explicit calendars and its credential file.')
    state = Path(policy['state_directory'])
    if not state.is_absolute():
        raise RuntimeError('Configure an absolute private calendar state directory.')
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
        raise RuntimeError('The calendar state directory must be service-owned with mode 700.')

    # A missing Phase 2 file preserves the accepted Phase 1 registration.
    changes = None
    try:
        CHANGES.lstat()
    except FileNotFoundError:
        pass
    else:
        changes = trusted_json(CHANGES)
        fields = {'account_id', 'calendar_ids', 'update_enabled', 'cancel_enabled',
                  'conditional_update_verified', 'conditional_cancel_verified'}
        switches = fields - {'account_id', 'calendar_ids'}
        if (not isinstance(changes, dict) or set(changes) != fields
                or any(type(changes[key]) is not bool for key in switches)
                or changes['account_id'] != policy['account_id']
                or not isinstance(changes['calendar_ids'], list) or not changes['calendar_ids']
                or any(not isinstance(key, str) for key in changes['calendar_ids'])
                or len(set(changes['calendar_ids'])) != len(changes['calendar_ids'])
                or not set(changes['calendar_ids']) <= set(policy['create_ids'])):
            raise RuntimeError('Changes must stay within the existing creation account and calendars.')
        for action in ('update', 'cancel'):
            if changes[action + '_enabled'] and not changes['conditional_' + action + '_verified']:
                raise RuntimeError('Do not enable an unvalidated conditional calendar method.')

    invitations = None
    try:
        INVITATIONS.lstat()
    except FileNotFoundError:
        pass
    else:
        invitations = policy_from_config(trusted_json(INVITATIONS), policy)
        if changes and (changes['update_enabled'] or changes['cancel_enabled']):
            raise RuntimeError('Keep update and cancellation disabled during the invitation pilot.')

    writer_records = [dict(record) for record in records]
    for record in writer_records:
        if record['id'] == policy['account_id']:
            record.update(create_ids=policy['create_ids'], write_password_file=policy['write_password_file'])
            if changes:
                # Retain permissions for GET-only reconciliation when write gates are disabled.
                record.update(update_ids=changes['calendar_ids'], cancel_ids=changes['calendar_ids'])
    writer_accounts = CalendarAccounts(json.dumps(writer_records))
    register_reads(app, accounts=read_accounts, legacy_writes=False)
    settings = {
        'INBOXTETHER_CALDAV_CREATE_ENABLED': '1' if policy['enabled'] else '0',
        'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED': '1' if policy['enabled'] else '0',
        'INBOXTETHER_CALDAV_RADAR_UPDATE_ENABLED': '1' if changes and changes['update_enabled'] else '0',
        'INBOXTETHER_CALDAV_RADAR_CANCEL_ENABLED': '1' if changes and changes['cancel_enabled'] else '0',
        'INBOXTETHER_CALDAV_RADAR_UPDATE_CONDITIONAL_VERIFIED':
            '1' if changes and changes['conditional_update_verified'] else '0',
        'INBOXTETHER_CALDAV_RADAR_CANCEL_CONDITIONAL_VERIFIED':
            '1' if changes and changes['conditional_cancel_verified'] else '0',
        'INBOXTETHER_CALDAV_RADAR_STATE_DIR': str(state),
        'INBOXTETHER_CALDAV_RADAR_MAX_PUTS_PER_HOUR': str(policy['max_attempts_per_hour']),
        'INBOXTETHER_CALDAV_RADAR_MAX_PUTS_PER_DAY': str(policy['max_attempts_per_day']),
    }
    with registration_environment(settings):
        register_owner_operations(app, writer_accounts, invitations=invitations)
    from carddav_contacts import register_configured
    register_configured(app, read_accounts, CONTACTS)
