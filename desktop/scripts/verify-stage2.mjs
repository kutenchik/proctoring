// Operator-assisted production-gate run. This harness never starts/captures/calibrates/submits.
import { _electron as electron } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const repo = path.resolve('..');
const output = path.join(repo, 'artifacts/electron-stage2');
const python = process.env.PROCTORING_PYTHON || path.join(repo, '.venv/Scripts/python.exe');
const safeConfig = path.join(output, 'operator-safe.toml');
await mkdir(output, { recursive: true });
// Resolve path-bearing settings before copying, so relative paths do not shift.
execFileSync(python, ['-c', `
import json,re,sys,tomllib
from pathlib import Path
from proctoring.config import load_config
source=Path(sys.argv[1]);target=Path(sys.argv[2]);config=load_config(source)
text=source.read_text(encoding='utf-8')
values={'quiz_path':config.quiz_path,'sessions_dir':config.sessions_dir,'yolo_model':config.vision.yolo_model,'face_model':config.vision.face_model,'validation_report':config.protection.validation_report}
for key,value in values.items():
 text=re.sub(r'^'+key+r'\\s*=.*$',lambda _: key+' = '+json.dumps(str(value)),text,flags=re.M)
for section in ('protection','remote'):
 text=re.sub(r'(\\['+section+r'\\]\\s*\\n(?:#[^\\n]*\\n)*)enabled\\s*=.*',lambda m:m.group(1)+'enabled = false',text)
target.write_text(text,encoding='utf-8')
safe=load_config(target)
assert not safe.remote.enabled and not safe.protection.enabled
`, path.join(repo, 'config/default.example.toml'), safeConfig], { cwd: repo, windowsHide: true, stdio: 'pipe' });
if (process.argv.includes('--prepare-only')) {
  console.log(JSON.stringify({ config_path: safeConfig, protection_enabled: false, remote_enabled: false }));
  process.exit(0);
}
const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE; delete env.PROCTORING_DEV_URL;
const application = await electron.launch({ args: ['.', '--config', safeConfig], env, timeout: 30000 });
let closed = false;
application.on('close', () => { closed = true; });
const page = await application.firstWindow();
await page.waitForSelector('h1');
const history = []; let signature = ''; let latest = null; let readErrors = 0;
const seen = new Set();
console.log(JSON.stringify({ stage: 'operator_ready', config_path: safeConfig, protection_enabled: false, remote_enabled: false,
  note: 'Complete the real onboarding, exam, pause/PIN/end and summary. No actions are automated.' }));
// No time limit ends a live exam. The user controls completion and normal exit.
while (!closed) {
  try {
    const result = await page.evaluate(() => window.proctoring.command('state.get'));
    if (result.ok && result.result.workflow) {
      const state = result.result, w = state.workflow;
      const events = w.events.records.map(e => ({ event_id: e.event_id, event_type: e.event_type, state: e.state,
        duration_seconds: e.duration_seconds, activity_seconds: e.activity_seconds, snapshot_available: !!(e.snapshot_path || e.snapshot) }));
      for (const event of events) seen.add(event.event_id);
      latest = { session_id: w.session_id, step: w.step, snapshot_seq: w.snapshot_seq,
        consent: state.consent_accepted, protection_enabled: state.protection.enabled,
        camera: { selected_key: state.camera.selected_key, state: state.camera.state, source_width: state.camera.source_width, source_height: state.camera.source_height },
        microphone: { running: state.audio.running, state: state.audio.check.state, gain: state.audio.check.gain,
          threshold: state.audio.check.committed_threshold, threshold_source: state.audio.check.threshold_source, stream_format: state.audio.check.stream_format },
        reference: { enabled: w.reference.enabled, ready: w.reference.ready },
        calibration: { phase: w.calibration.phase, target: w.calibration.target, ready: w.calibration.ready,
          accepted_samples: w.calibration.accepted_samples, message: w.calibration.message },
        monitoring: { healthy: w.monitoring.healthy, reason: w.monitoring.reason, fps: w.monitoring.fps },
        session: { ...w.session }, answered: w.quiz.answered, event_cursor: w.events.cursor,
        events, report: w.report, observed_unique_event_ids: [...seen],
        session_path: w.session_id ? path.join(repo, 'sessions', w.session_id) : null };
      const next = JSON.stringify([w.step, w.session.started, w.session.ended, w.session.pause_reasons,
        state.audio.check.state, state.audio.check.committed_threshold, w.reference.ready,
        w.calibration.phase, w.calibration.target, w.calibration.accepted_samples, w.quiz.answered,
        events.map(e => [e.event_id, e.state]), w.report.status]);
      if (next !== signature) { signature = next; history.push(latest); console.log(JSON.stringify(latest)); }
      await writeFile(path.join(output, 'operator-result.json'), JSON.stringify({ latest, history, read_errors: readErrors }, null, 2));
    }
  } catch {
    if (closed) break;
    readErrors += 1;
    // Renderer remount/crash remains visible to the application policy. Never restart a session.
  }
  await new Promise(resolve => setTimeout(resolve, 500));
}
await writeFile(path.join(output, 'operator-result.json'), JSON.stringify({ latest, history, read_errors: readErrors, native_closed: true }, null, 2));
console.log(JSON.stringify({ stage: 'operator_closed', ended: latest?.session.ended ?? false,
  end_reason: latest?.session.end_reason ?? null, event_ids: [...seen], session_path: latest?.session_path ?? null }));
