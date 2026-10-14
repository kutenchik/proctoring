"""Narrow Stage 2 lifecycle adapter; the existing controller still starts/ends.

No device, timer, detection or protection implementation is replaced here.
"""
import json
import math
from pathlib import Path
from uuid import uuid4

from .sync import SyncWorker
from ..storage import SessionStore


class ConnectedWorkflow:
    def __init__(self, bridge):
        self.bridge, self.client = bridge, bridge.admission_client
        self.journal = self.client.journal
        self.worker = SyncWorker(self.journal, bridge.config.sessions_dir, self.client.transport)
        self.last_checkpoint = float('-inf')
        self.background = False
        self.last_report_status = None
        self.error = None
        self.restored = self.client.restored
        self.recovery_authorized = False
        self.reconciled = not self.restored
        bridge.controller.connected_terminal_hook = self.terminal

    def row(self):
        return self.journal.get('attempt:'+self.client.durable['attempt_id']) if self.client.durable else None

    def admitted(self):
        b, c, client = self.bridge, self.bridge.controller, self.client
        row = self.row()
        if not row:
            return
        c.connected_session_id = row['session_id']
        client.persist(identity_required=b.config.identity.selfie_verification_enabled,
                       report_filename=b.config.reporting.report_filename)
        if not self.restored:
            return
        root = b.config.sessions_dir/row['session_id']
        if row.get('cleanup_started') and row.get('receipt'):
            from .sync import verify_receipt
            verify_receipt(row, row['receipt'])
            # Partial cleanup may already have removed session.json/summary.
            # Only resume the matching receipt cleanup, never reopen an exam.
            c.summary = row.get('final_summary') or {'session_id': row['session_id'], 'end_reason':row.get('terminal_reason'),
                'score':None,'total_questions':None,'events':[],'event_count':0}
            c.session.started = c.session.ended = True
            c.session.end_reason = row.get('terminal_reason')
            c.session.duration_seconds = c.summary.get('duration_seconds',c.session.duration_seconds)
            c.session.time_adjustment_ids = list(c.summary.get('time_adjustment_ids',[]))
            c.session._elapsed = c.summary.get('elapsed_seconds', 0.)
            c._restored_report_status = 'disabled'
            b._step = 'summary'
            return
        if row['phase'] not in ('ended_locally', 'terminal_pending') and (root/'events.jsonl').exists():
            # Start and pause records are appended before their encrypted
            # checkpoint. Recover the durable lifecycle tail after a crash in
            # that gap; never invent a second original start timestamp.
            row = client.persist(checkpoint=self.reconcile_lifecycle(root, row.get('checkpoint')))
        if (root/'summary.json').is_file() and row['phase'] not in ('ended_locally','terminal_pending'):
            summary = json.loads((root/'summary.json').read_bytes())
            if summary.get('connected_attempt', {}).get('attempt_id') != row['attempt_id'] or summary.get('session_id') != row['session_id']:
                raise ValueError('terminal_session_identity_mismatch')
            row = client.persist(phase='terminal_pending', terminal_reason=summary['end_reason'])
        elif row['phase'] not in ('ended_locally','terminal_pending') and (root/'events.jsonl').exists():
            records = [json.loads(line) for line in (root/'events.jsonl').read_bytes().splitlines()]
            terminal = next((r for r in reversed(records) if r.get('event_type') == 'connected_terminal'), None)
            if terminal:
                checkpoint = dict(row.get('checkpoint') or self.make_checkpoint())
                checkpoint.update(ended=True, elapsed_seconds=terminal['elapsed_seconds'],
                                  remaining_seconds=max(0., checkpoint.get('duration_seconds',b.config.duration_seconds)-terminal['elapsed_seconds']))
                if not any(r.get('event_type') == 'session_ended' for r in checkpoint.get('lifecycle', [])):
                    checkpoint['lifecycle'] = [*checkpoint.get('lifecycle', []),
                        {'event_type':'session_ended','timestamp':terminal['timestamp'],'reason':terminal['reason'],
                         'elapsed_seconds':terminal['elapsed_seconds']}]
                row = client.persist(phase='terminal_pending', terminal_reason=terminal['reason'], checkpoint=checkpoint)
        if row.get('phase') == 'terminal_pending' and not (root/'summary.json').exists():
            c.store = SessionStore.resume_connected(b.config.sessions_dir, row['session_id'], row['attempt_id'])
            checkpoint = row['checkpoint']
            c.session.started = c.session.ended = True
            c.session.end_reason = row['terminal_reason']
            c.session.duration_seconds = checkpoint.get('duration_seconds',c.session.duration_seconds)
            c.session.time_adjustment_ids = list(checkpoint.get('time_adjustment_ids',[]))
            c.session._elapsed = checkpoint['elapsed_seconds']
            c.session.records = checkpoint.get('lifecycle', [])
            for index, answer in checkpoint.get('answer_indices', {}).items():
                c.quiz.answer(int(index), answer)
            self.restore_events(checkpoint)
            persisted = [json.loads(line) for line in (root/'events.jsonl').read_bytes().splitlines()]
            c._record_cursor = sum(record.get('record_kind') == 'lifecycle' and record.get('event_type') in
                                   {r['event_type'] for r in c.session.records} for record in persisted)
            c._record_cursor = min(c._record_cursor, len(c.session.records))
            c._finalize()
            b._step = 'summary'
        elif row.get('phase') in ('ended_locally', 'terminal_pending'):
            c.store = SessionStore.inspect_ended_connected(b.config.sessions_dir, row['session_id'], row['attempt_id'])
            c.summary = json.loads((root/'summary.json').read_bytes())
            c.session.started = c.session.ended = True
            c.session.end_reason = c.summary['end_reason']
            c.session.duration_seconds = c.summary.get('duration_seconds',c.session.duration_seconds)
            c.session.time_adjustment_ids = list(c.summary.get('time_adjustment_ids',[]))
            c.session._elapsed = c.summary['elapsed_seconds']
            c.session.records = c.summary.get('lifecycle', [])
            for index, answer in c.summary.get('answers', {}).items():
                c.quiz.answer(int(index), answer)
            c._restored_report_status = 'complete' if (root/b.config.reporting.report_filename).is_file() else 'failed'
            b._step = 'summary'
        else:
            if root.exists():
                c.store = SessionStore.resume_connected(b.config.sessions_dir, row['session_id'], row['attempt_id'])
            for index, answer in (row.get('checkpoint') or {}).get('answer_indices', {}).items():
                c.quiz.answer(int(index), answer)
            if row['phase'] in ('locally_started', 'start_authorized', 'start_authorization_pending'):
                self.client.persist(phase='unexpected_interruption', interruption_id=uuid4().hex,
                                    checkpoint=row.get('checkpoint') or self.make_checkpoint())
            self.client.submit('refresh')

    def reconcile_lifecycle(self, root, checkpoint):
        checkpoint = dict(checkpoint or self.make_checkpoint())
        raw = (root/'events.jsonl').read_bytes()
        if raw and not raw.endswith(b'\n'):
            raise ValueError('journal_partial_record')
        kinds = {'session_started', 'session_recovered', 'session_ended', 'monitoring_failed',
                 'monitoring_recovered', 'monitoring_interruption_ended', 'recovery_pin_required',
                 'proctor_paused', 'proctor_resumed', 'presentation_lost', 'presentation_recovered',
                 'teacher_paused','teacher_resumed','teacher_monitoring_recovered','display_interrupted',
                 'teacher_display_recovered','teacher_time_added'}
        records = [{k:v for k,v in record.items() if k not in ('record_kind', 'session_id', 'candidate')}
                   for line in raw.splitlines() if (record := json.loads(line)).get('record_kind') == 'lifecycle'
                   and record.get('event_type') in kinds]
        previous = checkpoint.get('lifecycle', [])
        if records[:len(previous)] != previous:
            raise ValueError('lifecycle_checkpoint_mismatch')
        reasons = set(checkpoint.get('pause_reasons', []))
        for record in records[len(previous):]:
            kind = record['event_type']
            if kind == 'teacher_time_added':
                checkpoint['duration_seconds'] = record['duration_seconds']
                checkpoint['time_adjustment_ids'] = list(dict.fromkeys([*checkpoint.get('time_adjustment_ids',[]),record['command_id']]))
            if kind in ('teacher_paused','display_interrupted'):
                reasons.add('teacher' if kind == 'teacher_paused' else 'display')
            elif kind in ('teacher_resumed','teacher_display_recovered','teacher_monitoring_recovered'):
                reasons.discard({'teacher_resumed':'teacher','teacher_display_recovered':'display','teacher_monitoring_recovered':'recovery_pin'}[kind])
            if kind in ('proctor_paused','recovery_pin_required','monitoring_failed','presentation_lost'):
                reasons.add({'proctor_paused':'proctor','recovery_pin_required':'recovery_pin',
                             'monitoring_failed':'monitoring','presentation_lost':'presentation'}[kind])
            elif kind == 'proctor_resumed':
                reasons -= {'proctor','recovery_pin'}
            elif kind in ('monitoring_recovered','presentation_recovered'):
                reasons.discard('monitoring' if kind == 'monitoring_recovered' else 'presentation')
            elapsed = record.get('elapsed_seconds')
            if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or not 0 <= elapsed <= checkpoint.get('duration_seconds',self.bridge.config.duration_seconds):
                raise ValueError('invalid_lifecycle_timing')
            checkpoint['elapsed_seconds'] = max(checkpoint['elapsed_seconds'], elapsed)
        checkpoint.update(lifecycle=records, pause_reasons=sorted(reasons),
                          remaining_seconds=max(0., checkpoint.get('duration_seconds',self.bridge.config.duration_seconds)-checkpoint['elapsed_seconds']))
        return checkpoint

    def operation(self, operation):
        row = self.row()
        if not row:
            return
        if operation == 'refresh' and self.restored and not self.reconciled:
            checkpoint = row.get('checkpoint') or self.make_checkpoint()
            if self.client.admission.get('lifecycle') == 'admitted' and not self.client.admission.get('start_key'):
                if checkpoint['elapsed_seconds'] != 0 or any(r.get('event_type') == 'session_started' for r in checkpoint.get('lifecycle', [])):
                    self.error = 'start_reconciliation_conflict'
                    return
                self.client.persist(phase='preparation', interruption_id=None, checkpoint=None)
                self.reconciled = True
                return
            if row['phase'] in ('locally_started', 'start_authorized', 'start_authorization_pending', 'unexpected_interruption'):
                checkpoint = row.get('checkpoint') or self.make_checkpoint()
                interruption = row.get('interruption_id') or uuid4().hex
                self.client.persist(phase='unexpected_interruption', interruption_id=interruption, checkpoint=checkpoint)
                self.client.submit('interrupted', {'interruption_id': interruption, 'session_id': row['session_id'],
                    'reason': 'unexpected_application_closure', 'checkpoint': self.server_checkpoint(checkpoint)})
            else:
                self.reconciled = True
        if operation == 'interrupted':
            self.reconciled = True
        if operation == 'recover':
            self.recovery_authorized = True

    def can_prepare(self):
        return self.row() is not None and self.reconciled

    def can_start(self):
        row = self.row()
        if not row or not self.reconciled:
            return False
        if row['phase'] == 'unexpected_interruption':
            recovery = self.client.admission.get('recovery') or {}
            return self.recovery_authorized or recovery.get('state') in ('granted', 'authorized', 'consumed')
        return self.client.start_authorized or self.client.deadline > self.bridge.clock.monotonic()

    def request_start(self):
        row = self.row()
        if row['phase'] == 'unexpected_interruption':
            recovery = self.client.admission.get('recovery') or {}
            grant = recovery.get('grant_id')
            if not grant:
                raise ValueError('teacher_recovery_required')
            self.client.persist(recovery_grant=grant)
            self.client.submit('recover', {'grant_id': grant, 'session_id': row['session_id']})
        else:
            self.client.submit('start')

    def before_start(self):
        row, c = self.row(), self.bridge.controller
        if row['phase'] == 'unexpected_interruption':
            if not self.recovery_authorized:
                raise ValueError('teacher_recovery_required')
            checkpoint = row['checkpoint']
            c.session.restore_connected_checkpoint(checkpoint)
            # Historic events are closed at the last checkpoint. No stale
            # evidence duration crosses the app outage, and future IDs advance.
            self.restore_events(checkpoint)
            c._record_cursor = len(c.session.records)
            c._append({'record_kind': 'lifecycle', 'event_type': 'application_recovered',
                       'timestamp': c.clock.wall_time(), 'elapsed_seconds': c.session.elapsed_seconds,
                       'interruption_id': row.get('interruption_id')})

    def restore_events(self, checkpoint):
        c = self.bridge.controller
        history = {event['event_id']: dict(event) for event in checkpoint.get('events', [])}
        snapshots = dict(checkpoint.get('snapshots', {}))
        # The fsynced journal may be newer than the one-second timer checkpoint.
        # Preserve its tail and advance existing deterministic event IDs.
        if c.store is not None:
            with (c.store.path/'events.jsonl').open('r', encoding='utf-8') as source:
                for line in source:
                    record = json.loads(line)
                    if record.get('event_id'):
                        history[record['event_id']] = {**history.get(record['event_id'], {}), **record}
                        if record.get('snapshot_path'):
                            snapshots[record['event_id']] = record['snapshot_path']
        c.events._events = []
        if c.audio_events is not None:
            c.audio_events._events = []
        c.security_events = []
        for original in history.values():
            event = dict(original)
            kind = event['event_id']
            event['state'] = 'closed'
            if kind.startswith('audio-') and c.audio_events is not None:
                event['event_id'] = kind[6:]
                c.audio_events._events.append(event)
            elif kind.startswith('event-'):
                c.events._events.append(event)
            else:
                c.security_events.append(event)
            c._event_metadata[kind] = {k: v for k, v in original.items() if k in ('severity','review','description')}
        c._snapshots = snapshots

    def terminal(self):
        c, row = self.bridge.controller, self.row()
        if row and c.session.ended and row['phase'] not in ('terminal_pending','ended_locally'):
            # Called after native release and timer freeze, before slow cleanup.
            try:
                if not getattr(self, '_terminal_marker', False) and c.store:
                    c._append({'record_kind':'lifecycle','event_type':'connected_terminal','timestamp':c.clock.wall_time(),
                               'reason':c.session.end_reason,'elapsed_seconds':c.session.elapsed_seconds})
                    c.store.flush_durable()
                    self._terminal_marker = True
                self.client.persist(phase='terminal_pending', terminal_reason=c.session.end_reason,
                                    checkpoint=self.make_checkpoint())
            except Exception:
                self.error = 'terminal_checkpoint_requires_attention'

    def after_start(self):
        row, c = self.row(), self.bridge.controller
        self.checkpoint(force=True)
        if row.get('recovery_grant'):
            confirm = {'grant_id': row['recovery_grant'], 'session_id': row['session_id'],
                       'started_at': next(r['timestamp'] for r in c.session.records if r['event_type'] == 'session_started')}
        else:
            confirm = {'start_key': row['start_key'], 'session_id': row['session_id'],
                       'started_at': next(r['timestamp'] for r in c.session.records if r['event_type'] == 'session_started')}
        self.client.persist(phase='locally_started', pending_confirm=confirm)

    def make_checkpoint(self):
        c = self.bridge.controller
        return {'elapsed_seconds': c.session.elapsed_seconds, 'remaining_seconds': c.session.remaining_seconds,
                'duration_seconds': c.session.duration_seconds, 'time_adjustment_ids': list(c.session.time_adjustment_ids),
                'pause_reasons': sorted(c.session.pause_reasons), 'ended': c.session.ended,
                'answer_indices': c.quiz.answers, 'answers': c.quiz.answer_ids,
                'lifecycle': list(c.session.records), 'events': c.review_events,
                'snapshots': dict(c._snapshots)}

    @staticmethod
    def server_checkpoint(value):
        return {k: value[k] for k in ('elapsed_seconds', 'remaining_seconds', 'answers', 'pause_reasons',
                                    'duration_seconds','time_adjustment_ids') if k in value}

    def checkpoint(self, force=False):
        c, now = self.bridge.controller, self.bridge.clock.monotonic()
        row = self.row()
        if not row or row.get('cleanup') or not c.session.started or (not force and now-self.last_checkpoint < 1.):
            return
        checkpoint = self.make_checkpoint()
        if c.store:
            c.store.flush_durable()
        self.client.persist(checkpoint=checkpoint)
        self.last_checkpoint = now

    def tick(self):
        c = self.bridge.controller
        row = self.row()
        if not row or row.get('cleanup'):
            return
        self.checkpoint()
        if c.session.ended and c.summary is not None:
            row = self.row()
            if row.get('phase') != 'ended_locally':
                self.checkpoint(force=True)
                if c.store:
                    c.store._atomic_json('answers.json', {'attempt_id': row['attempt_id'], 'session_id': row['session_id'],
                        'answers': c.quiz.answer_ids if not c.config.external_url else {},
                        'score': c.summary.get('score'), 'total': c.summary.get('total_questions'),
                        'percentage': c.quiz.percentage if not c.config.external_url else None})
                self.client.persist(phase='ended_locally', terminal_reason=c.session.end_reason)
            released = not self.bridge.native_cleanup_pending and not getattr(c.protection, 'armed', False)
            # A late optional report completion is polled independently. A failed
            # PDF stays missing_required until the operator uses Report retry.
            if released and not row.get('media_released'):
                self.client.persist(media_released=True)
            if row.get('error') == 'required_material_missing' and c.report_status == 'complete' and self.last_report_status != 'complete':
                self.worker.next_retry.pop('attempt:'+row['attempt_id'], None)
            self.last_report_status = c.report_status

    def interrupt(self, reason):
        c = self.bridge.controller
        if c.session.started and not c.session.ended:
            c.session._freeze(c.clock.monotonic())
            c._write_events(c.events.close_all('application_interrupted'))
            if c.audio_events:
                c._write_audio_events(c.audio_events.close_all('application_interrupted'))
            c._append({'record_kind': 'lifecycle', 'event_type': 'application_interrupted', 'timestamp': c.clock.wall_time(),
                       'elapsed_seconds': c.session.elapsed_seconds, 'reason': 'unexpected_application_closure'})
            self.checkpoint(force=True)
            self.client.persist(phase='unexpected_interruption', interruption_id=uuid4().hex)
            c.monitor.stop(timeout=0.)
            if c.audio:
                c.audio.stop(timeout=0.)
            if c.system_checker:
                c.system_checker.stop()
            if c.store:
                c.store.close()

    def public(self):
        row = self.row()
        pending = [r for r in self.journal.attempts() if not r.get('cleanup') and r.get('checkpoint')]
        return {'status': row.get('sync_status', 'pending') if row else 'pending', 'error': self.error or (row or {}).get('error'),
                'phase': (row or {}).get('phase', 'admission'), 'pending_attempts': len(pending),
                'fully_synchronized': bool(row and row.get('cleanup')), 'background': self.background,
                'can_background': bool(row and row.get('phase') == 'ended_locally' and row.get('media_released') and not self.bridge.report_cleanup_pending),
                'recovery_required': bool(row and row.get('phase') == 'unexpected_interruption'),
                'recovery_state': (self.client.admission or {}).get('recovery', {}).get('state') if isinstance((self.client.admission or {}).get('recovery'), dict) else None,
                'remaining_seconds': (row or {}).get('checkpoint', {}).get('remaining_seconds') if (row or {}).get('checkpoint') else None}

    def close(self):
        self.worker.close()
