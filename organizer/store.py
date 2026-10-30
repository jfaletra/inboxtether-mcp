"""Private durable ledger. No receipt expiry or state restoration shortcuts."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat
import shutil

from .model import canonical, digest, require


class Store:
    def __init__(self, directory, identity, witness_dir=None):
        self.directory = Path(directory)
        self.identity = canonical(identity)
        self._directory_check()
        from .replay_guard import ReplayGuard
        self.guard = ReplayGuard(witness_dir, self.directory, self.identity) if witness_dir is not None else None
        with self.db() as db:
            old = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='batches'").fetchone()
            require(not old or 'run_id TEXT UNIQUE' not in old[0], 'Legacy batch schema requires explicit offline owner migration.')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, manifest TEXT NOT NULL, fingerprint TEXT NOT NULL,
                  state TEXT NOT NULL, initial INTEGER NOT NULL, uv INTEGER NOT NULL,
                  ceiling INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS items (
                  run_id TEXT NOT NULL REFERENCES runs(id), uid INTEGER NOT NULL,
                  decision TEXT, PRIMARY KEY(run_id,uid));
                CREATE TABLE IF NOT EXISTS batches (
                  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                  manifest TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                  expires REAL NOT NULL, actor TEXT, decided REAL);
                CREATE TABLE IF NOT EXISTS attempts (
                  source_key TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
                  uid INTEGER NOT NULL, state TEXT NOT NULL, evidence TEXT NOT NULL,
                  result TEXT, claimed REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS classification_requests (
                  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), uid INTEGER NOT NULL,
                  manifest TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                  expires REAL NOT NULL, submitted_sha256 TEXT);
                CREATE TABLE IF NOT EXISTS inventory_vetoes (run_id TEXT NOT NULL, uid INTEGER NOT NULL, PRIMARY KEY(run_id,uid));
                CREATE TABLE IF NOT EXISTS decision_history (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, uid INTEGER NOT NULL,
                  prior_decision TEXT NOT NULL, prior_manifest TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS item_generations (
                  run_id TEXT NOT NULL, uid INTEGER NOT NULL, generation INTEGER NOT NULL,
                  PRIMARY KEY(run_id,uid));
                CREATE INDEX IF NOT EXISTS classification_requests_item ON classification_requests(run_id,uid);
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                  reference TEXT NOT NULL, data TEXT NOT NULL, at REAL NOT NULL);
            ''')
            existing = db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()
            require(existing is None or existing[0] == self.identity, 'State belongs to another account or owner.')
            db.execute("INSERT OR IGNORE INTO meta VALUES ('identity',?)", (self.identity,))
            db.commit()

    def _directory_check(self):
        info = self.directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and not self.directory.is_symlink()
                and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'State directory must be private and service-owned.')

    @contextmanager
    def db(self):
        if self.guard is None:
            with self._database() as db:
                yield db
            return
        with self.guard.lock(self.directory / 'organizer.sqlite3') as token:
            with self._database() as db:
                self.guard.verify(db, token)
                self.guard.checkpoint(db)
                try:
                    yield db
                finally:
                    # Roll back any uncommitted caller transaction, preserving committed claims.
                    db.rollback()
                    self.guard.checkpoint(db)

    @contextmanager
    def _database(self):
        self._directory_check()
        path = self.directory / 'organizer.sqlite3'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe state database.')
        finally:
            os.close(fd)
        db = sqlite3.connect(path, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            # DELETE journal avoids untracked WAL snapshots. Use SQLite backup, not file copies.
            db.execute('PRAGMA journal_mode=DELETE')
            yield db
        finally:
            db.close()

    @contextmanager
    def lock(self):
        self._directory_check()
        fd = os.open(self.directory / 'account.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe account lock.')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                require(False, 'Organizer account is busy.')
            yield
        finally:
            os.close(fd)

    @staticmethod
    def event(db, kind, reference, data, now):
        db.execute('INSERT INTO events(kind,reference,data,at) VALUES (?,?,?,?)',
                   (kind, reference, canonical(data), now))

    def record(self, table, key):
        require(table in ('runs', 'batches', 'classification_requests'), 'Invalid record type.')
        require(isinstance(key, str) and len(key) == 64 and all(c in '0123456789abcdef' for c in key),
                'Invalid record identifier.')
        with self.db() as db:
            row = db.execute('SELECT * FROM ' + table + ' WHERE id=?', (key,)).fetchone()
        require(row is not None, 'Organization record unavailable.')
        result = dict(row)
        manifest = json.loads(row['manifest'])
        require(canonical(manifest) == row['manifest'] and digest(manifest) == row['fingerprint'],
                'Organization record integrity failure.')
        result['manifest'] = manifest
        return result

    def verify_identity(self, config):
        require(self.identity == canonical({'host': config.host, 'account': config.account, 'owner': config.owner}),
                'Organization account changed.')

    def ensure_capacity(self, additional_items=0, new_run=False):
        """Fail closed rather than purge replay receipts or exhaust the host volume."""
        self._directory_check()
        require(shutil.disk_usage(self.directory).free >= 67_108_864, 'Ledger reserve exhausted; owner review required.')
        path=self.directory/'organizer.sqlite3'
        require(path.stat().st_size < 536_870_912, 'Ledger retention limit reached; archive under owner control.')
        with self.db() as db:
            require(db.execute('SELECT count(*) FROM classification_requests').fetchone()[0] < 1000000,
                    'Classification request retention limit reached.')
            if new_run:
                require(db.execute('SELECT count(*) FROM runs').fetchone()[0] < 10000, 'Run retention limit reached.')
                require(db.execute('SELECT count(*) FROM items').fetchone()[0] + additional_items <= 1000000,
                        'Item retention limit reached.')
