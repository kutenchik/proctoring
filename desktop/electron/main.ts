import { app, dialog, BrowserWindow, globalShortcut, ipcMain, screen, session, Tray, Menu, nativeImage, type IpcMainInvokeEvent } from 'electron';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomBytes } from 'node:crypto';
import { PythonBridge } from './bridge';
import { DEVELOPMENT_CSP, PRODUCTION_CSP, trustedRenderer, validateCommand, validateEvidence, validateExternal } from './security';
import { ExternalExam, emergencyInput } from './external';
import { GeometryOwner } from './geometry';
import { actOnEvidence } from './evidence';
import { PresentationGate } from './presentation';
import { ControlProgress } from './control_progress';
import { desktopBuildFingerprint, nativeHandleHex } from './host_binding';
import { ensureRuntimeConfig, resolveRuntime } from './runtime';
import { finishShutdown } from './shutdown';
import { requestBackgroundUpload, backgroundFinished, pendingReceiptOnClose } from './background';
import { LiveScreen } from './live_screen';
import type { BackendState, Command, CommandResult, ExternalStatus } from '../shared/contracts';

const fixture = process.argv.includes('--fixture');
const launchId = randomBytes(16).toString('hex');
const controlProgress = new ControlProgress();
const runtime = resolveRuntime({ packaged: app.isPackaged, appRoot: path.resolve(__dirname, '..'), resources: process.resourcesPath,
  executable: process.execPath, cwd: process.cwd(), argv: process.argv, env: process.env });
const { dev } = runtime;
const rendererUrl = dev ? 'http://127.0.0.1:5173/' : pathToFileURL(path.join(__dirname, '../dist/index.html')).href;
let window: BrowserWindow | undefined;
let bridge: PythonBridge | undefined;
let external: ExternalExam | undefined;
let geometry: GeometryOwner | undefined;
let lastGeometry = '';
let lastGeometryIdentity = '';
let stopping = false;
let connecting = false;
let configuringExternal = false;
let hostBound = false;
let layoutSettling = false;
let protectedWindowControls = false;
let presentationTimer: NodeJS.Timeout | undefined;
let tray: Tray | undefined;
let backgroundUpload = false;
let liveScreen: LiveScreen | undefined;
const presentation = new PresentationGate();
let lastRendererRequest = Date.now();
const deliveredSnapshots = new Map<number, { session_id: string | null; cursor: number }>();
let deliveredEventCursor = 0;
let deliveredSession: string | null = null;
const unavailable = (code: string): CommandResult => ({ version: 1, id: 'unavailable', ok: false, error: { code, message: code } });

function sender(event: IpcMainInvokeEvent): void {
  if (stopping || !window || window.isDestroyed() || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame ||
      !trustedRenderer(event.senderFrame.url, rendererUrl)) throw new Error('Untrusted IPC sender');
  lastRendererRequest = Date.now();
}
function publicResult(result: CommandResult, allowEvents = false): CommandResult {
  if (!result.ok) return result;
  const workflow = result.result.workflow;
  if (workflow) {
    if (workflow.session_id !== deliveredSession) { deliveredSession = workflow.session_id; deliveredEventCursor = 0; deliveredSnapshots.clear(); }
    deliveredSnapshots.set(workflow.snapshot_seq, { session_id: workflow.session_id, cursor: workflow.events.cursor });
    while (deliveredSnapshots.size > 64) deliveredSnapshots.delete(deliveredSnapshots.keys().next().value!);
    if (allowEvents && result.data && typeof result.data === 'object') {
      const cursor = (result.data as { cursor?: unknown }).cursor;
      if (Number.isSafeInteger(cursor) && Number(cursor) >= 0) deliveredEventCursor = Math.max(deliveredEventCursor, Number(cursor));
    }
  }
  return { version: 1, id: result.id, ok: true, result: result.result, ...(allowEvents ? { data: result.data } : {}) };
}
function updateState(state: BackendState): void {
  liveScreen?.update(state);
  if (backgroundUpload && backgroundFinished(state)) { void stop(); return; }
  if (stopping || !window || window.isDestroyed() || window.webContents.isDestroyed()) return;
  const workflow = state.workflow;
  if (window && !window.isDestroyed() && state.protection.enabled !== protectedWindowControls) {
    protectedWindowControls = state.protection.enabled;
    window.setMinimizable(!protectedWindowControls); window.setResizable(!protectedWindowControls);
    window.setMaximizable(!protectedWindowControls); window.setMovable(!protectedWindowControls);
    window.setFullScreenable(!protectedWindowControls);
  }
  if (state.protection.challenge && workflow && window && !window.isDestroyed()) {
    const challenge = controlProgress.offer(state.protection.challenge, workflow.snapshot_seq, workflow.session_id);
    if (challenge) window.webContents.send('proctoring:control-challenge', challenge);
  }
  external?.setRunning(!!workflow?.session.running && !presentation.lost && !window?.isMinimized());
  if (workflow?.session.ended) external?.close();
  if (workflow?.session.started && !workflow.session.ended && state.config.external_exam_configured && !external?.status.configured && !configuringExternal) {
    configuringExternal = true;
    void bridge?.host('host.external').then(response => {
      if (stopping || !window || window.isDestroyed() || window.webContents.isDestroyed()) return;
      if (response.ok && response.data && typeof response.data === 'object') {
        const data = response.data as { url?: unknown; allowed_domains?: unknown };
        if (typeof data.url === 'string' && Array.isArray(data.allowed_domains) && data.allowed_domains.every(x => typeof x === 'string')) {
          external?.configure(data.url, data.allowed_domains);
          external?.setRunning(!!bridge?.latestState?.workflow?.session.running && !presentation.lost && !window?.isMinimized());
        }
      }
    }).catch(() => {}).finally(() => { configuringExternal = false; });
  }
}
async function geometryChanged(): Promise<void> {
  if (stopping || !window || window.isDestroyed() || !geometry || !bridge || bridge.status.state !== 'connected') return;
  const current = { ...geometry.snapshot(), fullscreen: window!.isFullScreen(), settled: !layoutSettling };
  const signature = `${current.geometry_id}:${current.fullscreen}:${current.settled}`;
  if (signature !== lastGeometry) {
    const changed = lastGeometryIdentity !== '' && lastGeometryIdentity !== current.geometry_id;
    lastGeometry = signature; lastGeometryIdentity = current.geometry_id;
    external?.intent({ action: 'hide' });
    if (changed && bridge.latestState?.protection.enabled && bridge.latestState.workflow?.session.started && !bridge.latestState.workflow.session.ended) {
      await bridge.host('host.safety_release', { reason: 'display_geometry_changed' });
    }
    await bridge.host('geometry.changed', { geometry: current });
  }
}
async function prepareProtectedGeometry(): Promise<boolean> {
  if (stopping || !window || window.isDestroyed() || layoutSettling) return false;
  layoutSettling = true;
  try {
    if (!window.isFullScreen()) {
      await new Promise<void>(resolve => {
        const finish = () => { clearTimeout(timeout); window?.removeListener('enter-full-screen', finish); resolve(); };
        const timeout = setTimeout(finish, 2000);
        window!.once('enter-full-screen', finish); window!.setFullScreen(true);
      });
    }
    // Require stable native geometry after the transition rather than treating
    // setFullScreen's request as completed target coordinates.
    if (stopping || !window || window.isDestroyed()) return false;
    const first = geometry!.snapshot().geometry_id;
    await new Promise(resolve => setTimeout(resolve, 120));
    if (stopping || !window || window.isDestroyed() || !window.isFullScreen() || geometry!.snapshot().geometry_id !== first) return false;
    layoutSettling = false;
    await geometryChanged(); return true;
  } finally { layoutSettling = false; }
}
async function losePresentation(): Promise<void> {
  external?.intent({ action: 'hide' });
  if (fixture || stopping || !presentation.lose()) return;
  deliveredSnapshots.clear();
  deliveredEventCursor = 0;
  if (bridge && !bridge.terminated) await bridge.host('presentation.lost');
}
async function connect(): Promise<void> {
  if (fixture || connecting || stopping) return;
  connecting = true;
  try {
    if (!bridge) {
      ensureRuntimeConfig(runtime);
      bridge = new PythonBridge(runtime.python, runtime.config, runtime.backendCwd, launchId, runtime.supervisorPrefix, app.isPackaged ? path.dirname(process.execPath) : undefined);
      bridge.onState = updateState;
      bridge.onDisconnected = () => { liveScreen?.stopLease('backend_disconnected'); external?.intent({ action: 'hide' }); presentation.lose(); };
      await bridge.start();
      if (!stopping && !bridge.terminated && window && !window.isDestroyed()) { liveScreen = new LiveScreen(window,bridge); if (bridge.latestState) liveScreen.update(bridge.latestState); }
    }
    // Reconcile an existing process only. Backend death never creates a new exam.
    if (stopping || bridge.terminated || !window || window.isDestroyed() || window.isMinimized()) return;
    const snapshot = await bridge.command('state.get');
    if (!snapshot.ok || stopping || !window || window.isDestroyed()) return;
    if (snapshot.result.protection.requested && !hostBound && window && !window.isDestroyed()) {
      // The independent native owner must register this chord itself. Main's
      // safe-mode shortcut cannot compete with or stand in for that recovery.
      globalShortcut.unregister('Control+Shift+Alt+Q');
      const binding = await bridge.host('host.bind', { launch_id: launchId, host_pid: process.pid,
        windows: [{ hwnd: nativeHandleHex(window.getNativeWindowHandle()), role: 'exam' }],
        runtime: { electron_version: process.versions.electron, app_version: app.getVersion(),
          build_kind: app.isPackaged ? 'packaged' : 'source', build_id: await desktopBuildFingerprint(path.resolve(__dirname, '..')) } });
      hostBound = binding.ok;
      if (!binding.ok || stopping || !window || window.isDestroyed()) return;
      // Unprotected preparation is normally escapable. Final geometry is set
      // before target collection, never silently changed at protected Start.
      window.setFullScreen(true);
    }
    // Presentation resumes only after renderer acknowledgement of a delivered
    // snapshot and durable event cursor; main liveness alone cannot resume it.
    await geometryChanged();
    if (bridge.latestState) updateState(bridge.latestState);
  } finally { connecting = false; }
}
async function stop(emergency = false): Promise<void> {
  if (stopping) return;
  stopping = true;
  liveScreen?.close(); liveScreen = undefined;
  if (presentationTimer) clearInterval(presentationTimer);
  presentationTimer = undefined;
  globalShortcut.unregisterAll();
  tray?.destroy(); tray = undefined;
  await finishShutdown({
    closePresentation: () => external?.close(),
    endSession: async () => { if (emergency && bridge && !bridge.terminated) await bridge.host('emergency.end'); },
    closeBackend: async () => { await bridge?.close(); },
    quit: () => app.quit(),
    reportErrors: errors => { console.error('Application shutdown encountered teardown errors', errors); process.exitCode = 1; },
  });
}

if (process.argv.includes('--recovery-fixture')) {
  void import('./recovery_fixture').then(m => m.runRecoveryFixture()).catch(() => app.quit());
} else if (process.argv.includes('--protected-fixture')) {
  void import('./protected_fixture').then(m => m.runProtectedFixture()).catch(error => { console.error(String(error)); app.quit(); });
} else if (process.argv.includes('--validate-electron-protection')) {
  void import('./recovery_audit').then(m => m.runRecoveryAudit()).catch(error => { console.error(String(error)); app.quit(); });
} else if (process.argv.includes('--validate-electron-short-protection')) {
  void import('./protected_audit').then(m => m.runProtectedAudit()).catch(error => { console.error(String(error)); app.quit(); });
} else if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (!stopping && window && !window.isDestroyed()) { window.restore(); window.focus(); } });
  app.whenReady().then(async () => {
    const isolated = session.fromPartition('local-proctoring-stage2');
    isolated.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
    isolated.setPermissionCheckHandler(() => false);
    isolated.on('will-download', event => event.preventDefault());
    isolated.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: {
      ...details.responseHeaders, 'Content-Security-Policy': [dev ? DEVELOPMENT_CSP : PRODUCTION_CSP],
    } }));
    window = new BrowserWindow({
      title: 'Local Proctoring', width: 1280, height: 800, minWidth: 480, minHeight: 400,
      backgroundColor: '#f8f6f1', autoHideMenuBar: true, show: false,
      webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
        nodeIntegration: false, sandbox: true, webSecurity: true, webviewTag: false,
        backgroundThrottling: false, session: isolated, additionalArguments: fixture ? ['--proctoring-fixture'] : [] },
    });
    external = new ExternalExam(window, () => { void stop(true); });
    geometry = new GeometryOwner(window);
    window.removeMenu();
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', event => event.preventDefault());
    window.webContents.on('will-redirect', event => event.preventDefault());
    window.webContents.on('will-attach-webview', event => event.preventDefault());
    window.webContents.on('before-input-event', (event, input) => {
      if (emergencyInput(input)) { event.preventDefault(); void stop(true); }
      else if (input.type === 'keyDown' && input.key === 'Escape' && !bridge?.latestState?.protection.enabled && window?.isFullScreen()) window.setFullScreen(false);
    });
    window.webContents.on('did-start-loading', () => { controlProgress.rendererReplaced(); if (bridge) void losePresentation(); });
    window.webContents.on('render-process-gone', () => { void losePresentation(); });
    window.on('unresponsive', () => { void losePresentation(); });
    window.on('minimize', () => { void losePresentation(); });
    window.on('resize', () => { void geometryChanged(); });
    window.on('move', () => { void geometryChanged(); });
    window.on('enter-full-screen', () => { void geometryChanged(); });
    window.on('leave-full-screen', () => { void geometryChanged(); });
    screen.on('display-metrics-changed', () => { void geometryChanged(); });
    screen.on('display-added', () => { void geometryChanged(); });
    screen.on('display-removed', () => { void geometryChanged(); });
    let pendingCloseDialog=false;
    window.on('close', event => {
      if (stopping) return;
      event.preventDefault();
      if (bridge?.latestState?.workflow?.session.started && !bridge.latestState.workflow.session.ended && !bridge.terminated) {
        external?.intent({ action: 'hide' }); window?.webContents.send('proctoring:request-end');
      } else if (pendingReceiptOnClose(bridge?.latestState) && !bridge?.terminated) {
        if(pendingCloseDialog)return;
        pendingCloseDialog=true;
        const locale=bridge?.latestState?.language??'en';
        const localized=(en:string,ru:string,kk:string)=>locale==='ru'?ru:locale==='kk'?kk:en;
        void dialog.showMessageBox(window!,{type:'warning',defaultId:0,cancelId:0,
          title:localized('Synchronization incomplete','Синхронизация не завершена','Синхрондау аяқталмады'),
          message:localized('A complete server receipt has not been verified. Keep this window open to finish synchronization. Exiting preserves pending evidence for the next launch.',
            'Полная квитанция сервера ещё не проверена. Оставьте окно открытым для завершения синхронизации. При выходе материалы сохранятся до следующего запуска.',
            'Сервердің толық түбіртегі әлі тексерілмеді. Синхрондау аяқталғанша терезені ашық қалдырыңыз. Шықсаңыз, материалдар келесі іске қосуға дейін сақталады.'),
          buttons:[localized('Keep open','Оставить открытым','Ашық қалдыру'),localized('Exit with evidence pending','Выйти с неотправленными материалами','Материалдар жіберілмей шығу')]
        }).then(result=>{if(result.response===1)void stop();}).finally(()=>{pendingCloseDialog=false;});
      } else void stop();
    });
    window.on('closed', () => {
      if (presentationTimer) clearInterval(presentationTimer);
      presentationTimer = undefined;
      if (!stopping && bridge && !bridge.terminated) void bridge.host('host.safety_release', { reason: 'host_window_destroyed' });
    });
    ipcMain.handle('proctoring:command', async (event, command, payload = {}) => {
      sender(event); const valid = validateCommand(command, payload);
      if (fixture || !bridge) return unavailable('backend_unavailable');
      if (command === 'sync.exit') {
        if (!bridge.latestState?.workflow?.session.ended) return unavailable('exam_not_ended');
        const result = await bridge.command('state.get');
        setImmediate(() => { void stop(); });
        return publicResult(result);
      }
      if (command === 'sync.background') {
        const result = await requestBackgroundUpload(bridge.latestState, () => bridge!.command('sync.background'), confirmed => {
          backgroundUpload = true; external?.close(); globalShortcut.unregisterAll();
          const pixels = Buffer.alloc(16*16*4); for (let i=0;i<pixels.length;i+=4) { pixels[i]=76;pixels[i+1]=124;pixels[i+2]=77;pixels[i+3]=255; }
          tray = new Tray(nativeImage.createFromBitmap(pixels, {width:16,height:16}));
          tray.setToolTip('Local Proctoring');
          const language = confirmed.language;
          const label = (en: string, ru: string, kk: string) => language === 'ru' ? ru : language === 'kk' ? kk : en;
          tray.setContextMenu(Menu.buildFromTemplate([
            { label: label('Show upload status','Показать состояние отправки','Жіберу күйін көрсету'), click: () => { window?.show(); } },
            { label: label('Exit completely','Выйти полностью','Толық шығу'), click: () => { void stop(); } },
          ]));
          tray.on('click', () => window?.show()); window?.hide();
        });
        return publicResult(result);
      }
      if (bridge.latestState?.protection.requested) {
        if (!hostBound && !['state.get', 'events.get'].includes(command)) return unavailable('host_binding_required');
        if (command === 'calibration.start' || (command === 'calibration.retry' && valid.payload.scope === 'baseline')) {
          if (!await prepareProtectedGeometry()) return unavailable('geometry_settlement_required');
        }
        if (command === 'exam.start' && (layoutSettling || !window?.isFullScreen())) return unavailable('geometry_preparation_required');
        if (command === 'exam.start') await geometryChanged();
      }
      if (valid.command === 'calibration.presented') {
        const current = { ...geometry!.snapshot(), fullscreen: window!.isFullScreen(), settled: !layoutSettling };
        if (valid.payload.geometry_id !== current.geometry_id) return unavailable('geometry_changed');
        return publicResult(await bridge.host('calibration.presented', { token: valid.payload.token, target: valid.payload.target, geometry: current }));
      }
      return publicResult(await bridge.command(valid.command as Command, valid.payload), command === 'events.get');
    });
    ipcMain.handle('proctoring:connection', event => { sender(event); return fixture ? { state: 'fixture' } : bridge?.status ?? { state: 'connecting' }; });
    ipcMain.handle('proctoring:control-progress', async (event, receipt) => {
      sender(event);
      if (fixture || !bridge || bridge.terminated || !hostBound || window?.isMinimized()) return { accepted: false };
      const delivered = deliveredSnapshots.get(receipt?.snapshot_seq);
      if (!delivered || delivered.session_id !== receipt.session_id) return { accepted: false };
      const progress = controlProgress.accept(receipt, bridge.latestState?.workflow?.session_id ?? null);
      if (!progress) return { accepted: false };
      const result = await bridge.host('host.progress', { ...progress, session_id: receipt.session_id, snapshot_seq: receipt.snapshot_seq });
      controlProgress.confirm(progress, result.ok);
      return { accepted: result.ok };
    });
    ipcMain.handle('proctoring:preview', event => { sender(event); return !fixture && bridge?.status.state === 'connected' ? bridge.preview.next() : null; });
    ipcMain.handle('proctoring:reconnect', async event => { sender(event); await connect(); return fixture ? { state: 'fixture' } : bridge?.status ?? { state: 'disconnected' }; });
    ipcMain.handle('proctoring:acknowledge-presentation', async (event, receipt) => {
      sender(event);
      if (fixture || !bridge || !receipt || typeof receipt !== 'object' || Object.keys(receipt).sort().join(',') !== 'event_cursor,session_id,snapshot_seq' ||
          !Number.isSafeInteger(receipt.snapshot_seq) || !Number.isSafeInteger(receipt.event_cursor) || receipt.event_cursor < 0 || window?.isMinimized()) return unavailable('invalid_presentation_receipt');
      const delivered = deliveredSnapshots.get(receipt.snapshot_seq);
      if (!delivered || delivered.session_id !== receipt.session_id || receipt.event_cursor < delivered.cursor || receipt.event_cursor > deliveredEventCursor) return unavailable('resynchronize_snapshot_and_events');
      const generation = presentation.beginSync();
      if (generation === null) return unavailable('presentation_sync_in_progress');
      let completed = false;
      try {
        const result = await bridge.host('presentation.sync', { session_id: receipt.session_id, event_cursor: receipt.event_cursor });
        const accepted = presentation.finishSync(generation, result.ok); completed = true;
        if (accepted && result.ok) updateState(result.result);
        return publicResult(result);
      } finally { if (!completed) presentation.finishSync(generation, false); }
    });
    ipcMain.handle('proctoring:geometry', event => { sender(event); return geometry!.snapshot(); });
    ipcMain.handle('proctoring:external', (event, intent) => {
      sender(event); const valid = validateExternal(intent);
      return fixture ? { configured: false, state: 'idle', visible: false, message: 'Fixture mode has no remote exam' } satisfies ExternalStatus : external!.intent(valid);
    });
    ipcMain.handle('proctoring:evidence', async (event, intent) => {
      sender(event); const valid = validateEvidence(intent);
      if (fixture || !bridge || !window) return { ok: false, error: 'Evidence is unavailable' };
      const { action: _action, ...request } = valid;
      const response = await bridge.host('host.evidence', request);
      return response.ok ? actOnEvidence(window, valid, response.data) : { ok: false, error: response.error.message };
    });
    globalShortcut.register('Control+Shift+Alt+Q', () => { void stop(true); });
    presentationTimer = setInterval(() => {
      if (stopping || !window || window.isDestroyed()) return;
      if (backgroundUpload) { void bridge?.command('state.get').catch(() => {}); return; }
      external?.tick(); if (!fixture && Date.now() - lastRendererRequest > 3000) void losePresentation();
    }, 250); presentationTimer.unref();
    await window.loadURL(rendererUrl);
    if (!stopping && window && !window.isDestroyed()) { window.show(); await connect(); }
  }).catch(() => { void stop(); });
  app.on('before-quit', event => { if (!stopping) { event.preventDefault(); void stop(); } });
  app.on('window-all-closed', () => { void stop(); });
}
