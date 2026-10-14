"""Teacher decisions are versioned separately from immutable uploaded records."""
from __future__ import annotations

import json
import math
from datetime import datetime

from .service import Problem, encoded, identifier, iso

DECISIONS = {'not_reviewed', 'confirmed', 'false_positive', 'insufficient_evidence'}
CONCLUSIONS = {'none_confirmed', 'violation_confirmed', 'insufficient_evidence'}
BEHAVIORAL = {'phone_visible', 'phone_raised', 'second_person', 'face_absent',
              'gaze_down', 'gaze_left', 'gaze_right', 'gaze_deviation', 'head_down',
              'voice_detected', 'impersonation_suspected', 'earphone_suspected'}


def prose(value, *, maximum=4000, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise Problem('invalid_review', f'Text must be {"nonempty and " if required else ""}at most {maximum} characters')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise Problem('invalid_review', 'Text contains unsupported control characters')
    return value.strip()


def version_value(data):
    value = data.get('expected_version')
    if type(value) is not int or value < 0:
        raise Problem('invalid_review', 'A nonnegative expected version is required')
    return value


def _timestamp(record):
    return record.get('start_timestamp') or record.get('timestamp') or record.get('activated_at')


def _instant(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


def event_projection(records, files):
    """Latest presentation per stable event; the raw append-only rows stay intact."""
    events = {}
    for position, item in enumerate(records):
        record = item.get('record', item)
        if not isinstance(record, dict) or not record.get('event_type'):
            continue
        if record.get('state') == 'candidate' or record.get('record_kind') == 'session_header':
            continue
        kind = str(record['event_type'])
        event_id = str(record.get('event_id') or f"record-{item.get('sequence', position)}")
        prior = events.get(event_id, {})
        raw = {**prior.get('raw', {}), **record}
        timestamp = _timestamp(raw)
        relative = raw.get('snapshot_path') or raw.get('snapshot')
        matching = [{'id': f['id'], 'kind': f['kind']} for f in files
                    if f.get('kind') == 'snapshot' and f.get('relative_path') == relative and f.get('complete')]
        # Existing lifecycle records use `duration`; detector events use
        # `duration_seconds`. Point records have no measured interval.
        duration = next((raw[key] for key in ('duration_seconds', 'duration')
                         if type(raw.get(key)) in (int, float) and
                         math.isfinite(raw[key]) and raw[key] >= 0), None)
        events[event_id] = {'event_id': event_id, 'event_type': kind, 'timestamp': timestamp,
                            'duration_seconds': duration,
                            'category': 'behavioral' if kind.lower() in BEHAVIORAL else 'technical',
                            'raw': raw, 'files': matching}
    return sorted(events.values(), key=lambda e: (str(e['timestamp'] or ''), e['event_id']))


def event_groups(events, gap_seconds=10):
    """Presentation grouping only; original identifiers and decisions remain separate."""
    groups, latest = [], {}
    for event in events:
        key = (event['event_type'], event['category'])
        stamp = _instant(event['timestamp'])
        old = latest.get(key)
        if old and len(old['event_ids']) < 100 and stamp is not None and old['_end'] is not None and stamp-old['_end'] <= gap_seconds:
            group = old
            group['event_ids'].append(event['event_id'])
        else:
            group = {'id': 'group-'+event['event_id'], 'event_type': key[0], 'category': key[1],
                     'event_ids': [event['event_id']], '_end': stamp}
            groups.append(group)
            latest[key] = group
        duration = event['duration_seconds']
        end = stamp + max(0., float(duration)) if stamp is not None and type(duration) in (int, float) else stamp
        group['_end'] = max(group['_end'], end) if group['_end'] is not None and end is not None else end
    return [{k: v for k, v in group.items() if k != '_end'} for group in groups]


class ReviewService:
    def __init__(self, service, sync):
        self.service, self.sync = service, sync
        self.database, self.clock = service.database, service.clock

    def _owned(self, connection, owner, attempt_id):
        row = self.service.owned_attempt(connection, owner, attempt_id)
        deleted = connection.execute('SELECT deleted_at,deletion_pending FROM sync_attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
        if deleted and (deleted['deleted_at'] is not None or deleted['deletion_pending']):
            raise Problem('materials_deleted', 'Attempt materials have been deleted', 410)
        return row

    @staticmethod
    def _review_doc(row):
        return {**{k: row[k] for k in ('version', 'decision', 'comment', 'teacher_id', 'teacher_name')},
                'created_at': iso(row['created_at'])}

    @staticmethod
    def _manual_doc(row):
        return {'id': row['observation_id'], **{k: row[k] for k in
            ('version', 'category', 'description', 'phase', 'author_id', 'author_name', 'changed_by')},
            'cancelled': bool(row['cancelled']), 'created_at': iso(row['created_at']), 'updated_at': iso(row['updated_at'])}

    @staticmethod
    def _conclusion_doc(row):
        return {**{k: row[k] for k in ('id', 'version', 'decision', 'comment', 'unreviewed_count',
                                     'teacher_id', 'teacher_name', 'report_status', 'report_error')},
                'created_at': iso(row['created_at']), 'needs_reconsideration': bool(row['needs_reconsideration']),
                'report_url': f"/api/v1/attempts/{row['attempt_id']}/reports/reviewed/{row['version']}"}

    def detail(self, owner, attempt_id):
        source = self.sync.teacher_detail(owner, attempt_id)
        with self.database.connect() as connection:
            attempt = self._owned(connection, owner, attempt_id)
            exam = self.service.owned_exam(connection, owner, attempt['exam_id'])
            events = event_projection(source.get('records', []), source.get('files', []))
            rows = connection.execute('SELECT r.*,t.name teacher_name FROM event_review_versions r JOIN teachers t ON t.id=r.teacher_id WHERE attempt_id=? ORDER BY event_id,version', (attempt_id,)).fetchall()
            histories = {}
            for row in rows:
                histories.setdefault(row['event_id'], []).append(self._review_doc(row))
            for event in events:
                event['history'] = histories.get(event['event_id'], [])
                event['review'] = event['history'][-1] if event['history'] else {
                    'version': 0, 'decision': 'not_reviewed', 'comment': '', 'teacher_id': None,
                    'teacher_name': None, 'created_at': None}
            manual = self._manuals(connection, attempt_id)
            conclusions = [self._conclusion_doc(row) for row in connection.execute(
                'SELECT c.*,t.name teacher_name FROM attempt_conclusions c JOIN teachers t ON t.id=c.teacher_id WHERE attempt_id=? ORDER BY version', (attempt_id,))]
            can_finalize = True
            try:
                self.sync.require_complete(connection, attempt_id)
            except Problem:
                can_finalize = False
            return {'attempt': self.service.attempt_document(attempt, connection),
                    'exam': {key: exam[key] for key in ('id', 'title', 'exam_type', 'timezone', 'duration_seconds')},
                    'sync': {k: v for k, v in source.items() if k not in ('records', 'attempt', 'exam')},
                    'events': events, 'groups': event_groups(events), 'manual_observations': manual,
                    'conclusion': conclusions[-1] if conclusions else None, 'conclusion_history': conclusions,
                    'unreviewed_count': sum(e['category'] == 'behavioral' and e['review']['decision'] == 'not_reviewed' for e in events),
                    'can_finalize': can_finalize}

    def _manuals(self, connection, attempt_id):
        histories = {}
        rows = connection.execute('SELECT m.*,t.name author_name FROM manual_observation_versions m JOIN teachers t ON t.id=m.author_id WHERE attempt_id=? ORDER BY created_at,observation_id,version', (attempt_id,))
        for row in rows:
            histories.setdefault(row['observation_id'], []).append(self._manual_doc(row))
        return [{**history[-1], 'history': history} for history in histories.values()]

    def _invalidate(self, connection, attempt_id):
        connection.execute('UPDATE attempt_conclusions SET needs_reconsideration=1 WHERE attempt_id=? AND version=(SELECT MAX(version) FROM attempt_conclusions WHERE attempt_id=?)', (attempt_id, attempt_id))

    def review(self, owner, attempt_id, data):
        items = data.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise Problem('invalid_review', 'Review one to 100 events per request')
        events = {e['event_id'] for e in self.detail(owner, attempt_id)['events']}
        seen = set()
        with self.database.connect(write=True) as connection:
            self._owned(connection, owner, attempt_id)
            for item in items:
                if not isinstance(item, dict):
                    raise Problem('invalid_review', 'Invalid review item')
                event_id = item.get('event_id')
                if not isinstance(event_id, str) or event_id not in events or event_id in seen:
                    raise Problem('invalid_review', 'Event is missing or repeated')
                seen.add(event_id)
                decision = item.get('decision')
                if not isinstance(decision, str) or decision not in DECISIONS:
                    raise Problem('invalid_review', 'Unsupported observation decision')
                comment, expected = prose(item.get('comment', '')), version_value(item)
                old = connection.execute('SELECT * FROM event_review_versions WHERE attempt_id=? AND event_id=? ORDER BY version DESC LIMIT 1', (attempt_id, event_id)).fetchone()
                current = old['version'] if old else 0
                if expected != current:
                    raise Problem('review_conflict', 'The review changed; refresh before saving', 409)
                now = self.clock()
                connection.execute('INSERT INTO event_review_versions VALUES (?,?,?,?,?,?,?)', (attempt_id, event_id, current+1, decision, comment, owner, now))
                self.service.audit(connection, owner, 'event_reviewed', attempt_id, now, details={
                    'event_id': event_id, 'old': {'decision': old['decision'], 'comment': old['comment']} if old else None,
                    'new': {'decision': decision, 'comment': comment}, 'version': current+1})
            self._invalidate(connection, attempt_id)
        return self.detail(owner, attempt_id)

    def manual(self, owner, attempt_id, data, observation_id=None):
        category = prose(data.get('category'), maximum=100, required=True)
        description = prose(data.get('description'), required=True)
        cancelled = data.get('cancelled', False)
        if type(cancelled) is not bool:
            raise Problem('invalid_review', 'Cancellation must be a boolean')
        with self.database.connect(write=True) as connection:
            attempt = self._owned(connection, owner, attempt_id)
            now = self.clock()
            if observation_id:
                old = connection.execute('SELECT * FROM manual_observation_versions WHERE observation_id=? AND attempt_id=? ORDER BY version DESC LIMIT 1', (observation_id, attempt_id)).fetchone()
                if not old:
                    raise Problem('not_found', 'Manual observation not found', 404)
                if version_value(data) != old['version']:
                    raise Problem('review_conflict', 'The observation changed; refresh before saving', 409)
                version, author, created, phase = old['version']+1, old['author_id'], old['created_at'], old['phase']
            else:
                old = None
                observation_id, version, author, created = identifier(), 1, owner, now
                state = connection.execute('SELECT lifecycle,ended_at FROM sync_attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
                phase = 'during_exam' if attempt['started_at'] is not None and attempt['finished_at'] is None and not (state and state['ended_at']) else 'later_review'
            connection.execute('INSERT INTO manual_observation_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (observation_id, attempt_id, version, category, description, int(cancelled), phase, author, created, owner, now))
            self.service.audit(connection, owner, 'manual_observation_changed', attempt_id, now, details={
                'observation_id': observation_id, 'version': version,
                'old': {k: old[k] for k in ('category','description','cancelled')} if old else None,
                'new': {'category': category, 'description': description, 'cancelled': cancelled}})
            self._invalidate(connection, attempt_id)
        return self.detail(owner, attempt_id)

    def conclude(self, owner, attempt_id, data):
        decision = data.get('decision')
        if not isinstance(decision, str) or decision not in CONCLUSIONS:
            raise Problem('invalid_conclusion', 'Unsupported final conclusion')
        expected, comment = version_value(data), prose(data.get('comment', ''))
        # Read inside the serialized transaction through the same connection in
        # a second pass below, to reject a stale snapshot instead of losing edits.
        snapshot = self.detail(owner, attempt_id)
        with self.database.connect(write=True) as connection:
            self._owned(connection, owner, attempt_id)
            receipt = self.sync.require_complete(connection, attempt_id)
            if not snapshot['sync'].get('receipt') or snapshot['sync']['receipt'].get('manifest_sha256') != receipt.get('manifest_sha256'):
                raise Problem('review_conflict', 'Evidence receipt changed; refresh before concluding', 409)
            old = connection.execute('SELECT * FROM attempt_conclusions WHERE attempt_id=? ORDER BY version DESC LIMIT 1', (attempt_id,)).fetchone()
            current = old['version'] if old else 0
            if expected != current:
                raise Problem('review_conflict', 'The conclusion changed; refresh before saving', 409)
            latest_reviews = {r['event_id']: r['version'] for r in connection.execute('SELECT event_id,MAX(version) version FROM event_review_versions WHERE attempt_id=? GROUP BY event_id', (attempt_id,))}
            if any(latest_reviews.get(e['event_id'], 0) != e['review']['version'] for e in snapshot['events']):
                raise Problem('review_conflict', 'Event decisions changed; refresh before concluding', 409)
            current_manual = self._manuals(connection, attempt_id)
            if current_manual != snapshot['manual_observations']:
                raise Problem('review_conflict', 'Manual observations changed; refresh before concluding', 409)
            unreviewed = snapshot['unreviewed_count']
            if unreviewed and data.get('confirm_unreviewed') is not True:
                raise Problem('unreviewed_confirmation_required', f'{unreviewed} observations remain unreviewed; explicitly confirm before finalizing', 409)
            now, conclusion_id = self.clock(), identifier()
            receipt_id = receipt['receipt_id'] if isinstance(receipt, dict) else json.loads(receipt['payload'])['receipt_id']
            # No prior conclusion/history duplication inside each immutable PDF snapshot.
            snapshot.pop('conclusion_history', None)
            snapshot['conclusion'] = {'id': conclusion_id, 'version': current+1, 'decision': decision,
                'comment': comment, 'unreviewed_count': unreviewed, 'teacher_id': owner, 'created_at': iso(now)}
            teacher = connection.execute('SELECT name FROM teachers WHERE id=?', (owner,)).fetchone()
            snapshot['conclusion']['teacher_name'] = teacher['name']
            connection.execute('INSERT INTO attempt_conclusions (attempt_id,version,id,decision,comment,unreviewed_count,teacher_id,created_at,receipt_id,review_snapshot) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (attempt_id, current+1, conclusion_id, decision, comment, unreviewed, owner, now, receipt_id, encoded(snapshot)))
            self.service.audit(connection, owner, 'attempt_concluded', attempt_id, now, details={
                'old_decision': old['decision'] if old else None, 'new_decision': decision,
                'old_comment': old['comment'] if old else None, 'new_comment': comment,
                'version': current+1, 'unreviewed_count': unreviewed})
        return current+1
