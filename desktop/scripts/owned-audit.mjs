// Foreground Node owner: unlike a bare GUI executable in PowerShell, this
// invocation does not return while Electron still depends on its output pipes.
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

export async function runOwnedAudit(executable, args, { cwd, record, signal, onProgress, onStage } = {}) {
  const state = { status: 'running', started_at: new Date().toISOString(), progress: [], stdout_bytes: 0, stderr_bytes: 0,
    exit_code: null, exit_signal: null, cancellation_requested: false };
  const save = () => {
    try { if (record) writeFileSync(record, JSON.stringify(state, null, 2)); }
    catch { state.record_failed = true; }
  };
  const child = spawn(executable, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  state.pid = child.pid ?? null;
  save();
  let pending = '';
  child.stdout.on('data', data => {
    state.stdout_bytes += data.length;
    pending = (pending + data.toString('utf8')).slice(-8192);
    let end;
    while ((end = pending.indexOf('\n')) >= 0) {
      const line = pending.slice(0, end); pending = pending.slice(end + 1);
      try {
        const value = JSON.parse(line);
        if (typeof value.audit_stage === 'string' && /^[a-z_]{1,80}$/.test(value.audit_stage)) {
          state.stage = value.audit_stage; save();
          try { onStage?.(value.audit_stage); } catch { state.record_failed = true; }
        }
        if (typeof value.native_audit === 'string' && /^[a-z_]{1,80}$/.test(value.native_audit) && typeof value.passed === 'boolean') {
          state.progress.push({ name: value.native_audit, passed: value.passed });
          state.progress = state.progress.slice(-32); save();
          try { onProgress?.(value); } catch { state.record_failed = true; }
        }
      } catch { /* Never preserve arbitrary child output. */ }
    }
  });
  child.stderr.on('data', data => { state.stderr_bytes += data.length; });
  const cancel = () => {
    state.cancellation_requested = true; save();
    // Signal output loss to the guarded audit. It releases its exact owners;
    // the launcher neither kills a process tree nor invents a successful exit.
    child.stdout.destroy();
  };
  signal?.addEventListener('abort', cancel, { once: true });
  child.stdout.on('error', cancel);
  child.stderr.on('error', cancel);
  if (signal?.aborted) cancel();
  await new Promise(resolve => {
    child.once('error', () => { state.spawn_failed = true; });
    child.once('close', (code, exitSignal) => { state.exit_code = code; state.exit_signal = exitSignal; resolve(); });
  });
  signal?.removeEventListener('abort', cancel);
  state.status = state.spawn_failed || state.record_failed || state.cancellation_requested || state.exit_code !== 0 ? 'failed' : 'exited';
  state.finished_at = new Date().toISOString(); save();
  return state;
}

