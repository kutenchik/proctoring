import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { validateState } from '../electron/security';

test('Python preadmission state and current consent contracts cross the Electron boundary', () => {
  const repo = path.resolve('..');
  const state = JSON.parse(execFileSync(path.join(repo, '.venv/Scripts/python.exe'), ['-c', `
import sys, json, tempfile
from pathlib import Path
from proctoring.config import load_config
load_config.__defaults__ = (Path('config/default.example.toml'),)
sys.path.insert(0, 'tests')
from test_connected_workflow import connected_workflow
from test_connected_stage3 import Worker
from proctoring.connected.live_workflow import LiveWorkflow
with tempfile.TemporaryDirectory() as folder:
    b = connected_workflow(Path(folder))
    b.live_teacher = LiveWorkflow(b, worker=Worker(b.clock.monotonic), display_count_provider=lambda:1)
    try: print(json.dumps(b.state()))
    finally: b.close()
`], { cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, 'src') }, encoding: 'utf8' }));
  assert.doesNotThrow(() => validateState(state));
  for (const version of [3, 4, 5]) {
    state.live_teacher.consent.version = version;
    state.live_teacher.consent.features = ['audioEvidence'];
    assert.doesNotThrow(() => validateState(state));
  }
  for (const patch of [{ version: 6 }, { features: ['unknown'] }, { features: 'audioEvidence' }]) {
    const changed = structuredClone(state);
    Object.assign(changed.live_teacher.consent, patch);
    assert.throws(() => validateState(changed));
  }
  for (const advanced of [{ unknown: 'ready' }, { identity: true }]) {
    assert.throws(() => validateState({ ...state, live_teacher: { ...state.live_teacher, advanced } }));
  }
});
