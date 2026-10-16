export interface EventSnapshotState {status:'pending'|'available'|'unavailable'|'disabled'|'not_applicable';item_id?:string|null;reason?:string|null;}
export type Presence = 'online' | 'offline' | 'reconnecting';
export interface LiveEvent {event_id: string; event_type: string; timestamp?: string; duration_seconds?: number; category: 'behavioral' | 'technical'; sequence?: number; snapshot?: EventSnapshotState; audio?: EventSnapshotState;}
export interface LiveStatus {
  sequence: number; state: 'preparation' | 'running' | 'paused' | 'ended'; elapsed_seconds: number;
  remaining_seconds: number; duration_seconds: number; answered: number | null; total: number | null;
  monitoring_healthy: boolean; pause_reasons: string[]; screen_consent?: boolean;
  monitoring_outage: {outage_id: string; duration_seconds: number; healthy: boolean; recovery_required: boolean} | null;
  display: {count: number | null; incident_id: string | null; ready: boolean; calibration_ready: boolean; approval_required: boolean};
}
export interface LiveStudent {
  attempt_id: string; session_id: string | null; student: {full_name: string; group: string; student_id: string};
  presence: Presence; last_contact_at: string | null; status: LiveStatus | null; events: LiveEvent[];
  unreviewed_count: number; capabilities: {commands: boolean; view: boolean};
  preparation_deadline?: string|null; lifecycle?: string; start_authorized?: boolean;
  restart_recovery?: {interruption_id?:string|null;grant_id?:string|null;state?:string}|null;
}
export function mayExtendPreparation(student:LiveStudent) {return student.start_authorized===false&&['admitted','preparation_expired'].includes(student.lifecycle??'');}
export function mayAuthorizeRestart(student:LiveStudent) {return student.lifecycle==='interrupted'&&student.restart_recovery?.state==='pending'&&!!student.restart_recovery.interruption_id&&!student.restart_recovery.grant_id;}
export type CommandType = 'monitoring_policy' | 'warning' | 'pause' | 'resume' | 'end' | 'add_time' | 'monitoring_recovery' | 'display_recovery';
export interface LiveCommand {command_id: string; attempt_id: string; command_type: CommandType; payload: Record<string,unknown>; created_at: string; expires_at: string; status: 'sent'|'delivered'|'applied'|'rejected'|'not_delivered'|'execution_unconfirmed'; result: Record<string,unknown> | null;}
export interface ViewerLease {viewer_id: string; attempt_id: string; session_id: string; expires_at: string; limits: Record<string,number>;}
export function socketUrl(path: string, base = location.href) {const url = new URL(path, base); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'; return url.toString();}
export function screenOnlyOffer(sdp:unknown):sdp is string {return typeof sdp==='string'&&sdp.length<=65536&&/^m=application /m.test(sdp)&&!/^m=(audio|video) /m.test(sdp);}
export function mergeEvents(old: LiveEvent[], next: LiveEvent[]): LiveEvent[] {
  const values = new Map(old.map(e => [e.event_id, e]));
  for (const event of next) values.set(event.event_id, {...event,audio:event.audio??values.get(event.event_id)?.audio,snapshot:event.snapshot??values.get(event.event_id)?.snapshot});
  return [...values.values()].sort((a,b) => (a.timestamp ?? '').localeCompare(b.timestamp ?? '') || (a.sequence ?? 0)-(b.sequence ?? 0)).slice(-100);
}
export function mergeCommands(old: LiveCommand[], next: LiveCommand[]): LiveCommand[] {
  const rank={sent:0,delivered:1,execution_unconfirmed:2,not_delivered:3,rejected:3,applied:4};
  const values = new Map(old.map(c => [c.command_id,c]));
  for (const command of next) {const previous=values.get(command.command_id);if(!previous||rank[command.status]>=rank[previous.status])values.set(command.command_id, command);}
  return [...values.values()].sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,100);
}
export function commandAllowed(student: LiveStudent, type: CommandType, connected: boolean): boolean {
  const s=student.status;
  if (!connected || student.presence !== 'online' || !student.capabilities?.commands || !s || !['running','paused'].includes(s.state)) return false;
  if (type==='monitoring_recovery') return !!s.monitoring_outage?.healthy && s.monitoring_outage.recovery_required;
  if (type==='display_recovery') return !!s.display?.incident_id && s.display.count===1 && s.display.ready && s.display.calibration_ready && s.display.approval_required;
  if (type==='resume') return s.pause_reasons.some(reason=>reason==='teacher' || reason==='teacher_pause');
  if (type==='pause') return !s.pause_reasons.some(reason=>reason==='teacher' || reason==='teacher_pause');
  return true;
}
export function timerText(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  const value=Math.max(0,Math.ceil(seconds)); return `${Math.floor(value/60)}:${String(value%60).padStart(2,'0')}`;
}
