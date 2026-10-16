import { mkdirSync, writeFileSync, copyFileSync, statSync, renameSync } from 'node:fs';
import path from 'node:path';

const events = new Set(['supervisor_started', 'backend_spawned', 'backend_bound', 'backend_ready',
  'camera_received', 'camera_opening', 'camera_started', 'camera_failed', 'camera_cleanup_failed',
  'request_failed', 'backend_transport_closed', 'backend_shutdown', 'backend_exited',
  'supervisor_draining', 'supervisor_forced', 'ownership_failed']);
const classifications = new Set(['runtime', 'value', 'os', 'memory', 'other']);
type Entry = { event: string; at: string; code?: number; windowsStatus?: string; classification?: string };

/** Fixed-schema local metadata only. Never accepts error messages or IPC bodies. */
export class Lifecycle {
  private tail: Entry[] = [];
  private first?: { reason: string; at: string; phase?: string; request?: string; response?: string; cameraOperation?: number };
  private phase?: string;
  private request?: string;
  private response?: string;
  private successfulRequest?: string;
  private cameraOperation = 0;
  private buffer = '';
  private dropping = false;
  constructor(private file?: string) {
    if (file) {
      try { if (statSync(file).size <= 65536) copyFileSync(file, `${file}.previous`); } catch { /* First launch or inaccessible storage. */ }
    }
  }
  sent(command: string): void { this.request = command; if (command === 'camera.start') { this.cameraOperation++; this.record('camera_requested'); } }
  written(command: string): void { this.successfulRequest = command; }
  received(command: string): void { this.response = command; }
  fail(reason: string): void {
    this.first ??= { reason, at: new Date().toISOString(), phase: this.phase, request: this.request,
      response: this.response, cameraOperation: this.cameraOperation || undefined };
    this.flush();
  }
  record(event: string, code?: number, classification?: string): void {
    this.phase = event;
    this.tail.push({ event, at: new Date().toISOString(), ...(Number.isInteger(code) && code! >= -(2**31) && code! <= 2**32-1 ? { code,
      windowsStatus: `0x${(code! >>> 0).toString(16).padStart(8, '0')}` } : {}),
      ...(classification && classifications.has(classification) ? { classification } : {}) });
    this.tail = this.tail.slice(-32); this.flush();
  }
  stderr(chunk: Buffer): void {
    // Parse bounded ASCII marker lines across chunks, discard all other stderr.
    for (const byte of chunk) {
      if (byte === 10) {
        if (!this.dropping && this.buffer.startsWith('PROCTORING_LIFECYCLE:')) {
          try {
            const value = JSON.parse(this.buffer.slice(21));
            if (events.has(value.event)) {
              this.record(value.event, typeof value.code === 'number' ? value.code : undefined, value.classification);
              if (['camera_failed', 'request_failed', 'ownership_failed'].includes(value.event)) this.fail(value.event);
              if (value.event === 'backend_exited' && typeof value.code === 'number' && value.code !== 0) this.fail('backend_exited');
            }
          } catch { /* Malformed/untrusted diagnostics cannot affect control. */ }
        }
        this.buffer = ''; this.dropping = false;
      } else if (!this.dropping) {
        if (this.buffer.length >= 512) { this.buffer = ''; this.dropping = true; }
        else this.buffer += String.fromCharCode(byte);
      }
    }
  }
  snapshot() { return { version: 1, firstFailure: this.first, lastRequest: this.request,
    lastSuccessfulRequest: this.successfulRequest,
    lastResponse: this.response, cameraOperation: this.cameraOperation || undefined, transitions: [...this.tail] }; }
  private flush(): void {
    if (!this.file) return;
    try {
      mkdirSync(path.dirname(this.file), { recursive: true });
      writeFileSync(`${this.file}.tmp`, JSON.stringify(this.snapshot()), { mode: 0o600 });
      renameSync(`${this.file}.tmp`, this.file);
    }
    catch { /* Diagnostic storage failure must not interfere with release. */ }
  }
}
