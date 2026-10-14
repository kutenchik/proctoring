import { BrowserWindow, WebContentsView, session, type Input, type WebContents } from 'electron';
import { randomUUID } from 'node:crypto';
import type { ExternalIntent, ExternalStatus } from '../shared/contracts';
import { ExamNavigationPolicy, safeExternalBounds } from './external_policy';

/** A native remote page, isolated from the trusted UI and its preload. */
export class ExternalExam {
  private view?: WebContentsView;
  private contents?: WebContents;
  private policy?: ExamNavigationPolicy;
  private running = false;
  private layout?: Extract<ExternalIntent, { action: 'layout' }>;
  private layoutAt = 0;
  private loaded = false;
  private state: ExternalStatus = { configured: false, state: 'idle', visible: false, message: '' };
  private timeout?: NodeJS.Timeout;
  private disposed = false;
  private readonly ownerClosed = () => this.close();
  constructor(private window: BrowserWindow, private emergency: () => void) { window.once('closed', this.ownerClosed); }
  configure(url: string, hosts: string[]): void {
    if (this.disposed || this.view) return;
    if (this.window.isDestroyed() || this.window.webContents.isDestroyed()) { this.close(); return; }
    this.policy = new ExamNavigationPolicy(url, hosts);
    const isolated = session.fromPartition(`exam-${randomUUID()}`);
    isolated.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    isolated.setPermissionCheckHandler(() => false);
    isolated.setDevicePermissionHandler(() => false);
    isolated.on('will-download', event => { event.preventDefault(); this.blocked('Downloads are blocked'); });
    isolated.webRequest.onBeforeRequest((details, callback) => {
      const document = details.resourceType === 'mainFrame' || details.resourceType === 'subFrame';
      const allowed = !this.disposed && (!document || this.policy!.allows(details.url));
      if (!allowed) this.blocked('Navigation outside exam domain is blocked');
      callback({ cancel: !allowed });
    });
    this.view = new WebContentsView({ webPreferences: { session: isolated, nodeIntegration: false,
      contextIsolation: true, sandbox: true, webSecurity: true, webviewTag: false,
      devTools: false, navigateOnDragDrop: false, safeDialogs: true, disableDialogs: true } });
    const wc = this.view.webContents;
    this.contents = wc;
    const guard = (event: Electron.Event & { url: string }) => {
      if (!this.policy!.allows(event.url)) { event.preventDefault(); this.blocked('Navigation outside exam domain is blocked'); }
    };
    wc.on('will-frame-navigate', guard);
    wc.on('will-redirect', guard);
    wc.setWindowOpenHandler(() => { this.blocked('Opening additional browser windows is blocked'); return { action: 'deny' }; });
    wc.on('will-attach-webview', event => event.preventDefault());
    wc.on('select-bluetooth-device', (event, _devices, callback) => { event.preventDefault(); callback(''); });
    wc.on('context-menu', () => {}); // No application/context menu is attached.
    wc.on('before-input-event', (event, input) => {
      if (this.disposed) return;
      if (emergencyInput(input)) { event.preventDefault(); this.emergency(); }
      else if (input.key === 'F12' || (input.control && input.shift && input.key.toLowerCase() === 'i')) event.preventDefault();
    });
    wc.on('did-start-loading', () => { if (this.disposed) return; this.state.state = 'loading'; this.state.message = ''; this.armTimeout(); });
    wc.on('did-finish-load', () => { if (this.disposed) return; this.clearTimeout(); this.state.state = 'ready'; this.state.message = ''; });
    wc.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
      if (!this.disposed && mainFrame && code !== -3) { this.clearTimeout(); this.state.state = 'failed'; this.state.message = 'Exam page failed to load. Check the network and reload.'; }
    });
    wc.on('render-process-gone', () => { if (this.disposed) return; this.state.state = 'failed'; this.state.message = 'Exam page process stopped. Reload to retry; unsaved page answers may be lost.'; this.hide(); });
    wc.once('destroyed', () => this.close());
    wc.on('content-bounds-updated', event => event.preventDefault());
    this.window.contentView.addChildView(this.view);
    this.view.setVisible(false);
    this.state.configured = true;
  }
  private blocked(message: string): void { if (!this.disposed) { this.state.state = 'blocked'; this.state.message = message; } }
  private armTimeout(): void { this.clearTimeout(); if (this.disposed) return; this.timeout = setTimeout(() => {
    if (!this.disposed) { this.state.state = 'failed'; this.state.message = 'Exam page loading timed out. Reload to retry.'; }
  }, 30000); this.timeout.unref(); }
  private clearTimeout(): void { if (this.timeout) clearTimeout(this.timeout); this.timeout = undefined; }
  setRunning(running: boolean): void {
    if (this.disposed) return;
    this.running = running;
    if (this.contents?.isDestroyed()) { this.close(); return; }
    if (running && this.contents && !this.loaded) {
      this.loaded = true;
      void this.contents.loadURL(this.policy!.url).catch(() => {});
    }
    this.applyLayout();
  }
  intent(intent: ExternalIntent): ExternalStatus {
    if (this.disposed) return this.status;
    if (intent.action === 'layout') { this.layout = intent; this.layoutAt = Date.now(); this.applyLayout(); }
    if (intent.action === 'hide') { this.layout = undefined; this.hide(); }
    if (this.contents?.isDestroyed()) { this.close(); return this.status; }
    if (intent.action === 'reload' && this.running && this.contents) { this.contents.reload(); }
    if (intent.action === 'focus' && this.state.visible && this.contents) this.contents.focus();
    return this.status;
  }
  tick(): void { this.applyLayout(); }
  private applyLayout(): void {
    if (this.disposed) return;
    if (this.window.isDestroyed() || this.window.webContents.isDestroyed()) { this.close(); return; }
    if (!this.view) return; // Native quiz has no native page and needs no geometry.
    if (!this.contents || this.contents.isDestroyed()) { this.close(); return; }
    const [width, height] = this.window.getContentSize();
    const bounds = this.layout ? safeExternalBounds(this.layout.bounds, { width, height }, this.window.webContents.getZoomFactor()) : null;
    if (!this.view || !this.running || !this.layout?.visible || this.layout.modal || Date.now() - this.layoutAt > 1800 || !bounds || this.window.isMinimized()) { this.hide(); return; }
    this.view.setBounds(bounds); this.view.setVisible(true); this.state.visible = true;
  }
  hide(): void {
    if (this.disposed) return;
    if (this.window.isDestroyed() || this.window.webContents.isDestroyed() || this.contents?.isDestroyed()) { this.close(); return; }
    const restoreFocus = this.state.visible && !!this.contents && !this.contents.isDestroyed() && this.contents.isFocused();
    this.view?.setVisible(false); this.state.visible = false;
    if (restoreFocus && !this.window.isDestroyed() && !this.window.webContents.isDestroyed()) this.window.webContents.focus();
  }
  /** Main-process owned view only; never included in a renderer IPC result. */
  get ownedContents() { return this.disposed ? undefined : this.contents; }
  get status(): ExternalStatus { return { ...this.state, state: !this.state.visible && this.state.state === 'ready' ? 'hidden' : this.state.state }; }
  close(): void {
    if (this.disposed) return;
    this.disposed = true; this.clearTimeout(); this.window.removeListener('closed', this.ownerClosed);
    const view = this.view, contents = this.contents;
    this.view = undefined; this.contents = undefined; this.layout = undefined; this.loaded = false; this.running = false;
    this.state = { configured: false, state: 'idle', visible: false, message: '' };
    if (view) {
      // Native owner destruction can precede an already queued tick/close.
      // Closing our webContents is still necessary when its parent is gone.
      try {
        if (!this.window.isDestroyed()) {
          const restoreFocus = !!contents && !contents.isDestroyed() && contents.isFocused();
          view.setVisible(false); this.window.contentView.removeChildView(view);
          if (restoreFocus && !this.window.webContents.isDestroyed()) this.window.webContents.focus();
        }
      } finally {
        if (contents && !contents.isDestroyed()) contents.close({ waitForBeforeUnload: false });
      }
    }
  }
}
export function emergencyInput(input: Pick<Input, 'key' | 'control' | 'shift' | 'alt' | 'type'>): boolean {
  return input.type === 'keyDown' && input.control && input.shift && input.alt && input.key.toLowerCase() === 'q';
}
