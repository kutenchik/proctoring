/** Explicit, bounded Gate 3B runner. No ordinary renderer can invoke these faults. */
import { app, BrowserWindow } from 'electron';
import path from 'node:path';
import { createServer } from 'node:http';
import { mkdir, writeFile, rename } from 'node:fs/promises';
import { Fixture } from './recovery_audit';
import { ensureRuntimeConfig, resolveRuntime } from './runtime';
import { assertSuppressedProbe, assertOrdinaryInputProbe, assertControlLossRelease, assertNormalRelease, foregroundRecoveryBound, assertCrossProcessForegroundRecovery, assertSuspendedOwnerDeath, runProtectedCheck } from './protected_assertions';

const shortcuts: Record<string, [string, string]> = {
  alt_tab: ['Tab', 'BLOCKED_ALT_TAB'], alt_shift_tab: ['Tab', 'BLOCKED_ALT_TAB'],
  left_win: ['MetaLeft', 'BLOCKED_WINDOWS_KEY'], right_win: ['MetaRight', 'BLOCKED_WINDOWS_KEY'],
  copy: ['KeyC', 'BLOCKED_COPY'], paste: ['KeyV', 'BLOCKED_PASTE'],
  ctrl_insert: ['Insert', 'BLOCKED_COPY'], shift_insert: ['Insert', 'BLOCKED_PASTE'],
  print_screen: ['PrintScreen', 'BLOCKED_SCREENSHOT'], alt_f4: ['F4', 'BLOCKED_CLOSE'],
  alt_escape: ['Escape', 'BLOCKED_ALT_ESCAPE'], ctrl_escape: ['Escape', 'BLOCKED_START_MENU'],
  ctrl_shift_escape: ['Escape', 'BLOCKED_TASK_MANAGER'],
};
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export async function runProtectedAudit(): Promise<void> {
  const probeOnly = process.argv.includes('--probe-input-only');
  if (!process.argv.includes('--allow-short-protection')) throw new Error('Explicit --allow-short-protection and operator readiness required');
  const recoveryIndex = process.argv.indexOf('--recovery-report');
  if (recoveryIndex < 0 || !process.argv[recoveryIndex + 1]) throw new Error('Current --recovery-report is required');
  process.env.PROCTORING_RECOVERY_REPORT = path.resolve(process.argv[recoveryIndex + 1]);
  await app.whenReady();
  const runtime = resolveRuntime({ packaged: app.isPackaged, appRoot: path.resolve(__dirname, '..'), resources: process.resourcesPath,
    executable: process.execPath, cwd: process.cwd(), argv: process.argv, env: process.env });
  ensureRuntimeConfig(runtime);
  const outputIndex = process.argv.indexOf('--test-output');
  const output = outputIndex >= 0 ? path.resolve(process.argv[outputIndex + 1]) : path.join(path.dirname(runtime.auditOutput), 'electron-protected-tests.json');
  const checks: { name: string; passed: boolean; detail: string }[] = [];
  const probeMeasurements: any[] = [];
  const active = new Set<Fixture>(); let cancelled = false; let restored = 0;
  let identity: string | undefined;
  const status = new BrowserWindow({ width: 620, height: 340, title: 'Bounded protected tests · explicit opt-in', webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await status.loadURL('data:text/html,' + encodeURIComponent(probeOnly ? '<h2>Unprotected owned input probe</h2><p>No keyboard hook, blocking or hotkey is enabled. Only A and Insert are sent to this owned fixture.</p><pre id="result">Preparing…</pre>' : '<h2>Short protected tests</h2><p>Each owned fixture has a maximum 15-second native lease. Ctrl+Shift+Alt+Q releases it.</p><pre id="result">Preparing current recovery audit check…</pre>'));
  status.on('close', () => { cancelled = true; for (const f of active) void f.close(); });
  const wait = async (predicate: () => Promise<boolean>, timeout = 8000) => {
    const start = performance.now();
    while (performance.now() - start < timeout) { if (cancelled) throw new Error('Operator cancelled'); if (await predicate()) return; await sleep(100); }
    throw new Error('Owned native check exceeded its bound');
  };
  const fixture = async (bind = true) => {
    if (cancelled) throw new Error('Operator cancelled');
    const f = new Fixture(output, runtime.config, 'protected', process.env.PROCTORING_RECOVERY_REPORT); active.add(f); await f.ready;
    if (bind) {
      const response = await f.ask('bind'); if (!response.ok) throw new Error(response.error.message);
      const current = JSON.stringify(response.result.audit_identity);
      if (!response.result.audit_identity || (identity !== undefined && current !== identity)) throw new Error('Runtime identity changed during protected tests');
      identity = current;
    }
    return f;
  };
  const call = async (f: Fixture, name: string, payload: Record<string, unknown> = {}) => {
    const response = await f.endpoint(name, payload); if (!response.ok) throw new Error(response.error?.message || 'Protected fixture rejected command'); return response.result;
  };
  const enable = async (f: Fixture, seconds = 15) => {
    if (probeOnly) throw new Error('Unprotected input probe cannot enable restrictions');
    await wait(async () => (await f.state()).native.control_confirmed === true);
    const result = await call(f, 'test.enable', { max_session_seconds: seconds });
    if (result.native.armed !== true || result.native.blocking_enabled !== true) throw new Error('Actual protected acknowledgement missing');
  };
  const released = (s: any) => ['armed', 'blocking_enabled', 'hook_installed', 'hotkey_registered'].every(k => s.native[k] === false);
  const normalInput = async (f: Fixture) => {
    await wait(async () => released(await f.state()));
    await f.ask('focus_context', { kind: 'trusted' }); await f.ask('key_probe_reset'); await sleep(100);
    const injected = await call(f, 'test.normal_input'); let probe: any;
    const deadline = performance.now() + 1000;
    do { await sleep(50); probe = await f.ask('key_probe'); } while (performance.now() < deadline && (probe.counts?.KeyA !== 1 || probe.ups?.KeyA !== 1));
    try { assertOrdinaryInputProbe('KeyA', probe); }
    catch (error) { throw new Error(`${String(error)}; injection=${JSON.stringify(injected.injection)}; native=${JSON.stringify(injected.native)}`); }
    restored++;
  };
  const close = async (f: Fixture) => { await f.close(); active.delete(f); };
  const record = (name: string, passed: boolean, detail: string) => {
    checks.push({ name, passed, detail: detail.slice(0, 1900) });
    console.log(JSON.stringify({ native_protected_test: name, passed, detail }));
    if (!status.isDestroyed()) void status.webContents.executeJavaScript(`document.getElementById('result').textContent=${JSON.stringify(checks.map(c => `${c.passed ? 'PASS' : 'FAIL / NOT RUN'} ${c.name}`).join('\n'))}`).catch(() => {});
  };
  const check = async (name: string, action: () => Promise<string | void>) => {
    await runProtectedCheck(name, action, async () => {
      const failures: unknown[] = [];
      for (const f of [...active]) { try { await close(f); } catch (error) { cancelled = true; failures.push(error); } }
      if (failures.length) throw new Error(failures.map(String).join('; '));
    }, record);
  };
  const site = createServer((_request, response) => { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<h2>Owned external test page</h2><input id="protected-probe" aria-label="Owned answer">'); });
  await new Promise<void>(resolve => site.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${(site.address() as { port: number }).port}/`;
  const savePartial = async (reason: string) => {
    const report = { schema: 1, mode: probeOnly ? 'owned_unprotected_input' : 'protected_validation', passed: false, partial: true,
      blocking_enabled: !probeOnly, generated_at: new Date().toISOString(), identity: identity ? JSON.parse(identity) : null,
      checks, probe_measurements: probeMeasurements, stopped_reason: reason, not_run: 'All remaining checks were not run after the first failed check or cancellation.' };
    await mkdir(path.dirname(output), { recursive: true });
    await writeFile(output + '.partial', JSON.stringify(report, null, 2)); await rename(output + '.partial', output);
  };
  try {
    if (probeOnly) {
      const f = await fixture(); const measurements = probeMeasurements;
      for (const [name, code] of [['a', 'KeyA'], ['insert', 'Insert']]) {
        await f.ask('focus_context', { kind: 'trusted' }); await f.ask('key_probe_reset');
        const result = await call(f, 'test.unprotected_input', { name }); await sleep(250);
        const probe = await f.ask('key_probe'); measurements.push({ name, injection: result.injection, native: result.native, probe });
        console.log(JSON.stringify({ unprotected_input_probe: measurements.at(-1) }));
        assertOrdinaryInputProbe(code, probe);
        record(`unprotected:${name}`, true, JSON.stringify(measurements.at(-1)));
      }
      await close(f);
      await mkdir(path.dirname(output), { recursive: true });
      await writeFile(output, JSON.stringify({ schema: 1, mode: 'owned_unprotected_input', blocking_enabled: false, passed: true, measurements }, null, 2));
      return;
    }
    // Each shortcut gets a fresh maximum lease and explicit release verification.
    for (const kind of ['trusted', 'pin', 'external']) for (const [name, [code, event]] of Object.entries(shortcuts)) {
      await check(`${kind}:${name}`, async () => {
        const f = await fixture(); await enable(f);
        if (kind === 'external') await f.ask('focus_external', { url });
        if (kind === 'pin') await f.ask('focus_pin');
        await f.ask('focus_context', { kind, url }); await f.ask('key_probe_reset'); await call(f, 'test.events'); await sleep(120);
        const injected = await call(f, 'test.shortcut', { name }); await sleep(120);
        const result = await call(f, 'test.events'); const probe = await f.ask('key_probe');
        try { assertSuppressedProbe(event, code, result.events, probe.counts); }
        catch (error) { throw new Error(`${String(error)}; injection=${JSON.stringify(injected.injection)}; events=${JSON.stringify(result.events)}; probe=${JSON.stringify(probe)}`); }
        await call(f, 'audit.release'); await normalInput(f);
        return 'Native suppressed event + no target keydown + confirmed release + ordinary native A delivered';
      });
    }
    await check('normal_release', async () => {
      const f = await fixture(); await enable(f); await call(f, 'audit.release'); await normalInput(f);
      for (let poll = 0; poll < 5; poll++) { await sleep(100); assertNormalRelease(await f.state(), 'normal_disable'); }
      return 'Native resources released and ordinary input restored; repeated status polls preserve public released/normal_disable';
    });
    await check('focus_containment', async () => {
      const f = await fixture(); await enable(f); await call(f, 'test.events'); await f.ask('focus_foreign_owned');
      await wait(async () => (await f.ask('focused_exam')) === true, 3000);
      const events = (await call(f, 'test.events')).events;
      if (!events.some((e: any) => e.event_type === 'UNAUTHORIZED_WINDOW')) throw new Error('Native foreground warning missing');
      await call(f, 'audit.release'); await normalInput(f);
    });
    await check('cross_process_foreground_recovery', async () => {
      const f = await fixture(); const foreign = await fixture(false);
      const examPid = f.binding.host_pid, foreignPid = foreign.binding.host_pid;
      const foreignHwnd = foreign.binding.windows[0]?.hwnd;
      if (examPid !== f.child.pid || foreignPid !== foreign.child.pid || examPid === foreignPid || typeof foreignHwnd !== 'string') {
        throw new Error('Separate inherited-IPC fixture identity differs from the actual spawned child');
      }
      await f.ask('focus_context', { kind: 'trusted' }); await enable(f); await call(f, 'test.events');
      const bound = foregroundRecoveryBound(await f.state());
      const observed = call(f, 'test.foreground_observe', { pid: foreignPid, hwnd: foreignHwnd, duration_seconds: Math.max(1.75, bound.total_seconds + .2) })
        .then(result => ({ result, error: undefined }), error => ({ result: undefined, error }));
      // The native observer runs independently of this other process's focus
      // request. No injected key, foreground policy change or unowned HWND.
      let requestError: unknown;
      await sleep(120);
      try { await foreign.ask('request_foreground'); } catch (error) { requestError = error; }
      const observationResult = await observed;
      if (observationResult.error) throw observationResult.error;
      const measured = observationResult.result;
      if (requestError) throw requestError;
      console.log(JSON.stringify({ cross_process_foreground_observation: measured.foreground_observation, native: measured.native, protection: measured.protection }));
      const outcome = assertCrossProcessForegroundRecovery(measured, examPid, foreignPid, foreignHwnd);
      const events = (await call(f, 'test.events')).events;
      if (!events.some((e: any) => e.event_type === 'UNAUTHORIZED_WINDOW')) throw new Error('Actual cross-process foreground produced no native unauthorized-window observation');
      await close(foreign);
      if (outcome.outcome === 'restored') await call(f, 'audit.release');
      await normalInput(f);
      return JSON.stringify({ ...outcome, native_foreground_observation: measured.foreground_observation,
        meaning: outcome.outcome === 'restored' ? 'Actual separate-process foreground restored to the registered exam HWND.' : 'Containment failed; bounded terminal release worked. This is not a successful-containment result.' });
    });
    await check('emergency_release', async () => { const f = await fixture(); await enable(f); await f.ask('focus_context', { kind: 'trusted' }); await call(f, 'audit.emergency'); await normalInput(f); });
    await check('maximum_lease', async () => { const f = await fixture(); await enable(f, 2); await normalInput(f); if ((await f.state()).native.reason !== 'lease_expired') throw new Error('Maximum lease was not the release cause'); });
    await check('renderer_loss', async () => {
      const f = await fixture(); await enable(f); await f.ask('renderer_stall');
      await wait(async () => released(await f.state()));
      const elapsed = assertControlLossRelease(await f.state());
      await normalInput(f);
      return `Native control_progress_lost release ${elapsed.toFixed(3)}s after last accepted progress; ordinary input restored`;
    });
    await check('helper_suspension', async () => {
      const f = await fixture(); await enable(f); const before = await f.state();
      const result = await call(f, 'audit.suspend_helper');
      await wait(async () => {
        const state = await f.state();
        return state.helper_alive === false && released(state) && ['helper_exited', 'helper_channel_closed'].includes(state.protection?.reason);
      });
      assertSuspendedOwnerDeath(before, result, await f.state());
      await normalInput(f);
      return 'Whole verified hook-owner suspension followed by confirmed original owner death, not emergency or maximum-lease release; ordinary input restored';
    });
    for (const name of ['main_loss', 'backend_loss']) await check(name, async () => {
      const f = await fixture(); await enable(f); const owner = await f.state();
      if (name === 'main_loss') f.child.kill(); else void f.endpoint('audit.crash').catch(() => {});
      const observer = await fixture(false);
      await wait(async () => (await call(observer, 'audit.process_gone', { pid: owner.helper_pid, created: owner.helper_created })).process_gone === true);
      await close(f); await close(observer);
      const fresh = await fixture(); await enable(fresh); await call(fresh, 'audit.release'); await normalInput(fresh);
      return 'Original exact hook-owner death confirmed; fresh registration/release and normal native input checked';
    });
    await check('repeated_cleanup', async () => { for (let i = 0; i < 3; i++) { const f = await fixture(); await enable(f); await call(f, 'audit.release'); await normalInput(f); await close(f); } });
    record('normal_input_restored', restored > 0 && !checks.some(c => !c.passed), `${restored} post-release native input probes; failures remain separately visible`);
    record('wrong_pin', false, 'NOT RUN here: this isolated fixture does not instantiate an exam or validate production PIN lifecycle; requires actual protected workflow test.');
    record('correct_pin', false, 'NOT RUN here: actual protected session PIN end/recovery requires separate workflow/operator validation.');
    const reporter = await fixture();
    for (const item of checks) await call(reporter, 'test.record', item);
    const result = await call(reporter, 'test.finish');
    console.log(JSON.stringify({ protected_report: output, passed: result.report.passed, missing: result.report.missing_checks }));
    await close(reporter);
  } catch (error) {
    // Do not arm another fixture when cleanup/input or any check is uncertain.
    await savePartial(String(error)); console.error(`Protected tests stopped: ${String(error)}`);
  } finally { for (const f of [...active]) await close(f); site.close(); if (!status.isDestroyed()) status.destroy(); app.quit(); }
}
