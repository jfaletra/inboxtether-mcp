"""Operator-configured account and calendar routing for the private owner worker."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from sogo_calendar import CalendarError, MAX_CALENDARS, SogoCalendar


@dataclass(frozen=True)
class Account:
    key: str
    reader: SogoCalendar
    write_secret: str | None
    read_ids: frozenset[str]
    full_visibility: frozenset[str]
    permissions: dict[str, frozenset[str]]


class CalendarAccounts:
    def __init__(self, encoded):
        self.accounts = {}
        self.aliases = {}
        self.targets = {}
        try:
            records = json.loads(encoded)
            if not isinstance(records, list) or not 1 <= len(records) <= MAX_CALENDARS:
                raise ValueError
            principals = set()
            credential_paths = set()
            for row in records:
                account = self.parse(row)
                principal = (account.reader.host, account.reader.port,
                             account.reader.username.casefold(), account.reader.home)
                paths = {Path(value) for value in (account.reader.password_file, account.write_secret) if value}
                if account.key in self.accounts or principal in principals or credential_paths & paths:
                    raise ValueError
                principals.add(principal)
                credential_paths.update(paths)
                self.accounts[account.key] = account
                self.targets.update((f'{account.key}:{path}', (account, path)) for path in account.read_ids)
                aliases = row.get('aliases', {})
                if not isinstance(aliases, dict):
                    raise ValueError
                for label, path in aliases.items():
                    alias = label.casefold()
                    if (not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9 _-]{0,59}', label)
                            or label != label.strip() or alias in self.aliases or path not in account.read_ids):
                        raise ValueError
                    self.aliases[alias] = label, f'{account.key}:{path}'
        except (CalendarError, KeyError, TypeError, ValueError):
            raise CalendarError('Invalid owner calendar account or alias configuration.') from None

    @staticmethod
    def parse(row):
        if not isinstance(row, dict) or set(row) - {
            'id', 'home_url', 'username', 'password_file', 'write_password_file', 'read_ids',
            'full_visibility_ids', 'create_ids', 'update_ids', 'cancel_ids', 'aliases',
        }:
            raise ValueError
        key = row['id']
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', key):
            raise ValueError
        secret = row['password_file']
        write_secret = row.get('write_password_file')
        if any(not Path(value).is_absolute() or '..' in Path(value).parts
               for value in (secret, write_secret) if value is not None) or not secret:
            raise ValueError
        username = row['username']
        if not isinstance(username, str) or not username or any(ord(char) <= 32 for char in username):
            raise ValueError
        reader = SogoCalendar(row['home_url'], username, secret)

        def paths(name):
            values = row.get(name, [])
            if (not isinstance(values, list) or len(values) > MAX_CALENDARS
                    or any(not isinstance(path, str) or not path.startswith(reader.home)
                           or path == reader.home or not path.endswith('/')
                           or reader.resource(path, reader.home) != path for path in values)
                    or len(set(values)) != len(values)):
                raise ValueError
            return frozenset(values)

        read_ids, visibility = paths('read_ids'), paths('full_visibility_ids')
        permissions = {action: paths(action + '_ids') for action in ('create', 'update', 'cancel')}
        if (not read_ids or not visibility <= read_ids or any(not ids <= visibility for ids in permissions.values())
                or (any(permissions.values()) and write_secret is None)):
            raise ValueError
        return Account(key, reader, write_secret, read_ids, visibility, permissions)

    def resolve(self, calendar_id):
        _, key = self.aliases.get(calendar_id.casefold(), (None, calendar_id))
        if key not in self.targets:
            raise CalendarError('Calendar alias or ID is outside the configured account allowlists.')
        return key

    def selection(self, calendar_ids):
        keys = [self.resolve(calendar_id) for calendar_id in calendar_ids]
        if not 1 <= len(keys) <= MAX_CALENDARS or len(set(keys)) != len(keys):
            raise CalendarError('Select 1 to 10 distinct calendar IDs.')
        return keys

    def calendars(self):
        results = {}
        for account in self.accounts.values():
            for path, row in account.reader.calendars().items():
                if path in account.read_ids:
                    key = f'{account.key}:{path}'
                    results[key] = {**row, 'calendar_id': key, 'account_id': account.key,
                                    'aliases': [label for label, target in self.aliases.values() if target == key]}
        return results

    def events(self, calendar_id, start, end):
        account, path = self.targets[self.resolve(calendar_id)]
        return account.reader.events(path, start, end)

    def event(self, calendar_id, event_id):
        account, path = self.targets[self.resolve(calendar_id)]
        return account.reader.event(path, event_id)

    def calendar_selection(self, calendar_ids):
        inventory = {}
        accounts = {}
        for key in self.selection(calendar_ids):
            account, path = self.targets[key]
            if account.key not in accounts:
                accounts[account.key] = account.reader.calendars()
            if path in accounts[account.key]:
                inventory[key] = accounts[account.key][path]
        return inventory

    def complete_resources(self, calendar_id):
        account, path = self.targets[calendar_id]
        return account.reader.complete_resources(path)

    def verified(self, calendar_id):
        account, path = self.targets[calendar_id]
        return path in account.full_visibility
