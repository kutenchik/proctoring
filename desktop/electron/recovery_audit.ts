import { app, BrowserWindow } from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import path from 'node:path';
import { nativeHandleHex } from './host_binding';
import { ensureRuntimeConfig, resolveRuntime } from './runtime';
import { AuditRunIdentity } from './recovery_identity';
import { AuditOutput } from './audit_output';

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
export class Fixture {
  child: ChildProcess; ready: Promise<any>; binding: any; latest: any;
  private token = randomBytes(32).toString('hex');
  private requests = new Map<string, { resolve: (v: any) => void; timer: NodeJS.Timeout }>();
  private closing?: Promise<void>;
  private diagnostics: string[] = [];
  constructor(output: string, config: string, mode: 'recovery' | 'protected' = 'recovery', recoveryReport = '') {
    const flag = mode === 'protected' ? '--protected-fixture' : '--recovery-fixture';
    const args = app.isPackaged ? [flag] : [app.getAppPath(), flag];
    this.child = spawn(process.execPath, args, { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe', 'ipc'], env: { ...process.env,
      PROCTORING_AUDIT_FIXTURE_TOKEN: this.token, PROCTORING_AUDIT_OUTPUT: output, PROCTORING_AUDIT_CONFIG: config,
      PROCTORING_RECOVERY_REPORT: recoveryReport } });
    let stderr = '';
    this.child.stderr?.on('data', data => {
      // Retain only fixed diagnostic codes, never raw stderr, paths or payloads.
      stderr = (stderr + data.toString('utf8')).slice(-8192);
      let end;
      while ((end = stderr.indexOf('\n')) >= 0) {
        const line = stderr.slice(0, end); stderr = stderr.slice(end + 1);
        if (!line.startsWith('AUDIT_FIXTURE_DIAGNOSTIC ')) continue;
        try {
          const value = JSON.parse(line.slice('AUDIT_FIXTURE_DIAGNOSTIC '.length));
          if (/^[a-z_]{1,40}$/.test(value.phase) && /^[A-Za-z0-9_-]{1,40}$/.test(value.code)) {
            this.diagnostics.push(`${value.phase}:${value.code}`); this.diagnostics = this.diagnostics.slice(-16);
          }
        } catch { /* Ignore unrelated/malformed private diagnostics. */ }
      }
    });
    this.ready = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Owned fixture startup timed out')), 15000);
      this.child.on('message', (message: any) => {
        if (!message || message.token !== this.token) return;
        if (message.ready) { clearTimeout(timer); this.binding = message.binding; resolve(message); }
        const request = this.requests.get(message.id);
        if (request) { clearTimeout(request.timer); this.requests.delete(message.id); request.resolve(message); }
      });
      this.child.once('error', error => { clearTimeout(timer); reject(error); });
      this.child.once('exit', () => {
        clearTimeout(timer); reject(new Error('Owned fixture exited'));
        for (const request of this.requests.values()) {
          clearTimeout(request.timer); request.resolve({ ok: false, error: 'Owned fixture exited' });
        }
        this.requests.clear();
      });
    });
  }
  async ask(command: string, payload: any = {}, timeout = 16000): Promise<any> {
    const result = await new Promise<any>(resolve => {
      const id = randomUUID();
      const timer = setTimeout(() => { this.requests.delete(id); resolve({ ok: false, error: 'Owned fixture request timed out' }); }, timeout);
      this.requests.set(id, { resolve, timer });
      this.child.send?.({ token: this.token, id, command, payload }, error => {
        if (error) { clearTimeout(timer); this.requests.delete(id); resolve({ ok: false, error: 'Owned fixture IPC closed' }); }
      });
    });
    if (!result.ok) throw new Error(result.error);
    return result.result;
  }
  async endpoint(command: string, payload: any = {}): Promise<any> {
    const result = await this.ask('endpoint', { command, payload });
    if (result.ok) this.latest = result.result;
    return result;
  }
  async state(): Promise<any> { const response = await this.endpoint('audit.status'); if (!response.ok) throw new Error(response.error.message); return response.result; }
  close(): Promise<void> {
    if (!this.closing) this.closing = this.closeOwned();
    return this.closing;
  }
  private async closeOwned(): Promise<void> {
    const exited = () => this.child.exitCode !== null || this.child.signalCode !== null;
    if (exited()) return;
    const deadline = performance.now() + 14000;
    try { await this.ask('close', {}, 14000); } catch { /* exit may precede its final IPC reply */ }
    while (!exited() && performance.now() < deadline) await sleep(30);
    if (!exited()) {
      this.child.kill();
      const killedDeadline = performance.now() + 2000;
      while (!exited() && performance.now() < killedDeadline) await sleep(30);
      if (!exited()) throw new Error('Exact owned fixture did not exit after bounded termination' + this.diagnosticDetail());
      throw new Error('Fixture cleanup required forced termination' + this.diagnosticDetail());
    }
    if (this.diagnostics.some(item => item.startsWith('fixture_cleanup_failed:'))) throw new Error('Fixture cleanup failed' + this.diagnosticDetail());
    if (this.child.exitCode !== 0) throw new Error('Fixture graceful cleanup exited unsuccessfully' + this.diagnosticDetail());
  }
  private diagnosticDetail(): string { return this.diagnostics.length ? ` [${this.diagnostics.join(', ')}]` : ''; }
}

export async function runRecoveryAudit(createFixture = (output: string, config: string) => new Fixture(output, config)): Promise<void> {
  const active = new Set<Fixture>(); let abort = false;
  const progress = new AuditOutput(process.stdout, process.stderr, () => {
    abort = true;
    for (const fixture of active) void fixture.close().catch(() => {});
  });
  await app.whenReady();
  const runtime = resolveRuntime({ packaged: app.isPackaged, appRoot: path.resolve(__dirname, '..'), resources: process.resourcesPath,
    executable: process.execPath, cwd: process.cwd(), argv: process.argv, env: process.env });
  ensureRuntimeConfig(runtime);
  const outputIndex = process.argv.indexOf('--audit-output');
  const output = outputIndex >= 0 ? path.resolve(process.argv[outputIndex + 1]) : runtime.auditOutput;
  await mkdir(path.dirname(output), { recursive: true });
  const inject = process.argv.includes('--native-input');
  const checks: { name: string; passed: boolean; detail: string }[] = [];
  const attemptId = randomUUID();
  const runIdentity = new AuditRunIdentity();
  const savePending = async (reason: string) => {
    const temporary = `${output}.${attemptId}.pending`;
    await writeFile(temporary, JSON.stringify({ schema: 2, frontend: 'electron', mode: 'audit_only', blocking_enabled: false,
      passed: false, status: progress.failure || abort ? 'failed' : 'pending_or_incomplete', attempt_id: attemptId, generated_at: new Date().toISOString(),
      identity: runIdentity.initial, run_identity_stable: runIdentity.stable,
      first_failure: progress.failure, reason: progress.failure ?? reason, checks }, null, 2));
    await rename(temporary, output);
  };
  // A crashed/cancelled fresh attempt must never leave an older PASS usable.
  await savePending('Native recovery audit started; no checks completed');
  const retiredOwners = new Map<string, { kind: string; pid: number; created: string }>();
  const statusWindow = new BrowserWindow({ width: 660, height: 360, title: 'Electron recovery audit — no suppression', webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await statusWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<h2>Native recovery audit</h2><p>No shortcut suppression or foreground containment. Owned temporary windows will open.</p><pre id="status">Preparing checks…</pre>'));
  statusWindow.on('close', () => { abort = true; for (const fixture of active) void fixture.close().catch(() => {}); });
  const record = async (name: string, passed: boolean, detail: string) => {
    checks.push({ name, passed, detail: detail.slice(0, 1900) });
    await savePending('Audit incomplete; only an explicit complete finish can pass');
    await progress.write({ native_audit: name, passed, detail });
    if (!statusWindow.isDestroyed()) void statusWindow.webContents.executeJavaScript(`document.getElementById('status').textContent=${JSON.stringify(checks.map(c => `${c.passed ? 'PASS' : 'FAIL / NOT RUN'} ${c.name}`).join('\n'))}`).catch(() => {});
  };
  const wait = async (predicate: () => Promise<boolean>, timeout = 8000) => {
    const start = performance.now();
    while (performance.now() - start < timeout) { if (abort) throw new Error('Operator cancelled'); if (await predicate()) return performance.now() - start; await sleep(100); }
    throw new Error(`Native recovery was not confirmed within ${timeout}ms`);
  };
  const bindFixture = async (f: Fixture) => {
    const response = await f.ask('bind');
    if (!response.ok) throw new Error(response.error.message);
    runIdentity.observe(response.result.audit_identity);
    f.latest = response.result;
  };
  const fixture = async (bind = true) => {
    if (abort) throw new Error('Operator cancelled');
    const f = createFixture(output, runtime.config); active.add(f); await f.ready;
    if (bind) await bindFixture(f);
    return f;
  };
  const close = async (f: Fixture) => {
    for (const owner of f.latest?.native_owners ?? []) {
      if (Number.isSafeInteger(owner.pid) && typeof owner.created === 'string') retiredOwners.set(`${owner.pid}:${owner.created}`, owner);
    }
    await f.close(); active.delete(f);
  };
  const closeAll = async () => {
    const results = await Promise.allSettled([...active].map(close));
    const failure = results.find(result => result.status === 'rejected');
    if (failure?.status === 'rejected') throw failure.reason;
  };
  const enable = async (f: Fixture) => {
    await wait(async () => (await f.state()).native.control_confirmed === true);
    const response = await f.endpoint('audit.enable', { max_session_seconds: 15 });
    if (!response.ok || response.result.native.armed !== true || response.result.native.blocking_enabled !== false) throw new Error('Audit-only arming acknowledgement missing');
    return response.result;
  };
  const released = (state: any) => state.native.armed === false && state.native.blocking_enabled === false && state.native.hook_installed === false && state.native.hotkey_registered === false;
  const verifyRetiredOwners = async (observer: Fixture) => {
    for (const owner of retiredOwners.values()) {
      await wait(async () => {
        const result = await observer.endpoint('audit.process_gone', { pid: owner.pid, created: owner.created });
        if (!result.ok) throw new Error(`Cleanup identity check failed for ${owner.kind}: ${result.error.message}`);
        return result.result.process_gone === true;
      }, 2500);
    }
    retiredOwners.clear();
  };
  const cleanupCheckpoint = async () => {
    await closeAll();
    if (!retiredOwners.size || abort) return;
    const next = await fixture(false);
    await verifyRetiredOwners(next);
    await bindFixture(next);
    await enable(next); await next.endpoint('audit.release'); await wait(async () => released(await next.state())); await close(next);
  };
  const check = async (name: string, action: () => Promise<string | void>) => {
    try {
      if (abort) throw new Error('NOT RUN: operator cancelled');
      await progress.write({ audit_stage: name });
      const detail = await action(); await cleanupCheckpoint();
      await record(name, true, (detail || 'Native owned fixture passed') + '; exact-owner cleanup and fresh re-registration checked');
    }
    catch (error) {
      if (progress.failure) throw error;
      await record(name, false, String(error));
    }
    finally { await closeAll(); }
  };
  const site = createServer((_request, response) => { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<h2>Controlled external audit page</h2><input aria-label="Fixture answer">'); });
  await new Promise<void>(resolve => site.listen(0, '127.0.0.1', resolve));
  const siteUrl = `http://127.0.0.1:${(site.address() as { port: number }).port}/`;
  try {
    await check('binding_identity', async () => { const f = await fixture(); const s = await f.state(); if (!s.native.prepared) throw new Error('Native binding not prepared'); });
    await check('wrong_hwnd_rejected', async () => { const f = await fixture(false); if ((await f.ask('bind', { windows: [{ hwnd: '0x1', role: 'exam' }] })).ok) throw new Error('Invalid HWND accepted'); });
    await check('wrong_stale_identity_rejected', async () => {
      const f = await fixture(); const handles = await f.ask('stale_handles');
      const candidates = [
        { ...f.binding, launch_id: '0'.repeat(32) },
        ...[handles.destroyed, handles.unstamped, nativeHandleHex(statusWindow.getNativeWindowHandle())].map(hwnd => ({ ...f.binding, windows: [{ hwnd, role: 'exam' }] })),
      ];
      for (const candidate of candidates) {
        const result = await f.endpoint('audit.binding_rejected', { candidate });
        if (!result.ok || !result.result.binding_rejected) throw new Error('Wrong launch, destroyed/unstamped or foreign HWND was accepted');
      }
      return 'Wrong launch, destroyed HWND, unstamped same-process HWND and foreign observer HWND rejected; no arbitrary PID reuse was manufactured';
    });
    await check('normal_release', async () => { const f = await fixture(); await enable(f); await f.endpoint('audit.release'); await wait(async () => released(await f.state())); });
    await check('repeated_cycles', async () => { for (let i = 0; i < 3; i++) { const f = await fixture(); await enable(f); await f.endpoint('audit.release'); await wait(async () => released(await f.state())); await close(f); } return 'Three independent attach/enable/release/cleanup cycles'; });
    for (const [name, focus] of [['emergency_shortcut', 'trusted'], ['pin_modal_emergency', 'focus_pin'], ['external_focus_emergency', 'focus_external']]) {
      await check(name, async () => {
        if (!inject) throw new Error('NOT RUN: --native-input requires operator readiness and exact foreground check');
        const f = await fixture(); await enable(f);
        if (focus !== 'trusted') await f.ask(focus, { url: siteUrl });
        await sleep(200);
        const response = await f.endpoint('audit.emergency'); if (!response.ok) throw new Error(response.error.message);
        await wait(async () => released(await f.state()));
      });
    }
    for (const [name, action] of [['renderer_loss_observer_alive', 'renderer_stall'], ['main_stall', 'main_stall'], ['backend_stall', 'backend_stall']]) {
      await check(name, async () => {
        const f = await fixture(); await enable(f); const started = performance.now();
        if (action === 'backend_stall') await f.endpoint('audit.stall_controller', { seconds: 6.5 }); else await f.ask(action);
        await wait(async () => released(await f.state()), 8500);
        const status = await f.state();
        const native = status.native;
        const elapsed = typeof native.released_at === 'number' && typeof native.control_confirmed_at === 'number' ? native.released_at - native.control_confirmed_at : null;
        if (native.reason !== 'control_progress_lost') throw new Error(`Expected lost-control release, observed ${native.reason}`);
        if (elapsed === null || elapsed < 0) throw new Error('Native release/last progress timestamps missing');
        const deadline = Number(status.protection_policy?.heartbeat_timeout_seconds);
        if (!Number.isFinite(deadline) || elapsed > deadline + 1) throw new Error(`Native lease release exceeded configured heartbeat + 1s allowance: ${elapsed}s`);
        return `Release after ${action}: native last-progress-to-release ${elapsed.toFixed(3)}s; observer confirmation ${(performance.now() - started).toFixed(0)}ms. Main status polling continues during renderer stall.`;
      });
    }
    for (const [name, action] of [['main_loss', 'main_loss'], ['backend_loss', 'backend_loss'], ['control_eof', 'eof']]) {
      await check(name, async () => {
        // This unbound observer owns no helper/mutex and cannot release the
        // faulted fixture. Observe owner death before any fixture cleanup.
        const observer = await fixture(false);
        const f = await fixture(); const armed = await enable(f); const started = performance.now();
        if (action === 'main_loss') f.child.kill();
        else if (action === 'backend_loss') void f.endpoint('audit.crash').catch(() => {});
        else await f.ask('eof');
        await wait(async () => {
          const gone = await observer.endpoint('audit.process_gone', { pid: armed.helper_pid, created: armed.helper_created });
          if (!gone.ok) throw new Error(gone.error.message);
          return gone.result.process_gone === true;
        }, 8500);
        const observed = performance.now() - started;
        await bindFixture(observer);
        await enable(observer); await observer.endpoint('audit.release'); await wait(async () => released(await observer.state()));
        return `Independent exact helper death confirmed before cleanup after ${action}, observed ${observed.toFixed(0)}ms; fresh re-registration confirmed`;
      });
    }
    for (const [name, command] of [['lost_release_ack', 'audit.lost_release_ack'], ['helper_suspension', 'audit.suspend_helper'], ['helper_loop_failure', 'audit.loop_failure'], ['forced_release', 'audit.terminate_helper']]) {
      await check(name, async () => { const f = await fixture(); await enable(f); const response = await f.endpoint(command); if (!response.ok) throw new Error(response.error.message); await wait(async () => released(await f.state()) || (await f.state()).helper_alive === false); });
    }
    await check('replay_rejected', async () => {
      const f = await fixture(); await enable(f);
      await f.ask('progress', { enabled: false }); await sleep(250);
      const response = await f.endpoint('audit.replay');
      if (!response.ok || response.result.replay_rejected !== true) throw new Error('Healthy-owner replay rejection was not confirmed');
      await f.ask('progress', { enabled: true });
    });
    await check('overlapping_helper_rejected', async () => { const first = await fixture(); await enable(first); const second = await fixture(false); if ((await second.ask('bind')).ok) throw new Error('Overlapping protected owner accepted'); if (!(await first.state()).native.armed) throw new Error('Second launch disturbed first owner'); });
    await check('recovery_reregister', async () => { const f = await fixture(); await enable(f); await f.endpoint('audit.release'); await wait(async () => released(await f.state())); });
    const reporter = await fixture();
    for (const item of checks) { const result = await reporter.endpoint('audit.record', item); if (!result.ok) throw new Error(result.error.message); }
    // The endpoint returns a candidate report only. A PASS is not durable until
    // its own helper/guardian/backend cleanup has also been confirmed.
    const result = await reporter.endpoint('audit.finish', { persist: false });
    if (!result.ok) throw new Error(result.error.message);
    runIdentity.observe(result.result.report.identity);
    await close(reporter);
    const verifier = await fixture(false);
    await verifyRetiredOwners(verifier);
    // This unbound observer has no helper/guardian. Its owning fixture waits
    // for the direct backend child exit before its own process can finish.
    await close(verifier);
    await progress.write({ report: output, passed: result.result.report.passed, missing: result.result.report.missing_checks });
    progress.assertHealthy();
    const completed = `${output}.${attemptId}.completed`;
    await writeFile(completed, JSON.stringify({ ...result.result.report,
      status: 'completed', attempt_id: attemptId, run_identity_stable: runIdentity.stable }, null, 2));
    progress.assertHealthy();
    await rename(completed, output);
  } catch (error) {
    abort = true;
    process.exitCode = 1;
    await savePending(`Native audit did not finish: ${String(error)}`);
    throw error;
  } finally {
    try { await closeAll(); }
    catch (error) { abort = true; process.exitCode = 1; await savePending(`Final owned cleanup failed: ${String(error)}`); }
    finally {
      if (progress.failure) await savePending(progress.failure);
      await new Promise<void>(resolve => site.close(() => resolve()));
      if (!statusWindow.isDestroyed()) statusWindow.destroy();
      app.quit();
    }
  }
}
