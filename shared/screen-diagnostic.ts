import { validCaptureGeometry, type CaptureGeometryDiagnostic } from './screen-geometry';
import { validStreamTrace, type StreamTraceSnapshot } from './stream-trace';
/** Closed vocabulary: never copy exception text, URLs, SDP or capabilities. */
export const SCREEN_CODES = [
  'unknown_failure','capture_unavailable','capture_bitmap_invalid','capture_mask_invalid',
  'single_display_required','privacy_mask_unavailable','capture_geometry_changed','monitor_capture_unavailable',
  'mask_query_failed','monitor_capture_failed','image_encode_failed','owner_destroyed',
  'session_not_active','authorization_ended','authorization_expired','consent_lost','backend_disconnected',
  'control_disconnected','host_channel_unavailable','invalid_host_message','invalid_stream_message',
  'invalid_stream_ready','invalid_stream_renewal','stream_authorization_ended','stream_network_error',
  'stream_disconnected','frame_delivery_unavailable','stopped','viewer_changed','viewer_switched',
  'viewer_replaced','teacher_stopped','session_ended','application_shutdown','display_changed','student_offline',
  'live_queue_full','disconnected','direct_timeout','direct_failed','direct_renderer_unavailable',
  'direct_start_failed','direct_unavailable','rtc_channel_closed','rtc_connection_failed','rtc_operation_failed',
  'socket_cleanup_failed','rtc_cleanup_failed','diagnostic_delivery_failed','stream_send_failed',
  'invalid_credential','invalid_live_auth','invalid_live_message','invalid_message','message_limit','message_rate',
  'origin_rejected','connection_replaced','frame_limit','invalid_frame','invalid_frame_ack','invalid_quality',
  'invalid_signal','invalid_transport','invalid_viewer','login_required','not_found','signal_limit','viewer_expired','viewer_forbidden',
] as const;
export type ScreenCode = typeof SCREEN_CODES[number];
export function screenCode(value: unknown): ScreenCode {
  return typeof value === 'string' && (SCREEN_CODES as readonly string[]).includes(value) ? value as ScreenCode : 'unknown_failure';
}
export interface ScreenDiagnostic {
  timestamp: string; generation: number; viewer_id: string;
  component: 'capture'|'sender'|'stream_socket'|'authorization';
  phase: 'capture'|'stop'; code: ScreenCode; description: string;
  transport: 'direct'|'relay'|null; capture_state: 'in_flight'|'idle';
  viewer_state: 'pending'|'attached'; requested: boolean;
  ws_close_code: number|null; ws_close_reason: ScreenCode|''|'redacted'|null;
  transition: 'lease_revoked'; fallback: ScreenCode|null; secondary: ScreenCode[];
  geometry?: CaptureGeometryDiagnostic;
  delivery_trace?: StreamTraceSnapshot;
}
export function validScreenDiagnostic(v: any): v is ScreenDiagnostic {
  const keys = ['timestamp','generation','viewer_id','component','phase','code','description','transport','capture_state','viewer_state','requested','ws_close_code','ws_close_reason','transition','fallback','secondary'];
  if(v && Object.hasOwn(v,'delivery_trace')) {if(!validStreamTrace(v.delivery_trace))return false;keys.push('delivery_trace');}
  if(v && Object.hasOwn(v,'geometry')) { if(!validCaptureGeometry(v.geometry))return false;keys.push('geometry'); }
  return !!v && typeof v === 'object' && Object.keys(v).length === keys.length && keys.every(k => k in v) &&
    typeof v.timestamp === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(v.timestamp) &&
    Number.isSafeInteger(v.generation) && v.generation >= 0 && typeof v.viewer_id === 'string' && /^[a-f0-9]{32}$/.test(v.viewer_id) &&
    ['capture','sender','stream_socket','authorization'].includes(v.component) && ['capture','stop'].includes(v.phase) &&
    SCREEN_CODES.includes(v.code) && v.description === v.code.replaceAll('_',' ') &&
    [null,'direct','relay'].includes(v.transport) && ['in_flight','idle'].includes(v.capture_state) && ['pending','attached'].includes(v.viewer_state) &&
    typeof v.requested === 'boolean' && (v.ws_close_code === null || Number.isInteger(v.ws_close_code) && v.ws_close_code >= 1000 && v.ws_close_code <= 4999) &&
    (v.ws_close_reason === null || v.ws_close_reason === '' || v.ws_close_reason === 'redacted' || SCREEN_CODES.includes(v.ws_close_reason)) &&
    v.transition === 'lease_revoked' && (v.fallback === null || SCREEN_CODES.includes(v.fallback)) &&
    Array.isArray(v.secondary) && v.secondary.length <= 4 && v.secondary.every((c: any) => SCREEN_CODES.includes(c));
}
