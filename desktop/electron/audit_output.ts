import type { Writable } from 'node:stream';

/** Output is part of the audit's observed lifetime. Losing it aborts, not passes. */
export class AuditOutput {
  private first?: string;
  private pending = new Set<(error: Error) => void>();
  constructor(private stdout: Writable, private stderr: Writable, private onFailure: (code: string) => void) {
    stdout.on('error', this.error); stderr.on('error', this.error);
    stdout.on('close', this.closed); stderr.on('close', this.closed);
  }
  private error = (error: NodeJS.ErrnoException) => this.fail(error.code === 'EPIPE' ? 'audit_output_epipe' : 'audit_output_error');
  private closed = () => this.fail('audit_output_closed');
  private fail(code: string): void {
    if (this.first) return;
    this.first = code;
    for (const reject of this.pending) reject(new Error(code));
    this.pending.clear();
    this.onFailure(code);
  }
  get failure(): string | undefined { return this.first; }
  assertHealthy(): void { if (this.first) throw new Error(this.first); }
  async write(value: unknown): Promise<void> {
    this.assertHealthy();
    if (this.stdout.destroyed || !this.stdout.writable) { this.closed(); this.assertHealthy(); }
    await new Promise<void>((resolve, reject) => {
      this.pending.add(reject);
      try {
        this.stdout.write(JSON.stringify(value) + '\n', error => {
          this.pending.delete(reject);
          if (error) { this.error(error); reject(new Error(this.first)); }
          else if (this.first) reject(new Error(this.first)); else resolve();
        });
      } catch (error) { this.pending.delete(reject); this.error(error as NodeJS.ErrnoException); reject(new Error(this.first)); }
    });
  }
  // Keep error handlers attached until process exit: late errors on an already
  // failed pipe must not reopen Electron's uncaught-exception modal during cleanup.
}
