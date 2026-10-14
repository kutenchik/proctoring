import type { BackendState, Command, HostCommand, DisplayGeometry, EvidenceIntent, ExternalIntent } from '../shared/contracts';
import { validLeaseChallenge } from './control_progress';
import { validScreenDiagnostic } from '../../shared/screen-diagnostic';
export const MAX_COMMAND_BYTES = 16 * 1024;
const emptyCommands = new Set(['state.get', 'devices.refresh', 'setup.show', 'camera.start', 'camera.stop', 'audio.start', 'audio.stop', 'audio.calibrate', 'reference.capture', 'calibration.start', 'calibration.cancel', 'exam.start', 'exam.submit', 'report.retry']);
export function validateCommand(command: unknown, payload: unknown, host = false): { command: Command | HostCommand; payload: Record<string, unknown> } {
  if (typeof command !== 'string' || !payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('INVALID_COMMAND');
  const value = payload as Record<string, unknown>;
  if (Buffer.byteLength(JSON.stringify(value), 'utf8') > MAX_COMMAND_BYTES) throw new Error('PAYLOAD_TOO_LARGE');
  const keys = Object.keys(value);
  const only = (...fields: string[]) => keys.length === fields.length && fields.every(field => keys.includes(field));
  const integer = (v: unknown, max = 1000000) => Number.isInteger(v) && Number(v) >= 0 && Number(v) <= max;
  const string = (v: unknown, max = 256) => typeof v === 'string' && v.length <= max && !/[\x00-\x1f\x7f]/.test(v);
  if (['connected.refresh', 'sync.retry', 'sync.background', 'sync.exit'].includes(command) && only()) return { command: command as Command, payload: value };
  if (command === 'connected.verify' && only('server_url') && string(value.server_url, 2048) && String(value.server_url).trim()) return { command, payload: value };
  if (command === 'connected.admit' && only('exam_code', 'full_name', 'group', 'student_id') &&
      [['exam_code', 64], ['full_name', 200], ['group', 128], ['student_id', 128]].every(([key, max]) => string(value[String(key)], Number(max)) && String(value[String(key)]).trim())) return { command, payload: value };
  if (command === 'quiz.answer' && only('question_index', 'option_indices', 'revision') && integer(value.question_index, 10000) && integer(value.revision) &&
      Array.isArray(value.option_indices) && value.option_indices.length <= 100 && new Set(value.option_indices).size === value.option_indices.length && value.option_indices.every(v => integer(v, 1000))) return { command, payload: value };
  if (emptyCommands.has(command) && keys.length === 0) return { command: command as Command, payload: value };
  if (['consent.set','screen.consent'].includes(command) && only('accepted') && typeof value.accepted === 'boolean') return { command: command as Command, payload: value };
  if ((command === 'camera.select' || command === 'microphone.select') && keys.length === 1 &&
      typeof value.key === 'string' && value.key.length > 0 && value.key.length <= 1024 && !/[\x00-\x1f]/.test(value.key)) return { command, payload: value };
  if (command === 'registration.submit' && only('first_name', 'last_name', 'group_id') && ['first_name', 'last_name', 'group_id'].every(k => string(value[k]))) return { command, payload: value };
  if (command === 'calibration.retry' && only('scope') && ['target', 'baseline'].includes(String(value.scope))) return { command, payload: value };
  if (command === 'calibration.presented' && only('token', 'target', host ? 'geometry' : 'geometry_id') && string(value.token, 128) && ['CENTER', 'LEFT', 'RIGHT', 'DOWN'].includes(String(value.target))) {
    if (host) validateGeometry(value.geometry); else if (!string(value.geometry_id, 128)) throw new Error('INVALID_GEOMETRY');
    return { command, payload: value };
  }
  if (command === 'quiz.answer' && only('question_index', 'option_index', 'revision') && integer(value.question_index, 10000) && integer(value.option_index, 1000) && integer(value.revision)) return { command, payload: value };
  if (command === 'quiz.navigate' && only('question_index') && integer(value.question_index, 10000)) return { command, payload: value };
  if (['proctor.pause', 'proctor.resume', 'proctor.end'].includes(command) && only('pin') && typeof value.pin === 'string' && /^[0-9]{4,64}$/.test(value.pin)) return { command: command as Command, payload: value };
  if (command === 'events.get' && only('after', 'limit') && integer(value.after, Number.MAX_SAFE_INTEGER) && integer(value.limit, 100) && Number(value.limit) > 0) return { command, payload: value };
  if (host) {
    if (command === 'live.poll' && only()) return { command, payload: value };
    if (command === 'live.capture' && (only('viewer_id','state','transport','reason') ||
        only('viewer_id','state','transport','reason','diagnostic') && validScreenDiagnostic(value.diagnostic) && value.diagnostic.viewer_id === value.viewer_id &&
        value.reason === value.diagnostic.code && ['stopped','unavailable'].includes(String(value.state))) && string(value.viewer_id,128) &&
        ['stopped','starting','recovering','live','degraded','unavailable'].includes(String(value.state)) &&
        (value.transport === null || ['direct','relay'].includes(String(value.transport))) && string(value.reason,256)) return { command, payload: value };
    if (command === 'host.progress' && only('lease_id', 'sequence', 'nonce', 'main_sequence', 'session_id', 'snapshot_seq') && validLeaseChallenge(value) && integer(value.main_sequence, Number.MAX_SAFE_INTEGER) && Number(value.main_sequence) > 0 &&
        (value.session_id === null || string(value.session_id, 128)) && integer(value.snapshot_seq, Number.MAX_SAFE_INTEGER)) return { command, payload: value };
    if (command === 'host.safety_release' && only('reason') && ['display_geometry_changed', 'host_window_destroyed'].includes(String(value.reason))) return { command, payload: value };
    if (command === 'host.bind' && only('launch_id', 'host_pid', 'windows', 'runtime')) {
      const runtime = value.runtime as Record<string, unknown> | null;
      if (!/^[a-f0-9]{32}$/.test(String(value.launch_id)) || !integer(value.host_pid, 0xffffffff) || Number(value.host_pid) <= 0 ||
          !Array.isArray(value.windows) || value.windows.length < 1 || value.windows.length > 8 ||
          !value.windows.every(w => w && Object.keys(w).sort().join(',') === 'hwnd,role' && /^0x[1-9a-f][a-f0-9]{0,15}$/.test(w.hwnd) && ['exam', 'dialog'].includes(w.role)) ||
          !runtime || Object.keys(runtime).sort().join(',') !== 'app_version,build_id,build_kind,electron_version' ||
          !string(runtime.electron_version, 64) || !string(runtime.app_version, 64) || !['source', 'packaged'].includes(String(runtime.build_kind)) || !/^[a-f0-9]{64}$/.test(String(runtime.build_id))) throw new Error('INVALID_HOST_BINDING');
      return { command, payload: value };
    }
    if (['shutdown', 'emergency.end', 'presentation.lost', 'host.external'].includes(command) && keys.length === 0) return { command: command as HostCommand, payload: value };
    if (command === 'presentation.sync' && only('session_id', 'event_cursor') && (value.session_id === null || string(value.session_id, 128)) && integer(value.event_cursor, Number.MAX_SAFE_INTEGER)) return { command, payload: value };
    if (command === 'geometry.changed' && only('geometry')) { validateGeometry(value.geometry); return { command, payload: value }; }
    if (command === 'host.evidence') { validateEvidence({ ...value, action: 'open' }); return { command, payload: value }; }
  }
  throw new Error('INVALID_COMMAND');
}
export function validateGeometry(value: unknown): DisplayGeometry {
  if (!value || typeof value !== 'object') throw new Error('INVALID_GEOMETRY');
  const g = value as DisplayGeometry;
  if (typeof g.geometry_id !== 'string' || g.geometry_id.length > 128 || typeof g.center_visible !== 'boolean' ||
      ![g.scale_factor, g.zoom_factor].every(n => Number.isFinite(n) && n > 0 && n <= 8) ||
      !g.center_client || ![g.center_client.x, g.center_client.y].every(Number.isFinite)) throw new Error('INVALID_GEOMETRY');
  for (const bounds of [g.content_bounds, g.display_bounds]) if (!bounds || !Object.values(bounds).every(Number.isFinite) || bounds.width <= 0 || bounds.height <= 0) throw new Error('INVALID_GEOMETRY');
  return g;
}
export function validateEvidence(value: unknown): EvidenceIntent {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('INVALID_EVIDENCE');
  const v = value as EvidenceIntent;
  const keys = Object.keys(v);
  if (keys.some(k => !['session_id', 'kind', 'event_id', 'action'].includes(k)) ||
      !/^session-[a-f0-9]{32}$/.test(v.session_id) || !['report', 'snapshot', 'reference'].includes(v.kind) || !['open', 'save'].includes(v.action) ||
      (v.kind === 'snapshot' ? typeof v.event_id !== 'string' || !/^(?:event-[0-9]{1,12}|[a-f0-9-]{1,64})$/i.test(v.event_id) : v.event_id !== undefined)) throw new Error('INVALID_EVIDENCE');
  return v;
}
export function validateExternal(value: unknown): ExternalIntent {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('INVALID_EXTERNAL');
  const v = value as ExternalIntent;
  if (v.action === 'layout') {
    if (Object.keys(v).sort().join(',') !== 'action,bounds,modal,visible' || typeof v.visible !== 'boolean' || typeof v.modal !== 'boolean' ||
        !v.bounds || Object.keys(v.bounds).sort().join(',') !== 'height,width,x,y' || !Object.values(v.bounds).every(n => Number.isFinite(n) && Math.abs(n) <= 20000) || v.bounds.width < 0 || v.bounds.height < 0) throw new Error('INVALID_EXTERNAL');
  } else if (!['status', 'reload', 'focus', 'hide'].includes(v.action) || Object.keys(v).length !== 1) throw new Error('INVALID_EXTERNAL');
  return v;
}
export function trustedRenderer(actualUrl: string, expectedUrl: string): boolean {
  try {
    const actual = new URL(actualUrl), expected = new URL(expectedUrl);
    return actual.protocol === expected.protocol && actual.host === expected.host && actual.pathname === expected.pathname && !actual.username && !actual.password;
  } catch { return false; }
}
export const PRODUCTION_CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
export const DEVELOPMENT_CSP = PRODUCTION_CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
  .replace("connect-src 'none'", "connect-src http://127.0.0.1:5173 ws://127.0.0.1:5173");

export function validateState(input: unknown): BackendState {
  const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
  const text = (v: unknown) => typeof v === 'string' && v.length <= 4096;
  const nullableText = (v: unknown) => v === null || text(v);
  const number = (v: unknown) => typeof v === 'number' && Number.isFinite(v);
  const nullableNumber = (v: unknown) => v === null || number(v);
  if (!object(input)) throw new Error('Invalid state');
  if (input.live_teacher !== undefined) {
    const live = input.live_teacher;
    const onlyKeys = (v:Record<string,unknown>,keys:string[]) => Object.keys(v).every(k => keys.includes(k));
    if (!object(live) || !onlyKeys(live,['connection','error','consent','viewing','messages','display','monitoring_outage','screen_diagnostic']) ||
        (live.screen_diagnostic != null && !validScreenDiagnostic(live.screen_diagnostic)) ||
        !['offline','reconnecting','online'].includes(String(live.connection)) || !nullableText(live.error) ||
        !object(live.consent) || !onlyKeys(live.consent,['accepted','version','acknowledged']) || live.consent.version !== 3 ||
        typeof live.consent.accepted !== 'boolean' || typeof live.consent.acknowledged !== 'boolean' ||
        !object(live.viewing) || !onlyKeys(live.viewing,['viewer_id','state','transport','reason']) ||
        !nullableText(live.viewing.viewer_id) || !nullableText(live.viewing.reason) ||
        !['stopped','starting','recovering','live','degraded','unavailable'].includes(String(live.viewing.state)) ||
        (live.viewing.transport !== null && !['direct','relay'].includes(String(live.viewing.transport))) ||
        !Array.isArray(live.messages) || live.messages.length > 20 || !live.messages.every(m => object(m) &&
          onlyKeys(m,['command_id','teacher_id','text','timestamp']) && ['command_id','teacher_id','text','timestamp'].every(k => text(m[k])) && String(m.text).length <= 400) ||
        !object(live.display) || !onlyKeys(live.display,['count','incident_id','ready','calibration_ready','approval_required']) ||
        !nullableNumber(live.display.count) || !nullableText(live.display.incident_id) ||
        !['ready','calibration_ready','approval_required'].every(k => typeof (live.display as Record<string, unknown>)[k] === 'boolean') ||
        (live.monitoring_outage !== null && (!object(live.monitoring_outage) ||
          !onlyKeys(live.monitoring_outage,['outage_id','duration_seconds','healthy','recovery_required']) ||
          !text(live.monitoring_outage.outage_id) || !number(live.monitoring_outage.duration_seconds) ||
          typeof live.monitoring_outage.healthy !== 'boolean' || typeof live.monitoring_outage.recovery_required !== 'boolean'))) throw new Error('Invalid live teacher state');
  }
  if (input.synchronization !== undefined) {
    const sync = input.synchronization;
    if (!object(sync) || !['offline','pending','uploading','verifying','retrying','needs_attention','fully_synchronized'].includes(String(sync.status)) ||
        !nullableText(sync.error) || !text(sync.phase) || !number(sync.pending_attempts) || !nullableNumber(sync.remaining_seconds) ||
        !nullableText(sync.recovery_state) || !['fully_synchronized','background','can_background','recovery_required'].every(k => typeof sync[k] === 'boolean')) throw new Error('Invalid synchronization state');
  }
  const { config, devices, camera, audio, protection } = input;
  if (input.version !== 1 || !['setup_only', 'exam_workflow'].includes(String(input.mode)) || typeof input.connected !== 'boolean' ||
      typeof input.consent_accepted !== 'boolean' || !['en', 'ru', 'kk'].includes(String(input.language)) ||
      !object(config) || !object(devices) || !object(camera) || !object(audio) || !object(protection) ||
      typeof protection.enabled !== 'boolean' || !text(protection.reason)) throw new Error('Invalid state');
  if (protection.requested !== undefined && typeof protection.requested !== 'boolean') throw new Error('Invalid protection intent');
  if (protection.state !== undefined && !['disabled', 'awaiting_audit', 'preparing', 'arming', 'active', 'releasing', 'released', 'fault'].includes(String(protection.state))) throw new Error('Invalid protection state');
  if (protection.challenge != null && !validLeaseChallenge(protection.challenge)) throw new Error('Invalid protection challenge');
  for (const field of ['audio_exam_enabled', 'remote_enabled', 'external_exam_configured', 'registration_enabled']) {
    if (typeof config[field] !== 'boolean') throw new Error('Invalid config');
  }
  if (!Array.isArray(config.remote_destinations) || config.remote_destinations.length > 4 || !config.remote_destinations.every(text)) throw new Error('Invalid destinations');
  if (typeof devices.scanning !== 'boolean' || !object(devices.errors) || !Object.values(devices.errors).every(text)) throw new Error('Invalid catalog');
  for (const field of ['cameras', 'microphones']) {
    const items = devices[field];
    if (!Array.isArray(items) || items.length > 64 || !items.every(d => object(d) &&
      ['key', 'label', 'name', 'backend', 'details', 'default_target_key'].every(k => text(d[k])) &&
      ['advanced', 'supported', 'ambiguous'].every(k => typeof d[k] === 'boolean'))) throw new Error('Invalid device');
  }
  if (!nullableText(camera.selected_key) || !['not_started', 'opening', 'live', 'stale', 'unavailable', 'stopped'].includes(String(camera.state)) ||
      !nullableText(camera.error) || !number(camera.fps) ||
      !['frame_age_seconds', 'source_width', 'source_height', 'preview_sequence'].every(k => nullableNumber(camera[k]))) throw new Error('Invalid camera');
  if (!nullableText(audio.selected_key) || !text(audio.state) || !nullableText(audio.error) || typeof audio.running !== 'boolean' ||
      !number(audio.processed_level) || !nullableNumber(audio.frame_age_seconds) || !object(audio.check) ||
      !text(audio.check.state) || !text(audio.check.reason) || !number(audio.check.progress)) throw new Error('Invalid audio');
  for (const field of ['gain', 'applied_gain', 'threshold', 'committed_threshold', 'processed_noise', 'processed_speech']) {
    if (audio.check[field] !== undefined && !nullableNumber(audio.check[field])) throw new Error('Invalid audio measurement');
  }
  for (const field of ['threshold_source', 'rejection_code', 'units', 'resolved_device', 'device_key']) {
    if (audio.check[field] !== undefined && !nullableText(audio.check[field])) throw new Error('Invalid audio detail');
  }
  if (audio.check.gain_limited != null && typeof audio.check.gain_limited !== 'boolean') throw new Error('Invalid gain status');
  if (audio.check.stream_format !== undefined && (!object(audio.check.stream_format) ||
      Object.keys(audio.check.stream_format).length > 8 ||
      !Object.values(audio.check.stream_format).every(v => text(v) || number(v)))) throw new Error('Invalid audio format');
  if (!Array.isArray(input.unavailable_actions) || input.unavailable_actions.length > 32 || !input.unavailable_actions.every(text)) throw new Error('Invalid capabilities');
  if (input.mode === 'exam_workflow') {
    if (input.admission !== undefined) {
      const a = input.admission;
      const identity = object(a) ? a.identity : null;
      if (object(a) && a.finish_status !== undefined && !['not_sent', 'pending', 'sent', 'failed'].includes(String(a.finish_status))) throw new Error('Invalid finish status');
      if (!object(a) || typeof a.enabled !== 'boolean' || !text(a.server_url) || !text(a.verified_server) || !nullableText(a.busy) || !nullableText(a.error) ||
          typeof a.admitted !== 'boolean' || typeof a.policy_applied !== 'boolean' || !nullableText(a.attempt_id) || !text(a.exam_title) ||
          !number(a.preparation_remaining_seconds) || !nullableText(a.preparation_deadline) || typeof a.start_authorized !== 'boolean' ||
          (identity !== null && (!object(identity) || !['full_name', 'group', 'student_id'].every(k => text(identity[k]))))) throw new Error('Invalid admission');
    }
    const w = input.workflow;
    if (!object(w) || !object(w.session)) throw new Error('Invalid workflow');
    const session = w.session;
    if (w.version !== 2 || !number(w.revision) || !number(w.snapshot_seq) || !nullableText(w.session_id) || !text(w.config_path) ||
        !['setup', 'calibration', 'ready', 'exam', 'paused', 'summary'].includes(String(w.step)) ||
        !['started', 'ended', 'running', 'monitoring_healthy', 'recovery_pin_required'].every(k => typeof session[k] === 'boolean') ||
        !['elapsed_seconds', 'remaining_seconds', 'duration_seconds'].every(k => number(session[k])) ||
        !Array.isArray(w.session.pause_reasons) || !w.session.pause_reasons.every(text) ||
        !object(w.events) || !number(w.events.cursor) || !Array.isArray(w.events.records) || w.events.records.length > 200 ||
        !w.events.records.every(e => object(e) && text(e.event_id) && text(e.event_type)) ||
        !['registration', 'reference', 'calibration', 'readiness', 'quiz', 'monitoring', 'report'].every(k => object(w[k]))) throw new Error('Invalid workflow');
  }
  return input as unknown as BackendState;
}
