// Test harness, not an application authority. Never opens capture or starts an exam.
import { _electron as electron } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
const live = process.argv.includes('--live');
const output = path.resolve('../artifacts/electron-stage1');
await mkdir(output, { recursive: true });
const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE; delete env.PROCTORING_DEV_URL;
const application = await electron.launch({ args: ['.', ...(live ? [] : ['--fixture'])], env, timeout: 30000 });
let closed = false;
application.on('close', () => { closed = true; });
const page = await application.firstWindow();
await page.waitForSelector('h1');
const preferences = await application.evaluate(({ BrowserWindow }) => {
  const prefs = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
  return { nodeIntegration: prefs.nodeIntegration, contextIsolation: prefs.contextIsolation, sandbox: prefs.sandbox, webviewTag: prefs.webviewTag };
});
const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content');
if (preferences.nodeIntegration || !preferences.contextIsolation || !preferences.sandbox || !csp?.includes("script-src 'self'")) throw new Error('Security configuration mismatch');
await page.screenshot({ path: path.join(output, live ? 'native-live-before-capture.png' : 'native-fixture.png') });
console.log(JSON.stringify({ mode: live ? 'live' : 'fixture', preferences, csp }));
if (!live) {
  const connection = await page.evaluate(() => window.proctoring.connection());
  if (connection.state !== 'fixture') throw new Error('Fixture mode connected a backend');
  const result = await page.evaluate(() => window.proctoring.command('camera.start'));
  if (result.ok) throw new Error('Fixture opened capture');
  // Packaged file-page CSP must block script elements, not merely exist as text.
  const blocked = await page.evaluate(async () => {
    window.__cspProbe = false;
    const script = document.createElement('script'); script.textContent = 'window.__cspProbe = true';
    document.head.append(script);
    await new Promise(resolve => setTimeout(resolve, 30));
    return !window.__cspProbe;
  });
  if (!blocked) throw new Error('Production inline-script CSP is not enforced');
  await writeFile(path.join(output, 'native-fixture-result.json'), JSON.stringify({ preferences, csp, fixtureIsolated: true, inlineScriptBlocked: blocked }, null, 2));
  await application.close();
  console.log('Native fixture startup, bridge isolation, enforced CSP and shutdown passed.');
} else {
  const history = []; let signature = ''; let last = null;
  for (let tick = 0; tick < 1200 && !closed; tick++) {
    try {
      const response = await page.evaluate(() => window.proctoring.command('state.get'));
      if (response.ok) {
        const s = response.result;
        last = { connected: s.connected, protection: s.protection, consent: s.consent_accepted,
          camera: s.camera, audio: s.audio, device_counts: { cameras: s.devices.cameras.length, microphones: s.devices.microphones.length } };
        // Capture status only; no candidate details, config secrets or media.
        const next = JSON.stringify([s.camera.selected_key, s.camera.state, s.camera.preview_sequence !== null,
          s.audio.selected_key, s.audio.check.state, s.audio.check.committed_threshold, s.audio.running]);
        if (signature !== next) { signature = next; history.push(last); console.log(JSON.stringify(last)); }
        await writeFile(path.join(output, 'native-live-result.json'), JSON.stringify({ latest: last, history }, null, 2));
      }
    } catch { if (closed) break; }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  if (!closed) await application.close();
  console.log('Native operator window closed; final numerical result saved.');
}
