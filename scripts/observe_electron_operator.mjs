// Operator-only observer. No exam actions, PIN entry, calibration bypass or media capture.
// Kept in root scripts/: native source fingerprint includes desktop/scripts/, not this directory.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { appendFile, mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import os from 'node:os';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(repo, 'desktop/package.json'));
const { _electron: electron } = require('playwright');
const run = promisify(execFile);
const option = name => { const index = process.argv.indexOf(name); return index < 0 ? null : process.argv[index + 1]; };
if (process.argv.includes('--help')) {
  console.log('node scripts/observe_electron_operator.mjs --config <absolute protected TOML> [--exe <copied LocalProctoring.exe>] [--output <directory>] [--summary-screenshot]');
  console.log('Launches normal app only. Complete all gates manually. Exit using normal End session/PIN and close. No images saved unless summary-statistics crop explicitly enabled.');
  process.exit(0);
}
const configArg = option('--config');
if (!configArg || configArg.startsWith('--')) throw new Error('An explicit --config is required');
const config = path.resolve(configArg);
const configText = await readFile(config, 'utf8');
let section = ''; let explicitlyProtected = false;
for (const line of configText.split(/\r?\n/)) {
  const header = /^\s*\[([^\]]+)\]\s*(?:#.*)?$/.exec(line);
  if (header) section = header[1];
  if (section === 'protection' && /^\s*enabled\s*=\s*true\s*(?:#.*)?$/.test(line)) explicitlyProtected = true;
}
if (!explicitlyProtected) throw new Error('Observer requires an explicitly enabled [protection] config; it will not rewrite one');
const exe = option('--exe') ? path.resolve(option('--exe')) : undefined;
const output = path.resolve(option('--output') || path.join(repo, 'artifacts/electron-stage3-operator', new Date().toISOString().replace(/[:.]/g, '-')));
await mkdir(output, { recursive: true });
const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE; delete env.PROCTORING_DEV_URL;
if (exe) {
  delete env.PROCTORING_PYTHON; delete env.PYTHONPATH; delete env.PYTHONHOME;
  delete env.PROCTORING_PACKAGE_ROOT; delete env.PROCTORING_HOST_LAUNCH_ID;
  delete env.PROCTORING_BACKEND_NONCE;
}
const started = performance.now();
const application = await electron.launch({ ...(exe ? { executablePath: exe } : {}),
  args: [...(exe ? [] : [path.join(repo, 'desktop')]), '--config', config], cwd: exe ? path.dirname(exe) : path.join(repo, 'desktop'), env, timeout: 60000 });
let closed = false; application.on('close', () => { closed = true; });
const child = application.process(); const rootPid = child.pid;
const page = await application.firstWindow();
await page.waitForFunction(() => !!window.proctoring, null, { timeout: 60000 });
const startup = { first_window_bridge_ms: performance.now() - started, first_authoritative_state_ms: null };
const limitations = [
  'Observer uses existing public state.get/events.get only; it never acknowledges native control challenges or starts/resumes/ends a session.',
  'Observer traffic does refresh presentation-traffic bookkeeping: this is not a renderer-poll-loss, crash or watchdog audit.',
  'Pause intervals are observed at about 1-second granularity; the backend monotonic exam timer remains authoritative.',
  'Working-set sum covers observed Electron/Python/helper/guardian descendants and double-counts shared pages; it is not unique physical RAM.',
  'Resource polling and Playwright add overhead; observer Node/PowerShell memory is outside the measured application tree.',
  'Startup includes automation launch/attachment overhead. The copied EXE still uses its own bundled backend and normal production gates.',
  'The observer uses repository Playwright tooling; that tooling is not an application runtime dependency. Packaged launches strip developer Python/path overrides.',
];
let latest = null, journalCursor = 0, journalSession = null, readErrors = 0, metricErrors = 0, capturedSummary = false;
const history = [], pauses = [], pauseStarts = new Map(), knownProcesses = new Map();
let signature = '', resourceBusy = false, previousResourceAt = null, peakWorkingSet = 0, peakPrivateBytes = 0;
const cpuLast = new Map();
const code = value => typeof value === 'string' && /^[a-zA-Z0-9_:-]{1,160}$/.test(value) ? value : null;
const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
const summarizeEvent = event => ({ record_kind: code(event.record_kind), event_id: code(event.event_id), event_type: code(event.event_type),
  action: code(event.action), state: code(event.state), timestamp: typeof event.timestamp === 'string' ? event.timestamp : null,
  duration_seconds: number(event.duration_seconds), activity_seconds: number(event.activity_seconds), elapsed_seconds: number(event.elapsed_seconds),
  confidence: number(event.confidence), snapshot_available: !!(event.snapshot_path || event.snapshot) });
const save = async () => {
  const file = path.join(output, 'operator-result.json');
  await writeFile(file + '.partial', JSON.stringify({ schema: 1, launched_mode: exe ? 'packaged' : 'source', config_path: config, root_pid: rootPid,
    startup, latest, history, pauses, read_errors: readErrors, resource_errors: metricErrors, native_closed: closed,
    peak_working_set_sum_bytes: peakWorkingSet, peak_private_bytes_sum: peakPrivateBytes, journal_cursor_observed: journalCursor,
    summary_statistics_screenshot: capturedSummary, limitations }, null, 2));
  await rename(file + '.partial', file);
};
const metrics = async () => {
  if (resourceBusy || closed) return; resourceBusy = true;
  try {
    const { stdout } = await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', path.join(repo, 'scripts/observe_electron_resources.ps1')],
      { windowsHide: true, timeout: 10000, maxBuffer: 4 * 1024 * 1024 });
    const all = JSON.parse(stdout); const at = performance.now(); const byPid = new Map(all.map(row => [row.pid, row]));
    const root = byPid.get(rootPid);
    if (!root) return;
    if (knownProcesses.has(rootPid) && knownProcesses.get(rootPid) !== root.created) throw new Error('Observed root PID identity changed');
    knownProcesses.set(rootPid, root.created);
    let changed = true;
    while (changed) {
      changed = false;
      for (const row of all) {
        const parent = byPid.get(row.parent);
        if (parent && knownProcesses.get(parent.pid) === parent.created && row.created >= parent.created && knownProcesses.get(row.pid) !== row.created) {
          knownProcesses.set(row.pid, row.created); changed = true;
        }
      }
    }
    const owned = all.filter(row => knownProcesses.get(row.pid) === row.created);
    let cpuDelta = 0;
    for (const row of owned) {
      const key = `${row.pid}:${row.created}`, total = row.cpu_100ns;
      if (cpuLast.has(key)) cpuDelta += Math.max(0, total - cpuLast.get(key));
      cpuLast.set(key, total);
    }
    const working = owned.reduce((sum, row) => sum + row.working_set_bytes, 0);
    const privateBytes = owned.reduce((sum, row) => sum + row.private_bytes, 0);
    peakWorkingSet = Math.max(peakWorkingSet, working); peakPrivateBytes = Math.max(peakPrivateBytes, privateBytes);
    const sample = { observer_seconds: (at - started) / 1000, process_count: owned.length,
      working_set_sum_bytes: working, private_bytes_sum: privateBytes,
      cpu_percent_machine: previousResourceAt === null ? null : 100 * (cpuDelta / 1e7) / ((at - previousResourceAt) / 1000) / os.availableParallelism(),
      processes: owned };
    previousResourceAt = at;
    await appendFile(path.join(output, 'resources.jsonl'), JSON.stringify(sample) + '\n');
  } catch { metricErrors++; } finally { resourceBusy = false; }
};
const resources = setInterval(() => { void metrics(); }, 3000); void metrics();
console.log(JSON.stringify({ stage: 'operator_ready', output, root_pid: rootPid,
  note: 'Use the normal registration/selfie/microphone/gaze flow. Start, pause/resume and End/PIN are operator actions. Observer will not close an active session.' }));
try {
  while (!closed) {
    try {
      const response = await page.evaluate(() => window.proctoring.command('state.get'));
      if (response.ok && response.result.workflow) {
        const s = response.result, w = s.workflow, now = performance.now();
        if (startup.first_authoritative_state_ms === null) startup.first_authoritative_state_ms = now - started;
        latest = { observer_seconds: (now - started) / 1000, session_id: code(w.session_id), step: code(w.step), snapshot_seq: w.snapshot_seq,
          protection: { requested: s.protection.requested, enabled: s.protection.enabled, state: code(s.protection.state), reason: code(s.protection.reason), audit_valid: s.protection.audit?.valid },
          camera: { state: s.camera.state, width: s.camera.source_width, height: s.camera.source_height, fps: s.camera.fps, frame_age_seconds: s.camera.frame_age_seconds },
          audio: { running: s.audio.running, state: code(s.audio.check.state), gain: number(s.audio.check.gain), threshold: number(s.audio.check.committed_threshold),
            gain_limited: s.audio.check.gain_limited, level: number(s.audio.processed_level), frame_age_seconds: number(s.audio.frame_age_seconds) },
          reference_ready: w.reference.ready, calibration: { phase: code(w.calibration.phase), target: code(w.calibration.target), ready: w.calibration.ready, accepted_samples: w.calibration.accepted_samples },
          monitoring: { healthy: w.monitoring.healthy, reason: code(w.monitoring.reason), fps: w.monitoring.fps, latency_ms: w.monitoring.latency_ms },
          session: { started: w.session.started, ended: w.session.ended, running: w.session.running, elapsed_seconds: w.session.elapsed_seconds,
            remaining_seconds: w.session.remaining_seconds, pause_reasons: w.session.pause_reasons.map(code).filter(Boolean), recovery_pin_required: w.session.recovery_pin_required, end_reason: code(w.session.end_reason) },
          answered_count: w.quiz.answered, event_cursor: w.events.cursor, events: w.events.records.map(summarizeEvent), report: { status: code(w.report.status), available: w.report.available } };
        const activeReasons = new Set(latest.session.started && !latest.session.ended ? latest.session.pause_reasons : []);
        if (activeReasons.size) activeReasons.add('ANY_PAUSE');
        for (const reason of activeReasons) if (!pauseStarts.has(reason)) pauseStarts.set(reason, now);
        for (const [reason, began] of pauseStarts) if (!activeReasons.has(reason)) { pauses.push({ reason, observed_start_seconds: (began - started) / 1000, observed_duration_seconds: (now - began) / 1000 }); pauseStarts.delete(reason); }
        const next = JSON.stringify([latest.step, latest.protection, latest.audio.state, latest.reference_ready, latest.calibration, latest.session.running, latest.session.ended, latest.session.pause_reasons, latest.answered_count, latest.events.map(e => [e.event_id, e.action, e.state]), latest.report]);
        if (next !== signature) { signature = next; history.push(latest); console.log(JSON.stringify(latest)); }
        await appendFile(path.join(output, 'states.jsonl'), JSON.stringify(latest) + '\n');
        if (w.session_id !== journalSession) { journalSession = w.session_id; journalCursor = 0; }
        if (journalSession && journalCursor < w.events.cursor) {
          const journal = await page.evaluate(after => window.proctoring.command('events.get', { after, limit: 100 }), journalCursor);
          if (journal.ok && journal.data) {
            for (const item of journal.data.records) await appendFile(path.join(output, 'event-history.jsonl'), JSON.stringify({ sequence: item.sequence, ...summarizeEvent(item.record) }) + '\n');
            journalCursor = journal.data.cursor;
          }
        }
        if (process.argv.includes('--summary-screenshot') && !capturedSummary && w.step === 'summary' && w.session.ended && await page.locator('.summary-stats').count()) {
          // Crop only existing non-media statistics; no candidate, preview or snapshots.
          await page.locator('.summary-stats').screenshot({ path: path.join(output, 'summary-statistics.png') }); capturedSummary = true;
        }
        await save();
      } else readErrors++;
    } catch { if (!closed) readErrors++; }
    if (!closed) await new Promise(resolve => setTimeout(resolve, 1000));
  }
} finally {
  clearInterval(resources);
  while (resourceBusy) await new Promise(resolve => setTimeout(resolve, 50));
  for (const [reason, began] of pauseStarts) pauses.push({ reason, observed_start_seconds: (began - started) / 1000, observed_duration_seconds: (performance.now() - began) / 1000, ended_by_application_close: true });
  await save();
  console.log(JSON.stringify({ stage: 'operator_closed', ended: latest?.session.ended ?? false, output }));
}
