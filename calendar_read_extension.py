"""Register calendar reads and the configured standalone creation pilot."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat


CONFIG = Path('/etc/inboxtether-calendar-radar/accounts.json')
CREATION = Path('/etc/inboxtether-calendar-radar/creation.json')
INVITATIONS = Path('/etc/inboxtether-calendar-radar/invitations.json')
CONTACTS = Path('/etc/inboxtether-calendar-radar/contacts.json')
WRITE_FLAGS = (
    'INBOXTETHER_CALDAV_CREATE_ENABLED', 'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED',
    'INBOXTETHER_CALDAV_RADAR_UPDATE_ENABLED', 'INBOXTETHER_CALDAV_RADAR_CANCEL_ENABLED',
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

    invitations = policy_from_config(trusted_json(INVITATIONS), policy)
    writer_records = [dict(record) for record in records]
    for record in writer_records:
        if record['id'] == policy['account_id']:
            record.update(create_ids=policy['create_ids'], write_password_file=policy['write_password_file'])
    writer_accounts = CalendarAccounts(json.dumps(writer_records))
    register_reads(app, accounts=read_accounts, legacy_writes=False)
    settings = {
        'INBOXTETHER_CALDAV_CREATE_ENABLED': '1' if policy['enabled'] else '0',
        'INBOXTETHER_CALDAV_RADAR_CREATE_ENABLED': '1' if policy['enabled'] else '0',
        'INBOXTETHER_CALDAV_RADAR_UPDATE_ENABLED': '0',
        'INBOXTETHER_CALDAV_RADAR_CANCEL_ENABLED': '0',
        'INBOXTETHER_CALDAV_RADAR_STATE_DIR': str(state),
        'INBOXTETHER_CALDAV_RADAR_MAX_PUTS_PER_HOUR': str(policy['max_attempts_per_hour']),
        'INBOXTETHER_CALDAV_RADAR_MAX_PUTS_PER_DAY': str(policy['max_attempts_per_day']),
    }
    with registration_environment(settings):
        register_owner_operations(app, writer_accounts, invitations=invitations)
    from carddav_contacts import register_configured
    register_configured(app, read_accounts, CONTACTS)
