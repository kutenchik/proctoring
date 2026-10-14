"""Durable Stage 2 outbox: journal batches, bounded chunks, complete receipts.

Only this background worker reads/hashes/uploads evidence. It never touches
devices, the exam clock, protection or detector health. Every retry is keyed by
the canonical session/sequence/item/digest, not by a fresh request identity.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from .client import ConnectedError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(256*1024), b''):
            result.update(block)
    return result.hexdigest()


def evidence_path(root, relative):
    if not isinstance(relative, str) or not re.fullmatch(
            r'(session\.json|events\.jsonl|summary\.json|answers\.json|[A-Za-z0-9_.-]+\.pdf|'
            r'reference_face\.jpg|reference_recovery_[a-f0-9]{32}\.jpg|snapshots/[A-Za-z0-9_-]+\.jpg)', relative):
        raise ValueError('evidence_path_not_allowed')
    root = Path(root)
    target = root/relative
    if root.is_symlink() or any(p.is_symlink() for p in (target, target.parent)) or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('evidence_path_not_allowed')
    return target


def session_root(base, row):
    if not re.fullmatch(r'session-[a-f0-9]{32}', row['session_id']):
        raise ValueError('invalid_session_identity')
    base = Path(base).resolve()
    root = base/row['session_id']
    if root.is_symlink() or root.resolve().parent != base:
        raise ValueError('invalid_session_identity')
    # Cleanup resumption may have removed metadata already; encrypted journal
    # retains the receipt and frozen validated manifest from before deletion.
    if not row.get('cleanup_started'):
        metadata = json.loads(evidence_path(root, 'session.json').read_bytes())
        if metadata.get('session_id') != row['session_id'] or metadata.get('connected_attempt', {}).get('attempt_id') != row['attempt_id']:
            raise ValueError('session_identity_mismatch')
    return root


def build_manifest(base, row):
    root = session_root(base, row)
    summary = json.loads(evidence_path(root, 'summary.json').read_bytes())
    if summary.get('session_id') != row['session_id'] or summary.get('connected_attempt', {}).get('attempt_id') != row['attempt_id']:
        raise ValueError('summary_identity_mismatch')
    items = []
    def item(key, kind, path, required=True, status=None, error=None):
        target = evidence_path(root, path)
        present = target.is_file() and status != 'disabled'
        items.append({'id': key, 'kind': kind, 'relative_path': path, 'required': required,
                      'status': 'present' if present else status or ('missing_error' if required else 'optional_absent'),
                      'size': target.stat().st_size if present else None,
                      'sha256': file_hash(target) if present else None,
                      'error': None if present else error or ('Production material is missing' if required else None)})
    item('session', 'session', 'session.json')
    item('events', 'events', 'events.jsonl')
    item('summary', 'summary', 'summary.json')
    native = row['admission']['exam']['exam_type'] == 'native'
    item('answers', 'answers', 'answers.json', native, None if native else 'disabled')
    item('original_pdf', 'original_pdf', row['report_filename'], True,
         error='Original PDF generation failed or has not completed')
    item('reference', 'reference', 'reference_face.jpg', row.get('identity_required', False))
    for index, path in enumerate(sorted(root.glob('reference_recovery_*.jpg'))):
        item('reference_recovery_'+str(index), 'reference', path.name, True)
    if not row['admission']['exam']['save_snapshots']:
        item('snapshots_disabled', 'snapshot', 'snapshots/disabled.jpg', False, 'disabled')
    else:
        snapshots = {e.get('snapshot_path') for e in summary.get('events', []) if e.get('snapshot_path')}
        for index, path in enumerate(sorted(snapshots)):
            early = next((v for v in row.get('early_snapshots', {}).values() if v.get('path') == path and v.get('declared')), None)
            item(early['item_id'] if early else 'snapshot_'+str(index), 'snapshot', path)
        # A recorded failed capture must stay visible, never manufacture a file.
        for index, error in enumerate(summary.get('snapshot_errors', [])):
            items.append({'id': 'snapshot_error_'+str(index), 'kind': 'snapshot', 'relative_path': 'snapshots/error_'+str(index)+'.jpg',
                          'required': False, 'status': 'missing_error', 'size': None, 'sha256': None,
                          'error': 'Recorded snapshot production error'})
    raw = evidence_path(root, 'events.jsonl').read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('journal_partial_record')
    return {'version': 1, 'attempt_id': row['attempt_id'], 'session_id': row['session_id'],
            'ended_at': summary['ended_at'], 'end_reason': summary['end_reason'],
            'record_count': len(raw.splitlines()), 'identity_required': row.get('identity_required', False), 'items': items}


def verify_receipt(row, receipt):
    manifest = row.get('manifest')
    if not manifest or row.get('phase') != 'ended_locally' or not isinstance(receipt, dict):
        raise ValueError('receipt_not_complete')
    if any(i['required'] and i['status'] != 'present' for i in manifest['items']):
        raise ValueError('required_material_missing')
    expected = {'version': 1, 'attempt_id': row['attempt_id'], 'session_id': row['session_id'],
                'manifest_sha256': digest(manifest), 'record_count': manifest['record_count'],
                'file_count': sum(i['status'] == 'present' for i in manifest['items']), 'complete': True}
    if (any(receipt.get(k) != v for k, v in expected.items()) or receipt.get('complete') is not True or
            any(type(receipt.get(k)) is not int for k in ('version', 'record_count', 'file_count')) or
            not isinstance(receipt.get('receipt_id'), str) or not receipt['receipt_id'] or
            not isinstance(receipt.get('verified_at'), str) or not receipt['verified_at']):
        raise ValueError('receipt_identity_mismatch')
    return True


def cleanup_received(journal, base, row):
    verify_receipt(row, row.get('receipt'))
    root = session_root(base, row)
    key = 'attempt:'+row['attempt_id']
    # Check the full bundle before deleting the first byte. Files modified since
    # upload are retained; a server receipt cannot authorize deleting new data.
    removed = set(row.get('removed', []))
    for item in row['manifest']['items']:
        if item['status'] != 'present' or item['id'] in removed:
            continue
        target = evidence_path(root, item['relative_path'])
        if not target.exists():
            if row.get('cleanup_started'):
                continue  # interruption between unlink and its journal commit
            raise ValueError('local_evidence_missing_before_cleanup')
        if target.stat().st_size != item['size'] or file_hash(target) != item['sha256']:
            raise ValueError('local_evidence_changed')
    journal.update(key, cleanup_started=True)
    for item in row['manifest']['items']:
        if item['status'] == 'present' and item['id'] not in removed:
            evidence_path(root, item['relative_path']).unlink(missing_ok=True)
            removed.add(item['id'])
            journal.update(key, removed=sorted(removed))
    # No recursive deletion: local config and unrelated/unlisted files survive.
    journal.update(key, cleanup=True, sync_status='fully_synchronized', error=None,
                   credential=None, device_secret=None, identity=None, admission=None,
                   checkpoint=None, pending_confirm=None, recovery_grant=None, final_summary=None,
                   live_commands=None, teacher_messages=None, screen_consent=None, display_incident=None,
                   display_calibration_id=None)


class SyncWorker:
    def __init__(self, journal, base, transport, *, clock=time.monotonic):
        self.journal, self.base, self.transport, self.clock = journal, Path(base), transport, clock
        self.stop_event = threading.Event()
        self.thread = None
        self.next_retry = {}
        self.failures = {}

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name='connected-durable-sync')
            self.thread.start()

    def close(self, timeout=0.):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout)

    def _call(self, row, endpoint, payload=None, method='POST'):
        if self.stop_event.is_set():
            raise ConnectedError('stopped')
        try:
            return self.transport(method, row['server'], endpoint, payload, row['credential'])
        except ConnectedError as error:
            diagnostic = getattr(error, 'diagnostic', None)
            if diagnostic is not None:
                # Produced only by the trusted HTTP adapter; never body/URL/error text.
                key = 'attempt:'+row['attempt_id']
                current = next((r for r in self.journal.attempts() if r['attempt_id']==row['attempt_id']), row)
                records = current.get('sync_diagnostics', [])[-31:] + [dict(diagnostic)]
                self.journal.update(key, sync_diagnostics=records, first_sync_failure=current.get('first_sync_failure') or dict(diagnostic))
            raise

    def _records(self, row, root):
        key = 'attempt:'+row['attempt_id']
        cursor = row.get('event_cursor', 0)
        batch, size = [], 0
        with evidence_path(root, 'events.jsonl').open('rb') as handle:
            for sequence, line in enumerate(handle):
                if sequence < cursor:
                    continue
                if not line.endswith(b'\n'):
                    break
                record = json.loads(line)
                if len(canonical(record)) > 64*1024:
                    raise ValueError('journal_record_too_large')
                if batch and (len(batch) >= 100 or size+len(line) > 400*1024):
                    break
                batch.append({'sequence': sequence, 'record': record})
                size += len(line)
        if batch:
            response = self._call(row, '/student/sync/records', {'session_id': row['session_id'], 'records': batch})
            if response.get('accepted_sequences') != [record['sequence'] for record in batch]:
                raise ValueError('invalid_record_acknowledgement')
            cursor = batch[-1]['sequence']+1
            self.journal.update(key, event_cursor=cursor)
        return bool(batch)

    def _snapshots(self, row, root):
        """Journal-backed queue: one bounded chunk per turn, no device/UI work."""
        if not row['admission']['exam']['save_snapshots'] or (row.get('screen_consent') or {}).get('version') != 3:
            return False
        key = 'attempt:'+row['attempt_id']
        pending = dict(row.get('early_snapshots', {}))
        cursor = row.get('snapshot_cursor', 0)
        accepted = row.get('event_cursor', 0)
        offset = row.get('snapshot_offset', 0)
        with evidence_path(root, 'events.jsonl').open('rb') as handle:
            handle.seek(offset)
            for sequence in range(cursor, min(accepted, cursor+100)):
                record_offset = offset
                line = handle.readline()
                if not line.endswith(b'\n'): break
                offset = handle.tell()
                record = json.loads(line)
                event_id, path = record.get('event_id'), record.get('snapshot_path')
                if (isinstance(event_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,96}', event_id)
                        and record.get('event_type') and path == 'snapshots/'+event_id+'.jpg'):
                    if event_id not in pending:
                        if len(pending) >= 1900:
                            # Defer discovery without losing the journal record or
                            # preventing final synchronization of the local bundle.
                            offset = record_offset
                            break
                        pending[event_id] = {'path':path,'item_id':'event_'+hashlib.sha256(event_id.encode()).hexdigest(),'complete':False}
                cursor = sequence+1
        self.journal.update(key, early_snapshots=pending, snapshot_cursor=cursor, snapshot_offset=offset)
        for event_id, item in pending.items():
            if item.get('complete'): continue
            path = evidence_path(root, item['path'])
            if not path.is_file(): continue  # late atomic publication is retried
            if not item.get('sha256'):
                from PIL import Image
                try:
                    size = path.stat().st_size
                    if not 0 < size <= 8*1024*1024: raise ValueError('invalid_snapshot')
                    with Image.open(path) as picture:
                        if picture.format != 'JPEG' or picture.width*picture.height > 16_000_000: raise ValueError('invalid_snapshot')
                        picture.load()
                    item.update(size=size, sha256=file_hash(path))
                except (OSError, ValueError, Image.DecompressionBombError):
                    item['error'] = 'invalid_snapshot'
                    continue
            if file_hash(path) != item['sha256'] or path.stat().st_size != item['size']:
                raise ValueError('local_evidence_changed')
            # Freeze local identity before the request; a lost ACK must not allow
            # finalization to assign a new file ID or delete provisional evidence.
            item['declared'] = True
            self.journal.update(key, early_snapshots=pending)
            status = self._call(row, '/student/sync/snapshots', {'session_id':row['session_id'],
                'event_id':event_id,'size':item['size'],'sha256':item['sha256']})
            offset = status.get('received_bytes')
            if status.get('item_id') != item['item_id'] or type(offset) is not int or not 0 <= offset <= item['size']:
                raise ValueError('invalid_upload_frontier')
            if not status.get('complete'):
                with path.open('rb') as handle:
                    handle.seek(offset); data = handle.read(256*1024)
                status = self._call(row, '/student/sync/snapshots/'+item['item_id']+'/chunks',
                    {'session_id':row['session_id'],'offset':offset,'data_base64':base64.b64encode(data).decode('ascii')})
                if status.get('item_id') != item['item_id'] or status.get('received_bytes') != offset+len(data):
                    raise ValueError('invalid_upload_acknowledgement')
            item['complete'] = status.get('complete') is True and status.get('received_bytes') == item['size']
            item.pop('error', None)
            self.journal.update(key, early_snapshots=pending)
            return True
        self.journal.update(key, early_snapshots=pending)
        return False

    def once(self, row):
        key = 'attempt:'+row['attempt_id']
        if row.get('cleanup') or not row.get('checkpoint'):
            return
        if row.get('receipt'):
            cleanup_received(self.journal, self.base, row)
            return
        root = session_root(self.base, row)
        self.journal.update(key, sync_status='uploading', error=None)
        if row.get('pending_confirm') and row.get('phase') == 'locally_started':
            endpoint = '/student/recovery/confirm' if row.get('recovery_grant') else '/student/start/confirm'
            self._call(row, endpoint, row['pending_confirm'])
            self.journal.update(key, pending_confirm=None)
        records_sent = self._records(row, root)
        row = next(r for r in self.journal.attempts() if r['attempt_id'] == row['attempt_id'])
        if row.get('phase') != 'ended_locally':
            self._snapshots(row, root)
        if records_sent:
            return
        if row.get('phase') != 'ended_locally' or not row.get('media_released'):
            self.journal.update(key, sync_status='pending')
            return
        manifest = build_manifest(self.base, row)
        self.journal.update(key, manifest=manifest, final_summary=json.loads(evidence_path(root, 'summary.json').read_bytes()))
        manifest_sha = digest(manifest)
        self._call(row, '/student/sync/manifest', {'manifest': manifest})
        status = self._call(row, '/student/sync/status', method='GET')
        if status.get('receipt'):
            row = self.journal.update(key, receipt=status['receipt'])
            cleanup_received(self.journal, self.base, row)
            return
        frontiers = {i['id']: i for i in status.get('files', [])}
        for item in manifest['items']:
            if item['status'] != 'present':
                continue
            frontier = frontiers.get(item['id'], {})
            if frontier.get('complete'):
                continue
            path = evidence_path(root, item['relative_path'])
            if file_hash(path) != item['sha256']:
                raise ValueError('local_evidence_changed')
            offset = frontier.get('received_bytes', 0)
            if type(offset) is not int or not 0 <= offset <= item['size']:
                raise ValueError('invalid_upload_frontier')
            with path.open('rb') as handle:
                handle.seek(offset)
                data = handle.read(256*1024)
            reply = self._call(row, '/student/sync/files/'+item['id']+'/chunks',
                {'manifest_sha256': manifest_sha, 'offset': offset, 'data_base64': base64.b64encode(data).decode('ascii')})
            if reply.get('item_id') != item['id'] or reply.get('received_bytes') != offset+len(data):
                raise ValueError('invalid_upload_acknowledgement')
            # Still at most one chunk per iteration, but do not leave the last
            # successful upload waiting for another worker tick before completion.
            if reply.get('complete') is True and all(
                    other['id'] == item['id'] or frontiers.get(other['id'], {}).get('complete')
                    for other in manifest['items'] if other['status'] == 'present'):
                break
            return  # interruption resumes the server frontier
        if any(i['required'] and i['status'] != 'present' for i in manifest['items']):
            self.journal.update(key, sync_status='needs_attention', error='required_material_missing')
            self.next_retry[key] = self.clock()+5.
            return
        self.journal.update(key, sync_status='verifying')
        response = self._call(row, '/student/sync/complete', {'manifest_sha256': manifest_sha})
        row = self.journal.update(key, receipt=response.get('receipt'))
        cleanup_received(self.journal, self.base, row)

    def _run(self):
        while not self.stop_event.wait(.2):
            for row in self.journal.attempts():
                if self.stop_event.is_set():
                    return
                key = 'attempt:'+row['attempt_id']
                if self.clock() < self.next_retry.get(key, 0):
                    continue
                try:
                    self.once(row)
                    self.failures[key] = 0
                except Exception as error:
                    count = self.failures.get(key, 0)+1
                    self.failures[key] = count
                    network = isinstance(error, ConnectedError) and str(error) == 'connection_failed'
                    transient = network or (isinstance(error, ConnectedError) and str(error) == 'server_unavailable')
                    self.next_retry[key] = self.clock()+min(60., 2**min(count, 6)) if transient else float('inf')
                    safe = {'connection_failed','server_unavailable','invalid_credential','invalid_device','manifest_incomplete',
                            'checksum_mismatch','invalid_manifest','invalid_file_type','file_conflict','record_conflict','bundle_frozen',
                            'receipt_incomplete','completion_conflict','request_rejected','invalid_response'}
                    code = str(error) if isinstance(error, ConnectedError) and str(error) in safe else 'local_evidence_requires_attention'
                    if isinstance(error, ValueError) and str(error) in {'journal_record_too_large','journal_partial_record',
                            'local_evidence_changed','receipt_identity_mismatch','required_material_missing','session_identity_mismatch'}:
                        code = str(error)
                    self.journal.update(key, sync_status='offline' if network else 'retrying' if transient else 'needs_attention', error=code)
