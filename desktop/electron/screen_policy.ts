import type { ScreenFrame } from '../../shared/live-screen';

export interface ScreenLease { viewer_id: string; attempt_id: string; session_id: string; sender_token: string; expires_at: string; lease_seconds: number; server_url: string }
export function streamURL(origin: string): string {
  const u = new URL(origin);
  if (u.username || u.password || u.hash || u.search || !['https:', 'http:'].includes(u.protocol) ||
      (u.protocol === 'http:' && !['127.0.0.1', '[::1]'].includes(u.hostname))) throw new Error('invalid_stream_origin');
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'; u.pathname = '/api/v1/live/stream'; return u.href;
}
export function validLease(v: unknown): v is ScreenLease {
  const l = v as ScreenLease;
  return !!l && [l.viewer_id,l.attempt_id,l.session_id,l.sender_token].every(x => typeof x === 'string' && x.length > 0 && x.length <= 256) &&
    /^session-[a-f0-9]{32}$/.test(l.session_id) && l.lease_seconds > 0 && l.lease_seconds <= 30 && Number.isFinite(Date.parse(l.expires_at)) &&
    typeof l.server_url === 'string';
}
export function captureAllowed(lease: ScreenLease | undefined, state: { consent: boolean; attempt: string | null; session: string | null; active: boolean }, deadline: number, now: number): boolean {
  return !!lease && now < deadline && state.consent && state.active && lease.attempt_id === state.attempt && lease.session_id === state.session;
}
export class CaptureBudget {
  width = 1280; quality = 72; interval = 200;
  private good = 0;
  congested(): void { this.good = 0; this.width = Math.max(800, this.width - 160); this.quality = Math.max(45, this.quality - 8); this.interval = Math.min(500, this.interval + 100); }
  delivered(): void { if (++this.good < 25) return; this.good = 0; this.width = Math.min(1280, this.width + 160); this.quality = Math.min(72, this.quality + 4); this.interval = Math.max(200, this.interval - 100); }
  get degraded(): boolean { return this.width < 1280 || this.interval > 200; }
}
export function safeAcknowledgement(value: unknown, lastSent: number): value is {type: 'frame_ack'; sequence: number} {
  const v = value as {type: string; sequence: number};
  return !!v && v.type === 'frame_ack' && Number.isSafeInteger(v.sequence) && v.sequence >= 0 && v.sequence <= lastSent;
}
export type OutboundFrame = ScreenFrame;
