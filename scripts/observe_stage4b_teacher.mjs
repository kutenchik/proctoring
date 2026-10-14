// Run on the remote teacher computer only after explicit physical/public approval.
// Opens an isolated ephemeral browser. Operator logs in and controls all actions.
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile, appendFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { ViewerClock } from './stage4b-viewer-clock.mjs';
const arg = name => process.argv[process.argv.indexOf(name) + 1];
if (process.argv.includes('--help')) {
  console.log('node scripts/observe_stage4b_teacher.mjs --operator-approved --origin https://<assigned>.trycloudflare.com --deadline <epoch milliseconds> --output <NEW directory>'); process.exit(0);
}
if (!process.argv.includes('--operator-approved')) throw Error('Separate operator approval required');
const origin = arg('--origin'), deadline = Number(arg('--deadline')), output = arg('--output');
if (!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(origin ?? '') || !output || !Number.isFinite(deadline) || deadline <= Date.now() || deadline - Date.now() > 1800000) throw Error('Exact origin, new output directory and remaining <=30 minute deadline required');
await mkdir(output); // refuse to overwrite any earlier run
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(repo, 'teacher-web/package.json'));
const { chromium } = require('playwright');
const remaining = deadline - Date.now(), began = performance.now();
const clock = new ViewerClock({ overallStart: 0, overallMs: remaining });
let browser, samples = 0, failureSaved = false, expectedNetworkViewer = null, networkWindowUsed = false;
const save = (file, value) => writeFile(path.join(output, file), JSON.stringify(value, null, 2));
// Independent wall-clock cap also covers a hung navigation/poll; never starts a viewer.
const cap = setTimeout(() => { void browser?.close(); }, remaining);
try {
  browser = await chromium.launch({ channel: 'msedge', headless: false });
  const context = await browser.newContext(); // no saved login, tracing, video or HAR
  const page = await context.newPage();
  await page.goto(origin, { timeout: 30000 });
  console.log('Operator: log in manually, use English UI, select disposable student. Start only on coordinator signal.');
  while (performance.now() - began < remaining && samples < 1800) {
    const raw = await page.evaluate(() => {
      const panel = document.querySelector('[data-stream-observation]');
      if (!panel) return null;
      const value = JSON.parse(panel.getAttribute('data-stream-observation'));
      const delivery = JSON.parse(panel.getAttribute('data-stream-metrics') || 'null');
      return { value, delivery, age: delivery?.firstPresentedAt == null ? null : performance.now() - delivery.firstPresentedAt,
        canvas_visible: panel.querySelector('canvas')?.style.visibility === 'visible' };
    });
    const now = performance.now() - began;
    const code = v => typeof v === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(v) ? v : null;
    const num = v => Number.isFinite(v) && v >= 0 ? v : null;
    const v = raw?.value;
    const record = { at: Date.now(), observer_ms: now, viewer_id: code(v?.viewer_id), state: code(v?.state), reason: code(v?.reason), transport: code(v?.transport),
      frames: num(raw?.delivery?.frames), firstPresentedAt: raw?.age == null ? null : now - raw.age,
      ack_roundtrip_ms: num(v?.quality?.ack_roundtrip_ms), canvas_visible: raw?.canvas_visible === true };
    // One operator-marked interruption. Never excuses privacy/auth failures.
    let control; try { control = JSON.parse(await readFile(path.join(output, 'control.json'), 'utf8')); } catch {}
    if (!networkWindowUsed && control?.action === 'network_interrupt' && Number.isFinite(control.at) && Date.now() >= control.at && Date.now() - control.at < 30000 && record.viewer_id) {
      networkWindowUsed = true; expectedNetworkViewer = record.viewer_id;
      await save('planned-network.json', { at: Date.now(), viewer_id: expectedNetworkViewer });
    }
    record.expected_network = record.viewer_id === expectedNetworkViewer;
    const timing = clock.sample(now, record);
    if (record.state === 'unavailable' && record.expected_network && record.reason === 'connection_lost') {
      // Exclusive create preserves the first expected disconnect as well.
      await writeFile(path.join(output, 'planned-network-first-disconnect.json'), JSON.stringify(record, null, 2), { flag: 'wx' }).catch(error => { if (error.code !== 'EEXIST') throw error; });
    }
    await appendFile(path.join(output, 'metrics.jsonl'), JSON.stringify({ ...record, timing }) + '\n'); samples++;
    if (clock.firstFailure && !failureSaved) { await save('first-failure.json', { ...record, timing }); failureSaved = true; }
    if (timing.stop) { await save('observation-stop.json', { reason: timing.stop, at: Date.now(), viewer_id: record.viewer_id }); break; }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
} finally {
  clearTimeout(cap); await browser?.close();
  await save('cleanup.json', { at: Date.now(), samples, closed: true, first_failure: clock.firstFailure });
}
