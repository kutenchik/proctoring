/** Stage 1 presentation contract. Python owns all measurement and lifecycle state. */
export const PROTOCOL_VERSION = 1 as const;
export type Locale = 'en' | 'ru' | 'kk';
export type Command = 'state.get' | 'devices.refresh' | 'setup.show' | 'consent.set' | 'camera.select' | 'microphone.select' | 'camera.start' | 'camera.stop' | 'audio.start' | 'audio.stop' | 'audio.calibrate' |
  'connected.verify' | 'connected.admit' | 'connected.refresh' | 'sync.retry' | 'sync.background' | 'sync.exit' | 'screen.consent' |
  'registration.submit' | 'reference.capture' | 'calibration.start' | 'calibration.presented' | 'calibration.cancel' | 'calibration.retry' |
  'exam.start' | 'quiz.answer' | 'quiz.navigate' | 'exam.submit' | 'proctor.pause' | 'proctor.resume' | 'proctor.end' | 'report.retry' | 'events.get';
export type HostCommand = 'shutdown' | 'emergency.end' | 'presentation.lost' | 'presentation.sync' | 'geometry.changed' | 'host.external' | 'host.evidence' | 'host.bind' | 'host.progress' | 'host.safety_release' | 'live.poll' | 'live.capture';
export interface LeaseChallenge { lease_id: string; sequence: number; nonce: string }
export interface ControlChallenge extends LeaseChallenge { required_snapshot_seq: number; session_id: string | null }
export interface ControlReceipt extends LeaseChallenge { snapshot_seq: number; session_id: string | null; render_generation: number }
export interface HostBinding {
  launch_id: string; host_pid: number; windows: { hwnd: string; role: 'exam' | 'dialog' }[];
  runtime: { electron_version: string; app_version: string; build_kind: 'source' | 'packaged'; build_id: string };
}
export interface ProtectionState {
  enabled: boolean; requested?: boolean; reason: string;
  state?: 'disabled' | 'awaiting_audit' | 'preparing' | 'arming' | 'active' | 'releasing' | 'released' | 'fault';
  audit?: { required?: boolean; valid: boolean; message: string; path: string }; challenge?: LeaseChallenge | null;
}
export interface Bounds { x: number; y: number; width: number; height: number }
export interface DisplayGeometry {
  geometry_id: string; content_bounds: Bounds; display_bounds: Bounds; scale_factor: number;
  zoom_factor: number; center_client: { x: number; y: number }; center_visible: boolean;
  fullscreen?: boolean; settled?: boolean;
}
export type ExternalIntent = { action: 'layout'; bounds: Bounds; visible: boolean; modal: boolean } | { action: 'status' | 'reload' | 'focus' | 'hide' };
export interface ExternalStatus { configured: boolean; state: 'idle' | 'loading' | 'ready' | 'blocked' | 'failed' | 'hidden'; visible: boolean; message: string }
export interface EvidenceIntent { session_id: string; kind: 'report' | 'snapshot' | 'reference'; event_id?: string; action: 'open' | 'save' }
export interface EvidenceResult { ok: boolean; cancelled?: boolean; error?: string }
export interface PresentationReceipt { session_id: string | null; event_cursor: number; snapshot_seq: number }
export interface ReviewEvent {
  event_id: string; event_type: string; timestamp?: string; started_at?: string; ended_at?: string | null;
  start_timestamp?: string; activated_timestamp?: string; end_timestamp?: string | null;
  duration_seconds?: number; activity_seconds?: number; confidence?: number | null;
  state?: string; description?: string; snapshot?: string | null; [field: string]: unknown;
}
export interface CalibrationState {
  attempt_id: string; phase: 'idle' | 'awaiting_presentation' | 'preparing' | 'collecting' | 'target_failed' | 'fit_failed' | 'complete';
  target: string; presentation_token: string | null; cue_sequence: number; cue: 'start' | 'complete' | null;
  message: string; accepted_samples: number; required_samples: number; completed_targets: string[];
  alignment: { ready: boolean; reason: string; message: string; progress: number; guide: [number, number, number, number]; [field: string]: unknown };
  ready: boolean; prepare_remaining: number; collection_progress: number; geometry_id: string | null;
  diagnostics: Record<string, unknown>; last_attempt: unknown; retained_attempts: { attempt_id: string; outcome: string }[];
  [field: string]: unknown;
}
export interface WorkflowState {
  version: 2; step: 'setup' | 'calibration' | 'ready' | 'exam' | 'paused' | 'summary'; revision: number; snapshot_seq: number;
  session_id: string | null; config_path: string;
  registration: { enabled: boolean; require_group: boolean; candidate: { first_name: string; last_name: string; group_id: string; full_name?: string; student_id?: string } | null; complete: boolean };
  reference: { advanced?: boolean; enabled: boolean; ready: boolean; can_capture: boolean; status: string };
  calibration: CalibrationState;
  readiness: { ready: boolean; checks: { id: string; status: 'ready' | 'blocked' | 'not_enabled'; message: string; required?: boolean }[] };
  session: { started: boolean; started_at?: string | null; ended: boolean; running: boolean; elapsed_seconds: number; remaining_seconds: number; duration_seconds: number; pause_reasons: string[]; monitoring_healthy: boolean; recovery_pin_required: boolean; end_reason: string | null };
  quiz: { mode: 'native' | 'external'; current_index: number; total: number | null; answered: number | null; revision: number; questions: { id: string; type?: 'single_choice' | 'multiple_choice'; prompt: string; options: string[]; option_ids?: string[] }[]; answers: Record<string, number | number[]> };
  monitoring: { healthy: boolean; reason: string; gaze_direction: string; head_pose: { yaw: number; pitch: number; roll: number } | null; person_count: number | null; phone_visible: boolean | null; latency_ms: { face: number | null; yolo: number | null }; fps: number };
  events: { cursor: number; records: ReviewEvent[] };
  summary: Record<string, unknown> | null;
  report: { status: string; error: string | null; file_name: string; available: boolean };
}
export interface Device {
  key: string; label: string; name: string; backend: string; advanced: boolean;
  supported: boolean; ambiguous: boolean; details: string; default_target_key: string;
}
export interface AudioCheck {
  state: string; reason: string; progress: number; gain?: number | null; applied_gain?: number | null;
  threshold?: number | null; committed_threshold?: number | null; threshold_source?: string | null;
  rejection_code?: string | null; gain_limited?: boolean | null; processed_noise?: number | null;
  processed_speech?: number | null; units?: string | null; resolved_device?: string | null;
  device_key?: string | null; stream_format?: Record<string, string | number>;
}
export interface BackendState {
  live_teacher?: LiveTeacherState;
  admission?: AdmissionState;
  synchronization?: { status: 'offline' | 'pending' | 'uploading' | 'verifying' | 'retrying' | 'needs_attention' | 'fully_synchronized'; error: string | null; phase: string; pending_attempts: number; fully_synchronized: boolean; background: boolean; can_background: boolean; recovery_required: boolean; recovery_state: string | null; remaining_seconds: number | null };
  version: 1; mode: 'setup_only' | 'exam_workflow'; connected: boolean; consent_accepted: boolean;
  language: Locale; protection: ProtectionState;
  config: { audio_exam_enabled: boolean; remote_enabled: boolean; remote_destinations: string[];
    external_exam_configured: boolean; registration_enabled: boolean };
  devices: { scanning: boolean; cameras: Device[]; microphones: Device[]; errors: Record<string, string> };
  camera: { selected_key: string | null; state: 'not_started' | 'opening' | 'live' | 'stale' | 'unavailable' | 'stopped';
    error: string | null; fps: number; frame_age_seconds: number | null; source_width: number | null;
    source_height: number | null; preview_sequence: number | null };
  audio: { selected_key: string | null; state: string; error: string | null; running: boolean;
    processed_level: number; frame_age_seconds: number | null; check: AudioCheck };
  unavailable_actions: string[];
  workflow?: WorkflowState;
}
export interface LiveTeacherState {
  connection: 'offline'|'reconnecting'|'online'; error: string|null;
  advanced?: Record<string,string>;
  consent: {accepted:boolean;version:3|4|5;acknowledged:boolean;features?:string[]};
  viewing: {viewer_id:string|null;state:'stopped'|'starting'|'recovering'|'live'|'degraded'|'unavailable';transport:'direct'|'relay'|null;reason:string|null};
  screen_diagnostic?: import('../../shared/screen-diagnostic').ScreenDiagnostic|null;
  messages: {command_id:string;teacher_id:string;text:string;timestamp:string}[];
  display: {count:number|null;incident_id:string|null;ready:boolean;calibration_ready:boolean;approval_required:boolean};
  monitoring_outage: {outage_id:string;duration_seconds:number;healthy:boolean;recovery_required:boolean}|null;
}
export interface PreviewFrame {
  sequence: number; captured_at: number; source_width: number; source_height: number;
  width: number; height: number; mime: 'image/jpeg'; jpeg_base64: string; overlays: unknown[];
}
export interface AdmissionState {
  pin_request?: number; pin_status?: 'pending'|'authorized'|'rejected'|null;
  enabled: boolean; server_url: string; verified_server: string; busy: string | null;
  error: string | null; admitted: boolean; policy_applied: boolean; attempt_id: string | null;
  exam_title: string; preparation_remaining_seconds: number; preparation_deadline: string | null;
  identity: {full_name: string; group: string; student_id: string} | null; start_authorized: boolean;
  finish_status?: 'not_sent' | 'pending' | 'sent' | 'failed';
}
export type CommandResult = { version: 1; id: string; ok: true; result: BackendState; data?: unknown } |
  { version: 1; id: string; ok: false; error: { code: string; message: string } };
export interface ConnectionStatus { state: 'connecting' | 'connected' | 'disconnected' | 'fixture'; reason?: string }
export interface DesktopAPI {
  onControlChallenge(listener: (challenge: ControlChallenge) => void): () => void;
  acknowledgeControlProgress(receipt: ControlReceipt): Promise<{ accepted: boolean }>;
  readonly mode: 'live' | 'fixture';
  command(command: Command, payload?: Record<string, unknown>): Promise<CommandResult>;
  connection(): Promise<ConnectionStatus>;
  preview(): Promise<PreviewFrame | null>;
  reconnect(): Promise<ConnectionStatus>;
  geometry(): Promise<DisplayGeometry>;
  external(intent: ExternalIntent): Promise<ExternalStatus>;
  evidence(intent: EvidenceIntent): Promise<EvidenceResult>;
  onEndRequested(listener: () => void): () => void;
  acknowledgePresentation(receipt: PresentationReceipt): Promise<CommandResult>;
}
declare global { interface Window { proctoring?: DesktopAPI } }
