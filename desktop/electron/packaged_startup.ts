import { app, BrowserWindow, dialog } from 'electron';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { runOwnedAudit } from '../scripts/owned-audit.mjs';
import { authorizeStartup, type Inspection } from './startup_gate';
import { securityHtml, securityStrings, auditStageLabel } from './startup_screen';
import { desktopBuildFingerprint } from './host_binding';
import { ensureRuntimeConfig, type resolveRuntime } from './runtime';

async function inspectBackend(executable: string, args: string[], cwd: string): Promise<Inspection> {
  const child = spawn(executable, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '', failed = false;
  child.stdout.on('data', chunk => { output += chunk.toString('utf8'); if (output.length > 1024*1024) { failed = true; output = ''; } });
  child.stderr.on('data', () => { /* Drain until close, including backend diagnostics. */ });
  child.on('error', () => { failed = true; });
  const code = await new Promise(resolve => child.on('close', resolve));
  if (failed || code !== 0) throw Error('Trusted package/configuration verification failed');
  return JSON.parse(output);
}

export async function packagedStartup(runtime: ReturnType<typeof resolveRuntime>): Promise<boolean> {
  const screen = new BrowserWindow({ width: 720, height: 540, backgroundColor: '#f8f6f1', autoHideMenuBar: true,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  screen.removeMenu();
  screen.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  screen.webContents.on('will-navigate', event => event.preventDefault());
  const cancellation = new AbortController();
  screen.webContents.on('render-process-gone', () => cancellation.abort());
  screen.on('close', event => { event.preventDefault(); cancellation.abort(); });
  screen.webContents.on('before-input-event', (_event, input) => {
    if (input.control && input.shift && input.alt && input.key.toLowerCase() === 'q') cancellation.abort();
  });
  const quit = (event: Electron.Event) => { event.preventDefault(); cancellation.abort(); };
  app.on('before-quit', quit);
  let language = app.getLocale().split('-')[0];
  await screen.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(securityHtml(language)));
  try {
    ensureRuntimeConfig(runtime);
    const hostRuntime = { electron_version: process.versions.electron, app_version: app.getVersion(),
      build_kind: 'packaged', build_id: await desktopBuildFingerprint(runtime.appRoot) };
    const inspect = async (report?: string) => {
      if (report) await screen.webContents.executeJavaScript(`document.getElementById('stage').textContent=${JSON.stringify(securityStrings(language)[5])}`);
      const result = await inspectBackend(runtime.python, ['--packaged-startup-check', '--config', runtime.config,
        '--host', process.execPath, '--runtime', JSON.stringify(hostRuntime), ...(report ? ['--report', report] : [])], runtime.backendCwd);
      return result;
    };
    const portableIdentity = process.env.LOCAL_PROCTOR_PORTABLE_SHA256;
    if (!portableIdentity || !/^[a-f0-9]{64}$/.test(portableIdentity)) throw Error('Launch the verified portable student EXE');
    return await authorizeStartup({ directory: path.join(runtime.writable, 'audits', 'history'), portableIdentity, inspect,
      cancelled: () => cancellation.signal.aborted,
      confirmRetry: async reason => {
        const t = securityStrings(language);
        const answer = await dialog.showMessageBox(screen, { type: 'warning', title: t[0], message: t[7], detail: reason,
          buttons: [t[9], t[8]], defaultId: 0, cancelId: 0 });
        return answer.response === 1;
      },
      run: async report => {
        await mkdir(path.dirname(report), { recursive: true });
        const completed = new Set<string>();
        return runOwnedAudit(process.execPath, ['--validate-electron-protection', '--native-input', '--config', runtime.config,
          '--audit-output', report, '--user-data-dir', `${report}.profile`], {
          cwd: runtime.backendCwd, record: `${report}.launcher.json`, signal: cancellation.signal,
          onStage: name => {
            void screen.webContents.executeJavaScript(`document.getElementById('stage').textContent=${JSON.stringify(auditStageLabel(name, language))}`).catch(() => cancellation.abort());
          },
          onProgress: value => {
            completed.add(value.native_audit);
            void screen.webContents.executeJavaScript(`document.getElementById('count').textContent=${JSON.stringify(`${completed.size} / 21`)};document.getElementById('progress').value=${completed.size}`).catch(() => cancellation.abort());
          },
        });
      },
    });
  } catch (error) {
    const t = securityStrings(language);
    if (!cancellation.signal.aborted) await dialog.showMessageBox(screen, { type: 'error', title: t[0], message: t[6], detail: String(error), buttons: [t[9]] });
    return false;
  } finally {
    app.removeListener('before-quit', quit);
    screen.destroy();
  }
}
