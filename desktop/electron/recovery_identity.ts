import { isDeepStrictEqual } from 'node:util';

/** One baseline for the entire audit, not a fresh baseline in the final reporter. */
export class AuditRunIdentity {
  private baseline?: Record<string, unknown>;
  private changed = false;
  observe(value: unknown): void {
    const candidate = value as Record<string, unknown> | null;
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate) ||
        typeof candidate.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(candidate.fingerprint) ||
        typeof candidate.host_executable !== 'string' || !candidate.host_executable ||
        !candidate.machine || !candidate.runtime || !candidate.protection_policy) {
      this.changed = true;
      throw new Error('Native audit identity is missing or malformed');
    }
    if (this.changed) throw new Error('Native audit identity changed earlier in this run');
    if (!this.baseline) this.baseline = structuredClone(candidate);
    else if (!isDeepStrictEqual(this.baseline, candidate)) {
      this.changed = true;
      throw new Error('Machine, policy or source/package identity changed during this audit');
    }
  }
  get initial(): Record<string, unknown> | null { return this.baseline ? structuredClone(this.baseline) : null; }
  get stable(): boolean { return !!this.baseline && !this.changed; }
}
