/** Fence asynchronous resume replies against a newer presentation loss. */
export class PresentationGate {
  lost = false;
  private generation = 0;
  private synchronizing: number | null = null;
  lose(): boolean {
    // Repeated lease ticks need no new backend command. A new loss during an
    // outstanding sync must invalidate that sync and enqueue another pause.
    if (this.lost && this.synchronizing !== this.generation) return false;
    this.lost = true;
    this.generation += 1;
    return true;
  }
  beginSync(): number | null {
    if (this.synchronizing !== null) return null;
    this.synchronizing = this.generation;
    return this.generation;
  }
  finishSync(generation: number, success: boolean): boolean {
    this.synchronizing = null;
    if (success && generation === this.generation) { this.lost = false; return true; }
    return false;
  }
}
