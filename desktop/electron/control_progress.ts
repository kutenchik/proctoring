import type { ControlChallenge, ControlReceipt, LeaseChallenge } from '../shared/contracts';

export function validLeaseChallenge(value: unknown): value is LeaseChallenge {
  if (!value || typeof value !== 'object') return false;
  const c = value as LeaseChallenge;
  return /^[a-f0-9]{32}$/.test(c.lease_id) && /^[a-f0-9]{32}$/.test(c.nonce) &&
    Number.isSafeInteger(c.sequence) && c.sequence > 0;
}
/** Polling/preview never renews this one-use, painted-presentation challenge. */
export class ControlProgress {
  private pending?: { challenge: ControlChallenge; issued: number; sent: number; inFlight: boolean };
  private consumed = '';
  private renderGeneration = 0;
  private mainSequence = 0;
  constructor(private now = () => performance.now()) {}
  offer(lease: LeaseChallenge, snapshot: number, session: string | null): ControlChallenge | null {
    if (!validLeaseChallenge(lease) || this.key(lease) === this.consumed) return null;
    if (this.pending && this.key(this.pending.challenge) === this.key(lease)) {
      const changed = this.pending.challenge.session_id !== session;
      if (changed) this.pending.challenge = { ...lease, required_snapshot_seq: snapshot, session_id: session };
      if (this.pending.inFlight || (!changed && this.now() - this.pending.sent < 300)) return null;
      this.pending.sent = this.now();
      return this.pending.challenge; // Resending never refreshes issue time.
    }
    const challenge = { ...lease, required_snapshot_seq: snapshot, session_id: session };
    this.pending = { challenge, issued: this.now(), sent: this.now(), inFlight: false };
    return challenge;
  }
  accept(value: unknown, session: string | null): (LeaseChallenge & { main_sequence: number }) | null {
    if (!validLeaseChallenge(value) || !this.pending || this.pending.inFlight) return null;
    const r = value as ControlReceipt, p = this.pending;
    if (Object.keys(r).sort().join(',') !== 'lease_id,nonce,render_generation,sequence,session_id,snapshot_seq' ||
        this.key(r) !== this.key(p.challenge) || r.session_id !== session || r.session_id !== p.challenge.session_id ||
        !Number.isSafeInteger(r.snapshot_seq) || r.snapshot_seq < p.challenge.required_snapshot_seq ||
        !Number.isSafeInteger(r.render_generation) || r.render_generation <= this.renderGeneration ||
        this.now() - p.issued > 1500) return null;
    this.pending.inFlight = true;
    this.renderGeneration = r.render_generation;
    return { lease_id: r.lease_id, sequence: r.sequence, nonce: r.nonce, main_sequence: ++this.mainSequence };
  }
  confirm(lease: LeaseChallenge, accepted: boolean): void {
    if (accepted) this.consumed = this.key(lease);
    if (this.pending && this.key(this.pending.challenge) === this.key(lease)) {
      if (accepted) this.pending = undefined;
      else this.pending.inFlight = false;
    }
  }
  rendererReplaced(): void { this.renderGeneration = 0; }
  private key(c: LeaseChallenge): string { return `${c.lease_id}:${c.sequence}:${c.nonce}`; }
}
