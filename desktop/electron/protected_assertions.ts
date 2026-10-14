/** Native suppression alone is insufficient: inspect actual target delivery too. */
export function assertSuppressedProbe(eventType: string, code: string,
  events: { event_type: string; details?: { suppressed?: boolean } }[], probe: Record<string, number>): void {
  if (!events.some(event => event.event_type === eventType && event.details?.suppressed === true)) throw new Error('Native suppression event missing');
  if ((probe[code] ?? 0) !== 0) throw new Error(`Suppressed ${code} reached the owned web input`);
}

export function assertOrdinaryInputProbe(code: string, probe: any): void {
  const events = probe.events?.filter((event: any) => event.code === code) ?? [];
  if (probe.counts?.[code] !== 1 || probe.ups?.[code] !== 1 || events.length !== 2 ||
      events.some((event: any) => event.ctrl || event.shift || event.alt || event.meta || event.repeat)) {
    throw new Error(`Ordinary native ${code} down/up without modifiers was not confirmed: ${JSON.stringify(probe)}`);
  }
}

/** A failed input/cleanup check must prevent every subsequent arm. */
export async function runProtectedCheck(name: string, action: () => Promise<string | void>,
  cleanup: () => Promise<void>, record: (name: string, passed: boolean, detail: string) => void): Promise<void> {
  let detail = 'Native owned protected fixture passed', failure: string | undefined;
  try { detail = await action() || detail; } catch (error) { failure = String(error); }
  try { await cleanup(); } catch (error) { failure = `${failure ? failure + '; ' : ''}Cleanup failed: ${String(error)}`; }
  record(name, !failure, failure ?? detail);
  if (failure) throw new Error(failure);
}

/** Require the intended failure, not an unrelated emergency/maximum release. */
export function assertControlLossRelease(state: any): number {
  const native = state.native;
  if (state.protection?.state !== 'fault') throw new Error('Lost-control release must remain a public protection fault');
  if (native?.reason !== 'control_progress_lost') throw new Error(`Expected lost-control release, observed ${native?.reason}`);
  const released = native.released_at, confirmed = native.control_confirmed_at;
  const deadline = state.protection_policy?.heartbeat_timeout_seconds;
  if (![released, confirmed, deadline].every(value => typeof value === 'number' && Number.isFinite(value)) || deadline <= 0) {
    throw new Error('Native release/progress timestamps or configured heartbeat missing');
  }
  const elapsed = released - confirmed;
  if (elapsed < 0 || elapsed > deadline + 1) throw new Error(`Lost-control release exceeded configured heartbeat + 1s allowance: ${elapsed}s`);
  return elapsed;
}

export function assertNormalRelease(state: any, reason: string): void {
  if (state.protection?.state !== 'released' || state.protection?.reason !== reason ||
      state.native?.reason !== reason || ['armed', 'blocking_enabled', 'hook_installed', 'hotkey_registered'].some(key => state.native?.[key] !== false)) {
    throw new Error(`Normal release was not consistently acknowledged: ${JSON.stringify({ protection: state.protection, native: state.native })}`);
  }
}

/** A foreign process must actually gain foreground; a refused focus request proves nothing. */
export function foregroundRecoveryBound(state: any): { native_seconds: number; poll_seconds: number; scheduler_seconds: number; total_seconds: number } {
  const poll = state.protection_policy?.foreground_poll_ms;
  if (!Number.isFinite(poll) || poll <= 0 || poll > 1000) throw new Error('Configured native foreground polling bound is missing or invalid');
  return { native_seconds: 1, poll_seconds: poll / 1000, scheduler_seconds: .4, total_seconds: 1 + poll / 1000 + .4 };
}

export function assertCrossProcessForegroundRecovery(state: any, examPid: number, foreignPid: number, foreignHwnd: string): { outcome: 'restored' | 'terminal_failure'; elapsed_seconds: number; bound: ReturnType<typeof foregroundRecoveryBound> } {
  const observation = state.foreground_observation;
  const validPid = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
  const hwnd = (value: unknown) => typeof value === 'string' && /^0x[0-9a-f]+$/i.test(value) ? BigInt(value) : null;
  if (!validPid(examPid) || !validPid(foreignPid) || examPid === foreignPid ||
      observation?.target?.pid !== foreignPid || hwnd(observation?.target?.hwnd) !== hwnd(foreignHwnd) ||
      hwnd(foreignHwnd) === null || hwnd(foreignHwnd) === 0n || !/^[1-9][0-9]*$/.test(observation?.target?.created ?? '')) {
    throw new Error('Separate owned process/HWND/creation identity was not confirmed');
  }
  const samples = observation.samples;
  if (!Array.isArray(samples) || !samples.length || !Number.isFinite(observation.started_at) || !Number.isFinite(observation.ended_at) || observation.ended_at <= observation.started_at ||
      samples.some((sample, i) => !Number.isFinite(sample.at) || sample.at < observation.started_at || sample.at > observation.ended_at ||
        (i > 0 && sample.at < samples[i - 1].at) || !['exam', 'foreign', 'other', 'none'].includes(sample.kind))) {
    throw new Error('Native foreground transition measurements are incomplete');
  }
  const firstForeign = samples.findIndex(sample => sample.kind === 'foreign' && hwnd(sample.hwnd) === hwnd(foreignHwnd));
  if (firstForeign < 0) throw new Error('NOT RUN: Windows did not grant the owned foreign process foreground during observation');
  const began = samples[firstForeign].at;
  const native = state.native;
  // Native policy is 1.0s. Add its configured poll interval and an explicit
  // 0.4s scheduling allowance (1.5s total for default 100ms polling), never
  // a maximum-lease, generic release or cleanup-induced apparent success.
  const bound = foregroundRecoveryBound(state);
  const withinBound = (at: number) => Number.isFinite(at) && at >= began && at <= observation.ended_at && at - began <= bound.total_seconds;
  if (native?.reason === 'foreground_containment_failed') {
    if (state.protection?.state !== 'fault' || state.protection?.reason !== 'foreground_containment_failed' || !withinBound(native.released_at) ||
        ['armed', 'blocking_enabled', 'hook_installed', 'hotkey_registered'].some(key => native[key] !== false)) {
      throw new Error('Persistent foreign foreground did not produce a bounded confirmed terminal failure');
    }
    return { outcome: 'terminal_failure', elapsed_seconds: native.released_at - began, bound };
  }
  const regained = samples.slice(firstForeign + 1).find(sample => sample.kind === 'exam');
  if (!regained || !withinBound(regained.at) || samples.at(-1)?.kind !== 'exam' ||
      state.protection?.state !== 'active' || state.protection?.enabled !== true || native?.armed !== true || native?.blocking_enabled !== true) {
    throw new Error('Foreign foreground neither restored promptly nor caused the specific bounded terminal failure');
  }
  return { outcome: 'restored', elapsed_seconds: regained.at - began, bound };
}

export function assertSuspendedOwnerDeath(before: any, result: any, after: any): void {
  if (before.native?.armed !== true || before.native?.blocking_enabled !== true || before.helper_alive !== true) {
    throw new Error('Suspension did not start with a live protected owner');
  }
  // audit.suspend_helper returns success only after NtSuspendProcess succeeded
  // and this exact retained owner died, before its failure-cleanup finally.
  // A suspended process cannot handle emergency keys or expire its own lease.
  if (result.result?.termination_confirmed !== true || result.result?.helper_pid !== before.helper_pid ||
      after.helper_pid !== before.helper_pid || after.helper_created !== before.helper_created || after.helper_alive !== false ||
      after.native?.termination_confirmed !== true) throw new Error('Suspended original hook-owner death was not confirmed');
  if (after.native?.reason !== before.native?.reason || !['helper_exited', 'helper_channel_closed'].includes(after.protection?.reason)) {
    throw new Error('Observed another release instead of suspended-owner termination');
  }
}
