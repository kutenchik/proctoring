import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomBytes } from 'node:crypto';
import { AuditClient } from './audit_client';
import { ControlProgress } from './control_progress';
import { desktopBuildFingerprint, nativeHandleHex } from './host_binding';
import { ExternalExam } from './external';
import { resolveRuntime } from './runtime';
import { finishShutdown } from './shutdown';

/** Private child mode: only an inherited parent IPC channel may invoke faults. */
export interface FixtureContext { window: BrowserWindow; audit: AuditClient; binding: Record<string, any>; getExternal: () => ExternalExam | undefined }
export async function runRecoveryFixture(protectedMode = false,
  extension?: (command: string, payload: any, context: FixtureContext) => Promise<any>): Promise<void> {
  if (!process.send || !process.env.PROCTORING_AUDIT_FIXTURE_TOKEN) throw new Error('Owned audit IPC required');
  await app.whenReady();
  const token = process.env.PROCTORING_AUDIT_FIXTURE_TOKEN;
  const appRoot = path.resolve(__dirname, '..'), repo = path.resolve(appRoot, '..');
  const runtime = resolveRuntime({ packaged: app.isPackaged, appRoot, resources: process.resourcesPath, executable: process.execPath,
    cwd: process.cwd(), argv: [], env: process.env });
  const output = process.env.PROCTORING_AUDIT_OUTPUT!;
  const launch = randomBytes(16).toString('hex');
  const window = new BrowserWindow({ width: 1100, height: 760, show: false, title: 'Local Proctoring · bounded native recovery audit',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true, contextIsolation: true, nodeIntegration: false, webviewTag: false, backgroundThrottling: false } });
  window.removeMenu();
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  if (protectedMode && !process.env.PROCTORING_RECOVERY_REPORT) throw new Error('Fresh Gate 3A report required for controlled protection');
  const args = protectedMode ? app.isPackaged ? ['--electron-protected-test'] : ['-u', '-m', 'proctoring.security.electron_protected_test'] : [...runtime.auditPrefix];
  if (protectedMode) args.push('--allow-short-protection', '--recovery-report', process.env.PROCTORING_RECOVERY_REPORT!);
  args.push('--parent-pid', String(process.pid), '--output', output);
  if (process.env.PROCTORING_AUDIT_CONFIG) args.push('--config', process.env.PROCTORING_AUDIT_CONFIG);
  if (app.isPackaged) args.push('--package-root', path.dirname(process.execPath));
  const audit = new AuditClient(runtime.python, args, runtime.backendCwd, launch);
  const binding = { launch_id: launch, host_pid: process.pid, windows: [{ hwnd: nativeHandleHex(window.getNativeWindowHandle()), role: 'exam' }],
    runtime: { electron_version: process.versions.electron, app_version: app.getVersion(), build_kind: app.isPackaged ? 'packaged' : 'source', build_id: await desktopBuildFingerprint(appRoot) } };
  const progress = new ControlProgress(); let sequence = 0; let autoProgress = true;
  let latest: any; let stopping = false; let external: ExternalExam | undefined;
  const temporary: BrowserWindow[] = [];
  const delivered = new Set<number>();
  const source = pathToFileURL(path.join(__dirname, 'recovery-renderer.html')).href + (protectedMode ? '?mode=protected' : '');
  const trusted = (event: Electron.IpcMainInvokeEvent) => {
    if (stopping || window.isDestroyed() || window.webContents.isDestroyed()) throw new Error('Fixture is closing');
    if (event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || event.senderFrame.url !== source) throw new Error('Untrusted fixture sender');
  };
  const publish = (state: any) => {
    if (stopping || !audit.available || window.isDestroyed() || window.webContents.isDestroyed()) return;
    latest = { protection: state.protection, workflow: { snapshot_seq: ++sequence, session_id: null } };
    if (autoProgress && state.protection.challenge) {
      const challenge = progress.offer(state.protection.challenge, sequence, null);
      if (challenge) window.webContents.send('proctoring:control-challenge', challenge);
    }
  };
  ipcMain.handle('proctoring:command', (event, name) => {
    trusted(event); if (name !== 'state.get') throw new Error('No real commands in audit fixture');
    if (latest) { delivered.add(latest.workflow.snapshot_seq); if (delivered.size > 100) delivered.delete(delivered.values().next().value!); }
    return { version: 1, id: 'fixture', ok: true, result: latest };
  });
  ipcMain.handle('proctoring:control-progress', async (event, receipt) => {
    trusted(event); if (!autoProgress || !delivered.has(receipt?.snapshot_seq)) return { accepted: false };
    const accepted = progress.accept(receipt, null);
    if (!accepted) return { accepted: false };
    const response = await audit.raw('host.progress', { ...accepted });
    progress.confirm(accepted, response.ok);
    if (response.ok) publish(response.result);
    return { accepted: response.ok };
  });
  let polling = false;
  const timer = setInterval(() => {
    if (polling || stopping || !audit.available) return;
    polling = true;
    void audit.call('audit.status').then(publish).catch(() => {}).finally(() => { polling = false; });
  }, 100);
  await window.loadURL(source); window.show();
  let closePromise: Promise<void> | undefined;
  function close(): Promise<void> {
    if (closePromise) return closePromise;
    stopping = true; clearInterval(timer);
    closePromise = finishShutdown({
      closePresentation: () => external?.close(),
      endSession: () => audit.close(),
      closeBackend: () => {
        try { for (const owned of temporary) if (!owned.isDestroyed()) owned.destroy(); }
        finally { if (!window.isDestroyed()) window.destroy(); }
      },
      quit: () => app.quit(),
      reportErrors: errors => {
        console.error('AUDIT_FIXTURE_DIAGNOSTIC ' + JSON.stringify({ phase: 'fixture_cleanup_failed', code: String(errors.length) }));
        process.exitCode = 1;
      },
    });
    return closePromise;
  }
  function send(message: Record<string, unknown>): void {
    if (stopping || !process.connected || !process.send) return;
    try {
      process.send(message, error => {
        if (error) console.error('AUDIT_FIXTURE_DIAGNOSTIC ' + JSON.stringify({ phase: 'parent_ipc_closed', code: 'send_failed' }));
      });
    } catch {
      console.error('AUDIT_FIXTURE_DIAGNOSTIC ' + JSON.stringify({ phase: 'parent_ipc_closed', code: 'send_threw' }));
    }
  }
  window.on('close', event => { if (!stopping) { event.preventDefault(); void close(); } });
  process.on('disconnect', () => { void close(); });
  process.on('message', async (message: any) => {
    if (stopping || !message || message.token !== token || typeof message.id !== 'string') return;
    try {
      let result: any;
      const payload = message.payload || {};
      switch (message.command) {
        case 'bind': result = await audit.raw('host.bind', { ...binding, ...payload }); break;
        case 'endpoint': result = await audit.raw(payload.command, payload.payload || {}); break;
        case 'status': result = audit.latest; break;
        case 'stale_handles': {
          const destroyed = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
          const hwnd = nativeHandleHex(destroyed.getNativeWindowHandle()); destroyed.destroy();
          const unstamped = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
          temporary.push(unstamped);
          result = { destroyed: hwnd, unstamped: nativeHandleHex(unstamped.getNativeWindowHandle()) }; break;
        }
        case 'renderer_stall': void window.webContents.executeJavaScript(`{const until=performance.now()+${Math.min(8000, Number(payload.milliseconds) || 6500)};while(performance.now()<until){}}`).catch(() => {}); result = true; break;
        case 'main_stall': { const until = performance.now() + 6500; while (performance.now() < until) {} result = true; break; }
        case 'renderer_crash': window.webContents.forcefullyCrashRenderer(); result = true; break;
        case 'eof': audit.child.stdin.end(); result = true; break;
        case 'progress': autoProgress = payload.enabled === true; result = true; break;
        case 'focus_pin': {
          window.focus(); window.webContents.focus();
          const focused = await window.webContents.executeJavaScript('document.getElementById("audit-pin-modal").showModal();document.getElementById("audit-pin").focus();document.activeElement===document.getElementById("audit-pin")');
          if (!focused || !window.webContents.isFocused()) throw new Error('PIN input focus was not established');
          result = { pin_input_focused: true, trusted_contents_focused: true }; break;
        }
        case 'focus_external':
          external = new ExternalExam(window, () => {}); external.configure(payload.url, ['127.0.0.1']); external.setRunning(true);
          external.intent({ action: 'layout', bounds: { x: 20, y: 350, width: 640, height: 220 }, visible: true, modal: false });
          window.focus();
          {
            const deadline = performance.now() + 5000;
            while (performance.now() < deadline) {
              external.intent({ action: 'layout', bounds: { x: 20, y: 350, width: 640, height: 220 }, visible: true, modal: false });
              if (external.status.state === 'ready' && external.status.visible && !external.ownedContents?.isLoading()) break;
              await new Promise(resolve => setTimeout(resolve, 30));
            }
            external.intent({ action: 'focus' });
            await new Promise(resolve => setTimeout(resolve, 50));
            if (external.status.state !== 'ready' || !external.status.visible || !external.ownedContents?.isFocused()) throw new Error('Loaded visible native external view did not acquire focus');
            result = { loaded: true, visible: true, external_contents_focused: true };
          }
          break;
        case 'close': await close(); return;
        default:
          if (!extension) throw new Error('Unknown private fixture action');
          result = await extension(message.command, payload, { window, audit, binding, getExternal: () => external });
      }
      send({ token, id: message.id, ok: true, result });
    } catch (error) { send({ token, id: message.id, ok: false, error: String(error) }); }
  });
  send({ token, ready: true, pid: process.pid, binding });
}
