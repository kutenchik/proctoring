"""Teacher-scoped PINs. No secret or reusable authorization leaves this service."""
import re
from .security import hash_password, verify_password
from .service import Problem, iso


class ProtectionPins:
    def __init__(self, service):
        self.service = service

    def status(self, owner):
        with self.service.database.connect() as db:
            row = db.execute('SELECT revision,updated_at FROM protection_pins WHERE teacher_id=?', (owner,)).fetchone()
            return {'configured': row is not None, 'revision': row['revision'] if row else 0,
                    'updated_at': iso(row['updated_at']) if row else None}

    def change(self, owner, data):
        if set(data) != {'pin', 'confirm_pin', 'revision'} or type(data['revision']) is not int:
            raise Problem('invalid_pin_request', 'Invalid PIN request')
        pin = data['pin']
        if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{6,12}', pin) or pin != data['confirm_pin']:
            raise Problem('invalid_pin', 'Enter matching PINs of 6–12 digits')
        verifier = hash_password('protection-pin:' + pin)
        now = self.service.clock()
        with self.service.database.connect(write=True) as db:
            old = db.execute('SELECT revision FROM protection_pins WHERE teacher_id=?', (owner,)).fetchone()
            revision = old['revision'] if old else 0
            if data['revision'] != revision:
                raise Problem('pin_revision_changed', 'PIN changed; refresh before trying again', 409)
            db.execute('INSERT INTO protection_pins VALUES (?,?,?,?) ON CONFLICT(teacher_id) DO UPDATE SET verifier=excluded.verifier,revision=excluded.revision,updated_at=excluded.updated_at',
                       (owner, verifier, revision + 1, now))
            self.service.audit(db, owner, 'protection_pin_changed', owner, now, details={'revision': revision + 1})
        return self.status(owner)

    def context(self, db, credential):
        attempt = self.service.credential_attempt(db, credential)
        if attempt['finished_at'] is not None:
            raise Problem('attempt_finished', 'Attempt has ended', 409)
        exam = db.execute('SELECT teacher_id FROM exams WHERE id=?', (attempt['exam_id'],)).fetchone()
        return attempt, exam['teacher_id']

    def revision(self, credential):
        with self.service.database.connect() as db:
            _, owner = self.context(db, credential)
        return self.status(owner)

    def verify(self, credential, data):
        if set(data) != {'pin', 'revision', 'action', 'nonce'} or data['action'] not in ('proctor.pause','proctor.resume','proctor.end') or type(data['revision']) is not int or not isinstance(data['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', data['nonce']):
            raise Problem('invalid_pin_request', 'Invalid privileged-action request')
        if not isinstance(data['pin'], str) or not re.fullmatch('[0-9]{6,12}', data['pin']):
            raise Problem('invalid_pin', 'Incorrect PIN', 403)
        now = self.service.clock()
        with self.service.database.connect(write=True) as db:
            attempt, owner = self.context(db, credential)
            db.execute('DELETE FROM protection_pin_attempts WHERE created_at<?', (now-900,))
            count = db.execute('SELECT COUNT(*) FROM protection_pin_attempts WHERE teacher_id=? AND created_at>?', (owner, now-900)).fetchone()[0]
            if count >= 10:
                raise Problem('pin_rate_limited', 'Too many PIN attempts; wait 15 minutes', 429)
            db.execute('INSERT INTO protection_pin_attempts VALUES (?,?,?)', (owner, attempt['id'], now))
            row = db.execute('SELECT * FROM protection_pins WHERE teacher_id=?', (owner,)).fetchone()
            allowed = bool(row and row['revision'] == data['revision'] and verify_password('protection-pin:'+data['pin'], row['verifier']))
            self.service.audit(db, owner, 'protection_pin_verified' if allowed else 'protection_pin_rejected', attempt['id'], now,
                               details={'action': data['action'], 'revision': data['revision']})
        # Raise after commit: failed attempts must consume their rate limit.
        if not allowed:
            raise Problem('invalid_pin', 'Incorrect PIN or changed PIN revision', 403)
        return {'authorized': True, 'action': data['action'], 'nonce': data['nonce'], 'revision': data['revision']}
