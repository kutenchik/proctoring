// Diagnostic clocks only: no viewer authorization, capture or lifecycle commands.
export class ViewerClock {
  constructor({ overallStart, overallMs, viewerMs = 420000, maxViewers = 3 }) {
    if (![overallStart, overallMs, viewerMs, maxViewers].every(Number.isFinite) || overallMs <= 0 || overallMs > 1800000 || viewerMs <= 0 || maxViewers < 1 || maxViewers > 3) throw Error('Invalid bounds');
    Object.assign(this, { overallStart, overallMs, viewerMs, maxViewers });
    this.viewers = new Map(); this.firstFailure = null;
  }
  sample(now, value) {
    if (now - this.overallStart >= this.overallMs) return { stop: 'overall_deadline' };
    const id = value?.viewer_id;
    if (!id) return { stop: null };
    if (!/^[a-zA-Z0-9_-]{1,128}$/.test(id)) throw Error('Invalid viewer identity');
    let clock = this.viewers.get(id);
    if (!clock) {
      if (this.viewers.size >= this.maxViewers) return { stop: 'viewer_limit' };
      clock = { observedAt: now, firstPresentedAt: null }; this.viewers.set(id, clock);
    }
    // The actual renderer presentation timestamp, never the observer's Start click.
    const first = value.firstPresentedAt;
    if (clock.firstPresentedAt === null && value.frames > 0 && Number.isFinite(first) && first <= now && first >= this.overallStart) clock.firstPresentedAt = first;
    const expectedNetwork = value.expected_network === true && value.reason === 'connection_lost';
    if (value.state === 'unavailable' && !expectedNetwork && !this.firstFailure) this.firstFailure = { at: now, viewer_id: id, reason: value.reason };
    const elapsed = clock.firstPresentedAt === null ? null : now - clock.firstPresentedAt;
    return { stop: this.firstFailure ? 'terminal_failure' : now - clock.observedAt >= this.viewerMs && value.state !== 'stopped' ? 'viewer_deadline' : null,
      viewer_id: id, elapsed_ms: elapsed, idle_complete: elapsed !== null && elapsed >= 30000,
      sustained_time_complete: elapsed !== null && elapsed >= 210000 };
  }
}
