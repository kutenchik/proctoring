/** Private inherited NDJSON client for the separate no-suppression audit only. */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { StringDecoder } from 'node:string_decoder';
export interface AuditState { protection: { challenge?: { lease_id: string; sequence: number; nonce: string } | null; [key: string]: unknown }; native: Record<string, unknown>; helper_pid: number | null; helper_alive: boolean; backend_pid: number; [key: string]: unknown }
export class AuditClient {
  child: ChildProcessWithoutNullStreams;
  latest?: AuditState;
  private pending = new Map<string, { done: (value: any) => void; timer: NodeJS.Timeout }>();
  private decoder = new StringDecoder('utf8');
  private buffer = '';
  private terminal = false;
  private closing = false;
  private closePromise?: Promise<void>;
  get available(): boolean {
    return !this.terminal && !this.closing && this.child.exitCode === null && this.child.signalCode === null
      && !this.child.stdin.destroyed && !this.child.stdin.writableEnded && this.child.stdin.writable;
  }
  constructor(python: string, args: string[], cwd: string, launchId: string) {
    this.child = spawn(python, args, { cwd, windowsHide: true, stdio: 'pipe', env: { ...process.env,
      PROCTORING_HOST_LAUNCH_ID: launchId, PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' } });
    this.child.stderr.on('data', () => {});
    // Writable errors are emitted even when write() also has an error callback.
    this.child.stdin.on('error', error => this.fail('stdin_error', (error as NodeJS.ErrnoException).code));
    this.child.stdout.on('data', data => {
      if (this.terminal) return;
      this.buffer += this.decoder.write(data);
      if (Buffer.byteLength(this.buffer) > 1024 * 1024) { this.fail('invalid_response'); this.child.stdin.end(); return; }
      let end;
      while ((end = this.buffer.indexOf('\n')) >= 0) {
        const line = this.buffer.slice(0, end); this.buffer = this.buffer.slice(end + 1);
        try {
          const result = JSON.parse(line), request = this.pending.get(result.id);
          if (result.version !== 1 || typeof result.ok !== 'boolean' || !request) continue;
          clearTimeout(request.timer); this.pending.delete(result.id);
          if (result.ok) this.latest = result.result;
          request.done(result);
        } catch { this.fail('invalid_response'); this.child.stdin.end(); return; }
      }
    });
    this.child.on('exit', (code, signal) => this.fail('endpoint_exit', signal || (code === null ? undefined : String(code))));
    this.child.on('error', error => this.fail('endpoint_error', (error as NodeJS.ErrnoException).code));
  }
  private fail(phase: string, code?: string): void {
    if (this.terminal) return;
    this.terminal = true;
    console.error('AUDIT_FIXTURE_DIAGNOSTIC ' + JSON.stringify({ phase, code: /^[A-Za-z0-9_-]{1,40}$/.test(code || '') ? code : 'unknown' }));
    for (const p of this.pending.values()) { clearTimeout(p.timer); p.done({ ok: false, error: { message: 'Audit endpoint unavailable' } }); }
    this.pending.clear();
  }
  raw(command: string, payload: Record<string, unknown> = {}, timeout = 12000): Promise<any> {
    return this.request(command, payload, timeout);
  }
  private request(command: string, payload: Record<string, unknown>, timeout: number, shuttingDown = false): Promise<any> {
    if (this.terminal || (this.closing && !shuttingDown) || this.child.exitCode !== null || this.child.signalCode !== null
      || this.child.stdin.destroyed || this.child.stdin.writableEnded || !this.child.stdin.writable) {
      return Promise.resolve({ ok: false, error: { message: 'Audit endpoint unavailable' } });
    }
    return new Promise(resolve => {
      const id = randomUUID();
      const timer = setTimeout(() => { this.pending.delete(id); resolve({ ok: false, error: { message: 'Audit command timed out' } }); }, timeout);
      this.pending.set(id, { done: resolve, timer });
      try {
        this.child.stdin.write(JSON.stringify({ version: 1, id, command, payload }) + '\n', error => {
          if (error) this.fail('stdin_write', (error as NodeJS.ErrnoException).code);
        });
      } catch (error) { this.fail('stdin_write', (error as NodeJS.ErrnoException).code); }
    });
  }
  async call(command: string, payload: Record<string, unknown> = {}): Promise<AuditState> {
    const result = await this.raw(command, payload);
    if (!result.ok) throw new Error(result.error?.message || 'Audit request failed');
    return result.result;
  }
  close(): Promise<void> {
    if (!this.closePromise) this.closePromise = this.closeOwned();
    return this.closePromise;
  }
  private async closeOwned(): Promise<void> {
    this.closing = true;
    if (this.child.exitCode !== null || this.child.signalCode !== null) return;
    await this.request('shutdown', {}, 3000, true);
    this.child.stdin.end();
    await new Promise<void>(resolve => {
      if (this.child.exitCode !== null || this.child.signalCode !== null) { resolve(); return; }
      const finish = () => { clearTimeout(timer); this.child.removeListener('exit', finish); resolve(); };
      const timer = setTimeout(finish, 8000); this.child.once('exit', finish);
    });
    // Exact child handle only. Helper recovery is independently supervised.
    if (this.child.exitCode === null && this.child.signalCode === null) {
      this.child.kill();
      await new Promise<void>(resolve => {
        if (this.child.exitCode !== null || this.child.signalCode !== null) { resolve(); return; }
        const finish = () => { clearTimeout(timer); this.child.removeListener('exit', finish); resolve(); };
        const timer = setTimeout(finish, 2000); this.child.once('exit', finish);
      });
      if (this.child.exitCode === null && this.child.signalCode === null) throw new Error('Owned audit endpoint cleanup did not finish');
    }
  }
}
