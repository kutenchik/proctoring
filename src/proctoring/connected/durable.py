"""Small transactional encrypted attempt journal. No evidence or secrets in UI.

SQLite transactions are short; evidence hashing/HTTP runs in the sync worker.
The journal lives outside session directories, so receipts survive cleanup.
"""
import json
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from .vault import WindowsVault, new_device


class DurableJournal:
    def __init__(self, path, *, vault=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.vault = vault if vault is not None else WindowsVault()
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, sealed BLOB NOT NULL)')
        if self.get('device') is None:
            self.put('device', new_device())

    def connect(self):
        db = sqlite3.connect(self.path, timeout=2.)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA secure_delete=ON')
        return db

    def get(self, key):
        with self.lock, self.connect() as db:
            row = db.execute('SELECT sealed FROM records WHERE id=?', (key,)).fetchone()
        return json.loads(self.vault.decrypt(row[0])) if row else None

    def put(self, key, value):
        sealed = self.vault.encrypt(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO records VALUES (?,?) ON CONFLICT(id) DO UPDATE SET sealed=excluded.sealed', (key, sealed))

    def update(self, key, **changes):
        with self.lock:
            value = self.get(key) or {}
            value.update(changes)
            self.put(key, value)
            return value

    def attempts(self):
        with self.lock, self.connect() as db:
            keys = [r[0] for r in db.execute("SELECT id FROM records WHERE id LIKE 'attempt:%' ORDER BY rowid")]
        return [self.get(k) for k in keys]

    def prepare_admission(self, server, identity):
        pending = self.get('pending_admission')
        if pending and not pending.get('consumed') and pending['server'] == server and pending['identity'] == identity:
            return pending
        value = {'server': server, 'identity': identity, 'admission_id': uuid4().hex,
                 'credential': __import__('secrets').token_urlsafe(32), **self.get('device')}
        self.put('pending_admission', value)
        return value

    def admit(self, server, admission, identity, credential):
        key = 'attempt:'+admission['attempt_id']
        previous = self.get(key)
        if previous:
            return previous
        value = {'attempt_id': admission['attempt_id'], 'server': server, 'admission': admission,
                 'identity': identity, 'credential': credential, **self.get('device'),
                 'session_id': 'session-'+uuid4().hex, 'start_key': uuid4().hex,
                 'phase': 'preparation', 'sync_status': 'pending', 'checkpoint': None,
                 'receipt': None, 'cleanup': False, 'event_cursor': 0, 'offsets': {}}
        self.put(key, value)
        self.put('pending_admission', {'consumed': True})
        return value
