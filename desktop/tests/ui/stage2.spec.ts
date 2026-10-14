import { test, expect, type Page } from '@playwright/test';
import type { BackendState, WorkflowState, ControlChallenge, ProtectionState } from '../../shared/contracts';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const shots = path.resolve('../artifacts/electron-stage2');
test.beforeAll(() => mkdir(shots, { recursive: true }));

function initialState(step: WorkflowState['step']): BackendState {
  const preparing = step === 'setup' || step === 'calibration';
  return {
    version: 1, mode: 'exam_workflow', connected: true, consent_accepted: true, language: 'en', protection: { enabled: false, reason: 'stage2' },
    config: { audio_exam_enabled: true, remote_enabled: false, remote_destinations: [], external_exam_configured: false, registration_enabled: true },
    devices: { scanning: false, cameras: [{ key: 'test-camera', label: 'Test camera', name: 'Test camera', backend: 'test', advanced: false, supported: true, ambiguous: false, details: '', default_target_key: '' }], microphones: [{ key: 'test-mic', label: 'Test microphone', name: 'Test microphone', backend: 'test', advanced: false, supported: true, ambiguous: false, details: '', default_target_key: '' }], errors: {} },
    camera: { selected_key: 'test-camera', state: 'live', error: null, fps: 12, frame_age_seconds: .02, source_width: 640, source_height: 480, preview_sequence: 1 },
    audio: { selected_key: 'test-mic', state: 'running', error: null, running: true, processed_level: .02, frame_age_seconds: .02, check: { state: 'ready', reason: '', progress: 1, gain: 8, committed_threshold: .003, threshold: .003 } },
    unavailable_actions: [],
    workflow: {
      version: 2, step, revision: 1, snapshot_seq: 1, session_id: preparing || step === 'ready' ? null : 'session-test-stage2', config_path: 'C:/test/config.toml',
      registration: { enabled: true, require_group: true, complete: !preparing, candidate: preparing ? null : { first_name: 'Test', last_name: 'Operator', group_id: 'T1' } },
      reference: { enabled: true, ready: !preparing, can_capture: true, status: 'Fresh source frame available' },
      calibration: { attempt_id: 'attempt-test', phase: preparing ? 'idle' : 'complete', target: 'CENTER', presentation_token: null, cue_sequence: 0, cue: null, message: '', accepted_samples: preparing ? 0 : 20, required_samples: 20, completed_targets: preparing ? [] : ['CENTER','LEFT','RIGHT','DOWN'], alignment: { ready: true, reason: 'ready', message: 'Face aligned', progress: 1, guide: [.18,.08,.82,.92] }, ready: !preparing, prepare_remaining: 0, collection_progress: 0, geometry_id: null, diagnostics: {}, last_attempt: null, retained_attempts: [] },
      readiness: { ready: !preparing, checks: [{ id: 'camera', status: 'ready', message: 'Fresh camera' }, { id: 'calibration', status: preparing ? 'blocked' : 'ready', message: '' }] },
      session: { started: !preparing && step !== 'ready', started_at: '2026-10-13T08:00:00Z', ended: step === 'summary', running: step === 'exam', elapsed_seconds: 144, remaining_seconds: 456, duration_seconds: 600, pause_reasons: step === 'paused' ? ['proctor'] : [], monitoring_healthy: true, recovery_pin_required: false, end_reason: null },
      quiz: { mode: 'native', current_index: 0, total: 2, answered: 0, revision: 1, questions: [{ id: 'q1', prompt: 'Backend question: select a color.', options: ['Green','Blue'] }, { id: 'q2', prompt: 'Backend question: select a number.', options: ['One','Two'] }], answers: {} },
      monitoring: { healthy: true, reason: 'Fresh test observations', gaze_direction: 'UNKNOWN', head_pose: { yaw: 0, pitch: 0, roll: 0 }, person_count: 1, phone_visible: false, latency_ms: { face: 18, yolo: 60 }, fps: 12 },
      events: { cursor: 0, records: [] }, summary: null,
      report: { status: 'disabled', error: null, file_name: 'exam_integrity_report.pdf', available: false },
    },
  };
}

async function mockWorkflow(page: Page, step: WorkflowState['step'] = 'setup') {
  await page.addInitScript((initial: BackendState) => {
    const state = structuredClone(initial); const workflow = state.workflow!;
    const calls: { name: string; payload?: Record<string, unknown> }[] = [];
    let connected = true; let sequence = 0; const journal: Record<string, unknown>[] = [];
    let nativeEnd: (() => void) | null = null;
    let controlChallenge: ((value: ControlChallenge) => void) | null = null;
    const snapshot = () => { workflow.revision++; workflow.snapshot_seq++; return structuredClone(state); };
    const finish = () => {
      workflow.step = 'summary'; workflow.session.running = false; workflow.session.ended = true; workflow.session.end_reason = 'submitted';
      workflow.summary = { session_id: workflow.session_id, score: 1, total_questions: 2, answered: workflow.quiz.answered, elapsed_seconds: 144, started_at: workflow.session.started_at, ended_at: '2026-10-13T08:02:24Z', end_reason: 'submitted', event_count: workflow.events.records.length, events: workflow.events.records, lifecycle: [], security_events: [] };
      workflow.report = { status: 'failed', error: 'Test report failure', file_name: 'exam_integrity_report.pdf', available: false };
    };
    const controls = {
      calls,
      challenge(value: ControlChallenge) { controlChallenge?.(value); },
      protection(value: ProtectionState) { state.protection = value; workflow.readiness.ready = value.state === 'preparing'; },
      failContainment() { finish(); state.protection = { requested: true, enabled: false, state: 'fault', reason: 'foreground_containment_failed' }; workflow.session.end_reason = 'foreground_containment_failed'; workflow.summary!.end_reason = 'foreground_containment_failed'; },
      unavailableHelper(phase: 'releasing' | 'fault') { finish(); state.protection = { requested: true, enabled: phase === 'releasing', state: phase, reason: 'helper_identity_unavailable' }; workflow.session.end_reason = 'helper_identity_unavailable'; workflow.summary!.end_reason = 'helper_identity_unavailable'; },
      failCalibration() { workflow.calibration.phase = 'fit_failed'; workflow.calibration.message = 'Measured CENTER and DOWN overlap'; workflow.calibration.ready = false; },
      passCalibration() { workflow.calibration.ready = true; workflow.calibration.phase = 'complete'; workflow.calibration.cue_sequence++; workflow.calibration.cue = 'complete'; workflow.calibration.completed_targets = ['CENTER','LEFT','RIGHT','DOWN']; workflow.readiness.ready = true; workflow.readiness.checks[1].status = 'ready'; workflow.step = 'ready'; },
      event(id = 'audio-event-001', duration = 2) {
        const record = { event_id: id, event_type: 'VOICE_DETECTED', record_kind: 'review_event', state: 'active', action: 'activated', duration_seconds: duration, activity_seconds: 2, activated_timestamp: '2026-10-13T08:01:00Z', snapshot_path: 'snapshots/test.jpg' };
        const index = workflow.events.records.findIndex(r => r.event_id === id);
        if (index < 0) workflow.events.records.push(record); else workflow.events.records[index] = record;
        journal.push({ record_kind: 'lifecycle', event_type: 'test_tick', timestamp: '2026-10-13T08:01:00Z' }, record);
        workflow.events.cursor = journal.length;
      },
      disconnect() { connected = false; workflow.step = 'paused'; workflow.session.running = false; workflow.session.pause_reasons = ['presentation', 'proctor']; },
      external() { workflow.quiz.mode = 'external'; workflow.quiz.questions = []; state.config.external_exam_configured = true; },
      endFromWindow() { nativeEnd?.(); },
    };
    (window as unknown as { __stage2: typeof controls }).__stage2 = controls;
    if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => { throw new Error('Physical capture prohibited in mocked UI checks'); };
    window.proctoring = {
      mode: 'live',
      async connection() { return { state: connected ? 'connected' : 'disconnected' }; },
      async reconnect() { connected = true; return { state: 'connected' }; },
      async acknowledgePresentation(payload) { calls.push({ name: 'presentation.ack', payload: { ...payload } }); workflow.session.pause_reasons = workflow.session.pause_reasons.filter(v => v !== 'presentation'); return { version: 1, id: 'ack', ok: true, result: snapshot() }; },
      onControlChallenge(listener) { controlChallenge = listener; return () => { controlChallenge = null; }; },
      async acknowledgeControlProgress(receipt) { calls.push({ name: 'control.progress', payload: { ...receipt } }); return { accepted: true }; },
      onEndRequested(callback) { nativeEnd = callback; return () => { nativeEnd = null; }; },
      async geometry() { return { geometry_id: 'geometry-test', content_bounds: { x: 0, y: 0, width: 1280, height: 720 }, display_bounds: { x: 0, y: 0, width: 1280, height: 720 }, scale_factor: 1, zoom_factor: 1, center_client: { x: 640, y: 360 }, center_visible: true }; },
      async external(intent) { calls.push({ name: `external.${intent.action}`, payload: { ...intent } }); return { configured: workflow.quiz.mode === 'external', state: 'ready', visible: intent.action === 'layout' && intent.visible && !intent.modal, message: '' }; },
      async evidence(intent) { calls.push({ name: 'evidence', payload: { ...intent } }); return { ok: false, error: 'Test evidence file missing' }; },
      async preview() { const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 48; return { sequence: ++sequence, captured_at: performance.now() / 1000, source_width: 640, source_height: 480, width: 64, height: 48, mime: 'image/jpeg', jpeg_base64: canvas.toDataURL('image/jpeg').split(',')[1], overlays: [{ kind: 'box', label: 'person', x1: .2, y1: .1, x2: .8, y2: .9 }] }; },
      async command(name, payload) {
        // Never retain typed PINs, even in test diagnostics.
        calls.push({ name, payload: name.startsWith('proctor.') ? undefined : payload });
        if (name.startsWith('proctor.') && payload?.pin !== '2468') return { version: 1, id: 'pin-rejected', ok: false, error: { code: 'invalid_pin', message: 'PIN was not accepted' } };
        if (name === 'registration.submit') { workflow.registration.candidate = { first_name: String(payload?.first_name), last_name: String(payload?.last_name), group_id: String(payload?.group_id) }; workflow.registration.complete = true; }
        if (name === 'reference.capture') workflow.reference.ready = true;
        if (name === 'calibration.start') { if (workflow.calibration.ready) workflow.step = 'ready'; else { workflow.step = 'calibration'; workflow.calibration.phase = 'awaiting_presentation'; workflow.calibration.presentation_token = 'token-test'; } }
        if (name === 'calibration.presented') { workflow.calibration.phase = 'preparing'; workflow.calibration.prepare_remaining = 2; }
        if (name === 'calibration.retry') { workflow.calibration.phase = 'idle'; workflow.calibration.ready = false; workflow.calibration.message = ''; }
        if (name === 'calibration.cancel') workflow.step = 'setup';
        if (name === 'setup.show') workflow.step = 'setup';
        if (name === 'exam.start' && workflow.readiness.ready) { workflow.step = 'exam'; workflow.session_id = 'session-test-stage2'; workflow.session.started = true; workflow.session.running = true; }
        if (name === 'quiz.answer') { const question = workflow.quiz.questions[Number(payload?.question_index)]; workflow.quiz.answers[String(payload?.question_index)] = Number(payload?.option_index); workflow.quiz.answered = Object.keys(workflow.quiz.answers).length; workflow.quiz.revision++; }
        if (name === 'quiz.navigate') workflow.quiz.current_index = Number(payload?.question_index);
        if (name === 'proctor.pause') { workflow.step = 'paused'; workflow.session.running = false; workflow.session.pause_reasons = ['proctor']; }
        if (name === 'proctor.resume') { workflow.step = 'exam'; workflow.session.running = true; workflow.session.pause_reasons = []; }
        if (name === 'proctor.end' || name === 'exam.submit') finish();
        if (name === 'report.retry') workflow.report = { ...workflow.report, status: 'complete', error: null, available: true };
        const data = name === 'events.get' ? { cursor: journal.length, records: journal.slice(Number(payload?.after ?? 0)).map((record, i) => ({ sequence: Number(payload?.after ?? 0) + i + 1, record })), has_more: false } : undefined;
        return { version: 1, id: 'test-result', ok: true, result: snapshot(), ...(data ? { data } : {}) };
      },
    };
  }, initialState(step));
}

async function control(page: Page, method: string, ...args: unknown[]) {
  await page.evaluate(({ method, args }) => { const controls = (window as unknown as { __stage2: Record<string, (...a: unknown[]) => void> }).__stage2; controls[method](...args); }, { method, args });
}

test('protection progress requires a committed matching snapshot, never ordinary polling', async ({ page }) => {
  await mockWorkflow(page, 'exam'); await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Backend question: select a color.' })).toBeVisible();
  const count = () => page.evaluate(() => (window as unknown as { __stage2: { calls: { name: string }[] } }).__stage2.calls.filter(c => c.name === 'control.progress').length);
  const challenge = { lease_id: 'a'.repeat(32), sequence: 1, nonce: 'b'.repeat(32), required_snapshot_seq: 1, session_id: 'session-test-stage2' };
  await control(page, 'challenge', { ...challenge, session_id: 'other-session' });
  await page.waitForTimeout(300);
  expect(await count()).toBe(0);
  await control(page, 'challenge', { ...challenge, required_snapshot_seq: 1_000_000 });
  await page.waitForTimeout(300);
  expect(await count()).toBe(0);
  await control(page, 'challenge', challenge);
  await expect.poll(count).toBe(1);
  await control(page, 'challenge', challenge);
  await page.waitForTimeout(300);
  expect(await count()).toBe(1);
  await control(page, 'challenge', { ...challenge, sequence: 2, nonce: 'c'.repeat(32) });
  await expect.poll(count).toBe(2);
});

test('requested or arming protection is never displayed as active; states translate', async ({ page }) => {
  await mockWorkflow(page, 'ready'); await page.goto('/');
  await control(page, 'protection', { requested: true, enabled: false, state: 'awaiting_audit', reason: 'awaiting_audit', audit: { valid: false, message: 'Test audit missing', path: 'C:/test/audit.json' } });
  await expect(page.locator('.app-header [data-protection-state]')).toHaveText('Protection awaits recovery audit');
  await expect(page.getByRole('button', { name: 'Start exam', exact: true })).toBeDisabled();
  await page.screenshot({ path: path.join(shots, 'protection-awaiting-audit.png'), fullPage: true });
  await page.locator('#language').selectOption('ru');
  await expect(page.locator('.app-header [data-protection-state]')).toHaveText('Защита ожидает проверку восстановления');
  await page.locator('#language').selectOption('kk');
  await expect(page.locator('.app-header [data-protection-state]')).toHaveText('Қорғау қалпына келтіру тексеруін күтуде');
  await control(page, 'protection', { requested: true, enabled: false, state: 'active', reason: '' });
  await expect(page.locator('.app-header [data-protection-state]')).toHaveAttribute('data-protection-state', 'unknown');
  await control(page, 'protection', { requested: true, enabled: true, state: 'active', reason: '' });
  await expect(page.locator('.app-header [data-protection-state]')).toHaveText('Қорғау белсенді');
  await control(page, 'disconnect');
  await expect(page.locator('.app-header [data-protection-state]')).toHaveText('Қорғау күйі қолжетімсіз');
  await page.setViewportSize({ width: 640, height: 360 });
  await expect(page.locator('.app-header [data-protection-state]')).toBeVisible();
  await page.screenshot({ path: path.join(shots, 'protection-disconnected-narrow-kk.png'), fullPage: true });
});

test('terminal foreground failure is explained on the summary in all three languages', async ({ page }) => {
  await mockWorkflow(page, 'exam'); await page.goto('/');
  await control(page, 'failContainment');
  const detail = page.locator('.protection-detail');
  await expect(detail).toContainText('The exam window could not be kept in the foreground.');
  await expect(detail).toContainText('Protection was released and the session ended.');
  await expect(page.locator('.summary-meta')).toContainText('foreground_containment_failed');
  await page.locator('#language').selectOption('ru');
  await expect(detail).toContainText('Не удалось удержать окно экзамена на переднем плане.');
  await page.locator('#language').selectOption('kk');
  await expect(detail).toContainText('Емтихан терезесін алдыңғы қатарда ұстау мүмкін болмады.');
  await expect(page.locator('.app-header [data-protection-state]')).toHaveAttribute('data-protection-state', 'fault');
  await expect(page.getByRole('button', { name: 'Start exam', exact: true })).toHaveCount(0);
});

test('unconfirmed helper identity never claims release in pending or fault states, in all locales', async ({ page }) => {
  await mockWorkflow(page, 'exam'); await page.goto('/');
  await control(page, 'unavailableHelper', 'releasing');
  const detail = page.locator('.protection-detail');
  await expect(detail).toContainText('Protection status could not be confirmed.');
  await expect(page.locator('.summary-meta')).toContainText('helper_identity_unavailable');
  const cases = [
    { locale: 'en', pending: 'Releasing protection…', fault: 'Protection interrupted — exam cannot continue', reason: 'Protection status could not be confirmed.', restart: 'Start a new session only after cleanup is confirmed.', falseRelease: 'The independent recovery path released protection.' },
    { locale: 'ru', pending: 'Снятие ограничений…', fault: 'Защита прервана — продолжить экзамен нельзя', reason: 'Не удалось подтвердить состояние защиты.', restart: 'Начинайте новую сессию только после подтверждения безопасного завершения работы.', falseRelease: 'Независимый механизм восстановления снял ограничения.' },
    { locale: 'kk', pending: 'Шектеулер алынуда…', fault: 'Қорғау үзілді — емтиханды жалғастыру мүмкін емес', reason: 'Қорғау күйін растау мүмкін болмады.', restart: 'Жұмыстың қауіпсіз аяқталғаны расталғаннан кейін ғана жаңа сессияны бастаңыз.', falseRelease: 'Тәуелсіз қалпына келтіру механизмі шектеулерді алды.' },
  ];
  for (const value of cases) {
    await page.locator('#language').selectOption(value.locale);
    // Unknown ownership does not clear cached native flags or prove release.
    await control(page, 'unavailableHelper', 'releasing');
    await expect(page.locator('.app-header [data-protection-state]')).toHaveText(value.pending);
    await expect(detail).toContainText(value.reason);
    await expect(detail).toContainText(value.restart);
    await expect(detail).toContainText('Ctrl+Shift+Alt+Q');
    await expect(detail).not.toContainText(value.falseRelease);
    await expect(page.locator('[data-protection-state="released"]')).toHaveCount(0);
    await control(page, 'unavailableHelper', 'fault');
    await expect(page.locator('.app-header [data-protection-state]')).toHaveText(value.fault);
    await expect(detail).toContainText(value.reason);
    await expect(detail).not.toContainText(value.falseRelease);
  }
});

test('outstanding protection challenge can follow the committed exam session transition', async ({ page }) => {
  await mockWorkflow(page, 'ready'); await page.goto('/');
  await expect(page.getByRole('button', { name: 'Start exam', exact: true })).toBeEnabled();
  const count = () => page.evaluate(() => (window as unknown as { __stage2: { calls: { name: string }[] } }).__stage2.calls.filter(c => c.name === 'control.progress').length);
  const challenge = { lease_id: 'a'.repeat(32), sequence: 1, nonce: 'b'.repeat(32), required_snapshot_seq: 1, session_id: null };
  await control(page, 'challenge', challenge);
  await expect.poll(count).toBe(1);
  await page.getByRole('button', { name: 'Start exam', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Backend question: select a color.' })).toBeVisible();
  await control(page, 'challenge', { ...challenge, session_id: 'session-test-stage2' });
  await expect.poll(count).toBe(2);
  await control(page, 'challenge', { ...challenge, session_id: 'session-test-stage2' });
  await page.waitForTimeout(200);
  expect(await count()).toBe(2);
});

test('real-mode preparation uses registration/reference and backend fit, never fixture success', async ({ page }) => {
  await mockWorkflow(page); await page.goto('/?scene=exam');
  await expect(page.locator('.fixture-bar')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save candidate details', exact: true })).toBeDisabled();
  await page.locator('#firstName').fill('Test'); await page.locator('#lastName').fill('Operator'); await page.locator('#group').fill('T1');
  await page.getByRole('button', { name: 'Save candidate details', exact: true }).click();
  await page.getByRole('button', { name: 'Capture reference photo', exact: true }).click();
  await expect(page.getByText('Reference photo accepted', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Start gaze calibration', exact: true }).click();
  await expect(page.getByText('Get ready for the target', { exact: false })).toBeVisible();
  await expect(page.locator('.physical-target')).toHaveCount(1);
  await expect(page.locator('#language')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Start exam', exact: true })).toHaveCount(0);
  await control(page, 'failCalibration');
  await expect(page.getByText('Measured CENTER and DOWN overlap').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start exam', exact: true })).toHaveCount(0);
  await page.screenshot({ path: path.join(shots, 'connected-calibration-failed.png'), fullPage: true });
  await page.getByRole('button', { name: 'Start a new baseline', exact: true }).click();
  await control(page, 'passCalibration');
  await expect(page.getByRole('button', { name: 'Start exam', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Back to devices', exact: true }).click();
  await page.getByRole('button', { name: 'Review readiness', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start exam', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start exam', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Backend question: select a color.', exact: true })).toBeVisible();
});

test('backend quiz, stable audio event IDs, PIN pause/resume and real summary/report states', async ({ page }) => {
  await mockWorkflow(page, 'exam'); await page.goto('/');
  await expect(page.getByTestId('exam-time')).toHaveText('07:36');
  await page.getByLabel('Green', { exact: false }).check();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByLabel('Two', { exact: false }).check();
  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(page.getByLabel('Green', { exact: false })).toBeChecked();
  await control(page, 'event');
  await expect(page.locator('[data-event-id="audio-event-001"]')).toHaveCount(1);
  await control(page, 'event', 'audio-event-001', 4);
  await expect(page.locator('[data-event-id="audio-event-001"]')).toHaveCount(1);
  await expect(page.getByTestId('exam-time')).toHaveText('07:36');
  await page.getByRole('button', { name: 'Pause exam', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.locator('#proctor-pin')).toBeFocused();
  const modalViewport = await page.locator('.dialog-overlay').evaluate(element => {
    const rect = element.getBoundingClientRect();
    return { top: rect.top, left: rect.left, width: rect.width, height: rect.height, viewportWidth: innerWidth, viewportHeight: innerHeight };
  });
  expect(modalViewport).toEqual({ top: 0, left: 0, width: modalViewport.viewportWidth, height: modalViewport.viewportHeight, viewportWidth: modalViewport.viewportWidth, viewportHeight: modalViewport.viewportHeight });
  // Fixed dialogs are reviewed in their real viewport; full-page captures include content above scrollY.
  await page.screenshot({ path: path.join(shots, 'connected-pin-dialog.png') });
  await page.locator('#proctor-pin').fill('wrong'); await page.getByRole('dialog').getByRole('button', { name: 'Pause exam', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('PIN was not accepted');
  await page.locator('#proctor-pin').fill('2468'); await page.getByRole('dialog').getByRole('button', { name: 'Pause exam', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Exam paused', exact: true })).toBeVisible();
  await expect(page.getByTestId('exam-time')).toHaveText('07:36');
  await page.getByRole('button', { name: 'Resume exam', exact: true }).click();
  await page.locator('#proctor-pin').fill('2468'); await page.getByRole('dialog').getByRole('button', { name: 'Resume exam', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Exam paused', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByRole('button', { name: 'Submit answers', exact: true }).click();
  await expect(page.locator('#proctor-pin')).toHaveCount(0);
  await page.getByRole('dialog').getByRole('button', { name: 'Submit answers', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Session ended', exact: true })).toBeVisible();
  await expect(page.locator('[data-event-id="audio-event-001"]')).toHaveCount(1);
  await expect(page.getByText('Test report failure', { exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(shots, 'connected-summary-report-failed.png'), fullPage: true });
  await page.getByRole('button', { name: 'Retry report generation', exact: true }).click();
  await page.getByRole('button', { name: 'View snapshot', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Test evidence file missing');
  await expect(page.getByRole('button', { name: 'Open report', exact: true })).toBeEnabled();
});

test('external view hides for native-close PIN and presentation resync preserves independent proctor pause', async ({ page }) => {
  await mockWorkflow(page, 'exam'); await page.goto('/'); await control(page, 'external');
  await expect(page.getByTestId('external-exam-slot')).toBeVisible();
  await control(page, 'endFromWindow');
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __stage2: { calls: { name: string }[] } }).__stage2.calls.some(c => c.name === 'external.hide'))).toBe(true);
  await page.keyboard.press('Escape');
  await control(page, 'event'); await control(page, 'disconnect');
  await expect(page.getByRole('heading', { name: 'Connection interrupted.', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Reconnect to Python', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Exam paused', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Reconnect to Python', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Reconnect to Python', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Exam paused', exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __stage2: { calls: { name: string }[] } }).__stage2.calls.filter(c => c.name === 'exam.start').length)).toBe(0);
});

for (const [width, height, locale] of [[1280,720,'en'],[1366,768,'ru'],[1920,1080,'kk'],[640,360,'ru']] as const) {
  test(`connected exam layout ${width} ${locale}`, async ({ page }) => {
    await page.setViewportSize({ width, height }); await mockWorkflow(page, 'exam'); await page.goto('/');
    await page.locator('#language').selectOption(locale); await control(page, 'event');
    await expect(page.locator('[data-event-id="audio-event-001"]')).toHaveCount(1);
    await expect(page.locator('.protection-status')).toBeVisible();
    await expect(page.getByTestId('exam-time')).toHaveText('07:36'); await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: path.join(shots, `connected-exam-${width}-${locale}.png`), fullPage: true });
  });
}
