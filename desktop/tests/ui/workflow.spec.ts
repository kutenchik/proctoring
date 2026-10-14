import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import type { Page } from '@playwright/test';
import type { BackendState } from '../../shared/contracts';
const screenshots = path.resolve('../artifacts/electron-stage1');
test.beforeAll(async () => { await mkdir(screenshots, { recursive: true }); });
const layouts = [
  ['setup-en-720', 1280, 720, 'setup', 'en'], ['setup-ru-768', 1366, 768, 'setup', 'ru'],
  ['setup-kk-1080', 1920, 1080, 'setup', 'kk'], ['setup-125', 1024, 576, 'setup', 'ru'],
  ['setup-150', 853, 480, 'setup', 'kk'], ['exam-200', 640, 360, 'exam', 'en'],
  ['exam-ru-1080', 1920, 1080, 'exam', 'ru'], ['gaze-en-720', 1280, 720, 'gaze', 'en'],
  ['ready-ru-720', 1280, 720, 'ready', 'ru'], ['paused-kk-720', 1280, 720, 'pause-pin', 'kk'],
  ['summary-en-720', 1280, 720, 'summary', 'en'], ['disconnected-en', 1280, 720, 'disconnected', 'en'],
] as const;
for (const [name, width, height, scene, locale] of layouts) {
  test(`layout ${name}`, async ({ page }) => {
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
    await page.setViewportSize({ width, height });
    await page.goto(`/?scene=${scene}`);
    await page.locator('#language').selectOption(locale);
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('h1')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator('.fixture-bar')).toBeVisible();
    expect(errors).toEqual([]);
    await page.screenshot({ path: path.join(screenshots, `${name}.png`), fullPage: true });
  });
}
test('language changes retain entered form values and fixture actions stay isolated', async ({ page }) => {
  await page.goto('/');
  await page.locator('#firstName').fill('Test'); await page.locator('#lastName').fill('Example');
  await page.locator('#group').fill('LOCAL');
  for (const language of ['ru', 'kk', 'en']) {
    await page.locator('#language').selectOption(language);
    await expect(page.locator('#firstName')).toHaveValue('Test');
    await expect(page.locator('#group')).toHaveValue('LOCAL');
  }
  expect(await page.evaluate(() => typeof window.proctoring)).toBe('undefined');
  await page.getByRole('button', { name: 'Continue to calibration', exact: true }).click();
  await expect(page.locator('.fixture-bar')).toBeVisible();
});
test('dialog has keyboard focus and restores it; reduced motion does not hide controls', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' }); await page.goto('/?scene=exam');
  const end = page.getByRole('button', { name: 'End session', exact: true }); await end.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.locator('#proctor-pin')).toBeFocused();
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toBeHidden();
  await expect(end).toBeFocused();
  await page.screenshot({ path: path.join(screenshots, 'exam-reduced-motion.png'), fullPage: true });
});
test('all fixture empty, failure and calibration states render without page errors', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  for (const scene of ['mic-quiet', 'mic-speak', 'mic-result', 'gaze-collect', 'gaze-rejected', 'summary-empty', 'summary-error', 'pause-short', 'pause-proctor']) {
    await page.goto(`/?scene=${scene}`); await expect(page.locator('h1')).toBeVisible();
    await expect(page.locator('.fixture-bar')).toBeVisible();
    await page.screenshot({ path: path.join(screenshots, `${scene}.png`), fullPage: true });
  }
  expect(errors).toEqual([]);
});
test('semantic palette contrast and bundled Kazakh glyph coverage', async ({ page }) => {
  await page.goto('/');
  const contrast = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
    const ctx = canvas.getContext('2d')!;
    const luminance = (token: string) => {
      ctx.fillStyle = style.getPropertyValue(token).trim(); ctx.fillRect(0, 0, 1, 1);
      const rgb = Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3).map(v => { const c = v / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; });
      return rgb[0]*.2126 + rgb[1]*.7152 + rgb[2]*.0722;
    };
    return [['--foreground', '--background'], ['--secondary-text', '--card'], ['--primary-foreground', '--primary'], ['--warning', '--warning-bg'], ['--error', '--error-bg'], ['--input-border', '--surface']].map(([a, b]) => { const x = luminance(a), y = luminance(b); return { pair: `${a}/${b}`, ratio: (Math.max(x,y)+.05)/(Math.min(x,y)+.05) }; });
  });
  for (const entry of contrast) expect(entry.ratio, entry.pair).toBeGreaterThanOrEqual(entry.pair.startsWith('--input') ? 3 : 4.5);
  await page.evaluate(() => {
    for (const [id, tag] of [['font-probe-body', 'p'], ['font-probe-heading', 'h2']]) {
      const node = document.createElement(tag); node.id = id; node.textContent = 'ӘҒҚҢӨҰҮҺІәғқңөұүһі'; document.body.append(node);
    }
    return document.fonts.ready;
  });
  const client = await page.context().newCDPSession(page);
  await client.send('DOM.enable'); await client.send('CSS.enable');
  const { root } = await client.send('DOM.getDocument');
  for (const [selector, family] of [['#font-probe-body', 'Inter'], ['#font-probe-heading', 'Nunito']]) {
    const { nodeId } = await client.send('DOM.querySelector', { nodeId: root.nodeId, selector });
    const { fonts } = await client.send('CSS.getPlatformFontsForNode', { nodeId });
    expect(fonts.length).toBeGreaterThan(0);
    expect(fonts.every(f => f.isCustomFont && f.familyName.includes(family)), JSON.stringify(fonts)).toBe(true);
  }
});

// The live-mode presentation is exercised against an in-page fake preload only.
// There is no Electron IPC, Python process, getUserMedia or physical device access.
async function installMockLiveAPI(page: Page) {
  const device = (key: string, label: string, ambiguous = false) => ({ key, label, name: label,
    backend: 'test', advanced: false, supported: true, ambiguous, details: 'Test catalog only', default_target_key: '' });
  const state: BackendState = {
    version: 1, mode: 'setup_only', connected: true, consent_accepted: false, language: 'en',
    protection: { enabled: false, reason: 'stage1' },
    config: { audio_exam_enabled: true, remote_enabled: false, remote_destinations: [], external_exam_configured: false, registration_enabled: true },
    devices: { scanning: false, cameras: [device('camera-a', 'Test camera A'), device('camera-b', 'Test camera B', true)],
      microphones: [device('mic-a', 'Test microphone A'), device('mic-b', 'Test microphone B')], errors: {} },
    camera: { selected_key: 'camera-a', state: 'not_started', error: null, fps: 0, frame_age_seconds: null, source_width: null, source_height: null, preview_sequence: null },
    audio: { selected_key: 'mic-a', state: 'stopped', error: null, running: false, processed_level: 0, frame_age_seconds: null,
      check: { state: 'idle', reason: '', progress: 0, threshold: .08 } },
    unavailable_actions: ['registration', 'reference', 'calibration', 'exam'],
  };
  await page.addInitScript((initial: BackendState) => {
    let connected = true; let sequence = 0;
    const calls: { name: string; payload?: Record<string, unknown> }[] = [];
    let mediaCalls = 0;
    if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => { mediaCalls++; throw new Error('Hardware access is forbidden in this UI test'); };
    const state = structuredClone(initial);
    const testWindow = window as typeof window & { __mockDesktop: { disconnect(): void; calls: typeof calls; mediaCalls(): number } };
    testWindow.__mockDesktop = { disconnect() { connected = false; }, calls, mediaCalls: () => mediaCalls };
    window.proctoring = {
      mode: 'live',
      async geometry() { return { geometry_id: 'test-geometry', content_bounds: { x: 0, y: 0, width: 1280, height: 720 }, display_bounds: { x: 0, y: 0, width: 1280, height: 720 }, scale_factor: 1, zoom_factor: 1, center_client: { x: 640, y: 360 }, center_visible: true }; },
      async external() { return { configured: false, state: 'idle', visible: false, message: '' }; },
      async evidence() { return { ok: false, error: 'Not supported by setup-only test' }; },
      onControlChallenge() { return () => {}; },
      async acknowledgeControlProgress() { return { accepted: false }; },
      onEndRequested() { return () => {}; },
      async acknowledgePresentation() { return { version: 1, id: 'test-sync', ok: true, result: structuredClone(state) }; },
      async connection() { return { state: connected ? 'connected' : 'disconnected', reason: connected ? undefined : 'Test bridge disconnected' }; },
      async command(name, payload) {
        calls.push({ name, payload });
        if (!connected) return { version: 1, id: 'test', ok: false, error: { code: 'DISCONNECTED', message: 'Test bridge disconnected' } };
        if (name === 'consent.set') state.consent_accepted = payload?.accepted === true;
        if (name === 'camera.select') state.camera.selected_key = String(payload?.key);
        if (name === 'microphone.select') state.audio.selected_key = String(payload?.key);
        if (name === 'camera.start' && state.consent_accepted) state.camera = { ...state.camera, state: 'live', source_width: 640, source_height: 480, frame_age_seconds: 0, fps: 12 };
        if (name === 'camera.stop') state.camera.state = 'stopped';
        if ((name === 'audio.start' || name === 'audio.calibrate') && state.consent_accepted) {
          state.audio = { ...state.audio, state: 'running', running: true, processed_level: .12, frame_age_seconds: .02,
            check: { state: name === 'audio.calibrate' ? 'ambient' : 'idle', reason: '', progress: .25, threshold: .08 } };
        }
        if (name === 'audio.stop') state.audio = { ...state.audio, running: false, state: 'stopped', processed_level: 0 };
        return { version: 1, id: `test-${calls.length}`, ok: true, result: structuredClone(state) };
      },
      async preview() {
        if (!connected || state.camera.state !== 'live') return null;
        const canvas = document.createElement('canvas'); canvas.width = 8; canvas.height = 6;
        canvas.getContext('2d')!.fillRect(0, 0, 8, 6);
        return { sequence: ++sequence, captured_at: performance.now() / 1000, source_width: 640, source_height: 480,
          width: 8, height: 6, mime: 'image/jpeg', jpeg_base64: canvas.toDataURL('image/jpeg').split(',')[1], overlays: [] };
      },
      async reconnect() {
        connected = true;
        state.camera.state = 'stopped';
        state.audio = { ...state.audio, state: 'stopped', running: false, processed_level: 0, frame_age_seconds: null,
          check: { state: 'idle', reason: '', progress: 0, threshold: .08 } };
        return { state: 'connected' };
      },
    };
  }, state);
}

test('mock live setup allows consented device actions before registration but never enables Stage 2 actions', async ({ page }) => {
  await installMockLiveAPI(page);
  // A fixture route query must not bypass the live-mode Stage 1 boundary.
  await page.goto('/?scene=exam');
  await expect(page.getByText('Python connected', { exact: true })).toBeVisible();
  await expect(page.locator('.fixture-bar')).toHaveCount(0);
  await expect(page.locator('#firstName')).toHaveValue('');
  await expect(page.locator('#lastName')).toHaveValue('');
  await expect(page.locator('#camera-select')).toBeEnabled();
  await expect(page.locator('#microphone-select')).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Test camera', exact: true })).toBeDisabled();
  await page.getByRole('checkbox').check();
  await page.locator('#camera-select').selectOption('camera-b');
  await page.locator('#microphone-select').selectOption('mic-b');
  await page.getByRole('button', { name: 'Test camera', exact: true }).click();
  await expect(page.getByRole('img', { name: 'Live preview', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Test microphone', exact: true }).click();
  await expect(page.getByRole('meter')).toHaveAttribute('aria-valuenow', '0.12');
  await page.getByRole('button', { name: 'Calibrate microphone', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Stay quiet for a moment', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Microphone calibrated', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Stop microphone', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Take reference photo', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Continue to calibration', exact: true })).toBeDisabled();
  await expect(page.locator('#stage-two-note')).toContainText('Available in the next migration stage');
  const result = await page.evaluate(() => {
    const mock = (window as unknown as { __mockDesktop: { calls: { name: string; payload?: Record<string, unknown> }[]; mediaCalls(): number } }).__mockDesktop;
    return { calls: mock.calls.filter(c => c.name !== 'state.get'), mediaCalls: mock.mediaCalls() };
  });
  expect(result.mediaCalls).toBe(0);
  expect(result.calls.map(c => c.name)).toEqual(['consent.set', 'camera.select', 'microphone.select', 'camera.start', 'audio.start', 'audio.calibrate']);
  expect(result.calls[1].payload).toEqual({ key: 'camera-b' });
  expect(result.calls[2].payload).toEqual({ key: 'mic-b' });
});

test('mock live disconnect hides preview and meter, preserves fields, and reconnect does not restart capture', async ({ page }) => {
  await installMockLiveAPI(page); await page.goto('/');
  await expect(page.getByText('Python connected', { exact: true })).toBeVisible();
  await page.locator('#firstName').fill('Local test');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Test camera', exact: true }).click();
  await page.getByRole('button', { name: 'Test microphone', exact: true }).click();
  await expect(page.getByRole('img', { name: 'Live preview', exact: true })).toBeVisible();
  await expect(page.getByRole('meter')).toHaveAttribute('aria-valuenow', '0.12');
  await page.evaluate(() => (window as unknown as { __mockDesktop: { disconnect(): void } }).__mockDesktop.disconnect());
  await expect(page.getByRole('heading', { name: 'Connection interrupted.', exact: true })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Live preview', exact: true })).toHaveCount(0);
  await expect(page.getByRole('meter')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Microphone calibrated', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Reconnect to Python', exact: true }).click();
  await expect(page.locator('#firstName')).toHaveValue('Local test');
  await expect(page.getByRole('button', { name: 'Test camera', exact: true })).toBeEnabled();
  await expect(page.getByRole('img', { name: 'Live preview', exact: true })).toHaveCount(0);
  await expect(page.getByRole('meter')).toHaveAttribute('aria-valuenow', '0');
  await expect(page.getByRole('button', { name: 'Continue to calibration', exact: true })).toBeDisabled();
  const calls = await page.evaluate(() => (window as unknown as { __mockDesktop: { calls: { name: string }[] } }).__mockDesktop.calls.map(c => c.name));
  expect(calls.filter(c => c === 'camera.start')).toHaveLength(1);
  expect(calls.filter(c => c === 'audio.start')).toHaveLength(1);
});
