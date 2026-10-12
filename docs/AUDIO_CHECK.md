# Devices and voice-level microphone calibration

This source update adds device selection and application-side gain. The published
v0.4.0 executable is preserved and does not contain this update.

## Use

In camera setup, select a named camera and an input microphone under **Devices**.
The existing preview remains beside gaze calibration. Click **Calibrate microphone**,
stay quiet for 1.5 seconds, then speak naturally for six seconds. A progress bar shows
the bounded check; its overall deadline is 12 seconds. No extra collection buttons,
shouting, numerical adjustment, or developer sequence is required.

A setup audio test is available even if `audio.enabled = false`. It never enables
exam audio monitoring implicitly. Only the configured enabled audio worker can
produce the existing exam audio-activity events. Setup samples cannot create events,
start an exam, or advance the exam timer. Audio failure still does not pause the exam.

## Device identity and lifecycle

- Camera: Qt `QMediaDevices.videoInputs()` enumerates names/IDs and `QCamera` opens
  that exact ID. `QVideoSink` converts frames to owned BGR arrays on the capture
  path, feeding the existing one-frame mailbox and unchanged Face/YOLO inference.
  No Qt-index-to-OpenCV-index mapping is made. The explicitly labelled configured
  OpenCV entry preserves older configuration behavior.
- Microphone: sounddevice/PortAudio enumerates and opens the same backend's input.
  Labels include name, host API and current index; outputs are excluded. The system
  default resolves when explicitly opened. Requested sample rate/mono are checked;
  the device-reported default rate and two-channel input are tried if needed.
  Processing sizes use the opened stream's actual rate and channel count.
- PortAudio does not expose a stable endpoint ID here. Preferences therefore use
  a name/API/channel fingerprint, resolved afresh rather than saving an index.
  Ambiguous duplicates have distinct live labels but are never restored silently.
- Preferences use `QSettings("LocalProctoring", "InputDevices")`, normally under
  `HKEY_CURRENT_USER\Software\LocalProctoring\InputDevices` on Windows. Only
  device choices are persisted there. The user's TOML files are not overwritten.
- A missing saved device is marked unavailable. Choose another device explicitly.
- Switching is setup-only. The previous worker must exit before another is opened.
  Old frames/buffers are discarded. Camera switches clear gaze and identity baselines;
  microphone switches clear only microphone calibration. No competing capture worker
  is created when a driver refuses to release; the UI reports the condition.
- Refresh releases the application's input stream off the UI thread before refreshing
  PortAudio's cached catalog. Its paired `_terminate`/`_initialize` calls are isolated
  in `devices.refresh_microphones` because sounddevice 0.5.x has no public refresh API.
  Audio opens/calibration are excluded during refresh. A stuck enumeration times out
  in the UI without launching competing enumeration; reconnect/restart if necessary.
- Device opening, reads, release and inference run off the UI. A selected Qt camera
  that produces no frames for ten seconds stops and requires an explicit retry.

## Numerical processing

Samples are normalized floating point. The raw background estimate B is the 75th
percentile of quiet-window buffer RMS. Raw speech-level candidates exceed
`max(0.003, 3*B, B+0.002)`. At least ten buffers and 20% of the speech window must be
usable. The window must show variation (`P90/P10 >= 1.25`); steady noise/tone cannot
verify speech. This is an activity proxy, not a speech model: varying music or noise
can still resemble speech. Human checking is necessary.

Let S be median RMS of usable speech buffers and P the largest raw peak over the
speech window. The proposed fixed session gain is:

```
gain = min(max_gain, speech_target_rms / S, 0.90 / max(P, 0.001))
processed_noise = B * gain
processed_speech = S * gain
threshold = max(min_energy_threshold,
                processed_noise + 0.4 * (processed_speech - processed_noise))
```

Reject if gain is below 0.1, threshold exceeds `max_energy_threshold`, or threshold
is at least 90% of processed speech RMS. Gain is not estimated from silence. Raw
background above 0.12 is rejected; input with more than 0.1% of samples at absolute
amplitude >=0.995 is reported as clipping, not repaired.

Committed gain approaches its fixed target exponentially with a 0.25-second time
constant and a within-buffer linear ramp. Processed samples are limited to ±0.95.
The actual detector and displayed meter both consume these processed samples.
There is no per-frame normalization or gain growth during silence. Peak headroom
protects normal calibrated input; the limiter protects against later louder samples.
Gain cannot remove noise or recover already-clipped audio.

The regular UI shows simple instructions/progress. `--calibration-debug` additionally
shows input RMS, processed RMS, gain and threshold; the old manual threshold slider
is available only there for the gain-enabled worker. It remains a threshold control,
not a system microphone volume control.

Gains/references are session-local and bound to the microphone. Failed same-device
retries retain the last valid gain/threshold. Changing the resolved device resets
those settings, including when reopening the system-default choice resolves to a
different input. Raw/processed measurements have explicit metadata names. Session
records store numerical gain/threshold/device/format information only. No audio
recordings, credentials or tokens are exported. Windows volume and embedded website
microphone streams are not changed.

Without successful calibration, gain remains 1 and the existing three-second
ambient/static-threshold fallback is retained. The audio-event duration and clearing
hysteresis are unchanged.

## Configuration

Add to the existing `[audio]` section if customization is needed; old TOML files
remain valid because these fields have defaults:

```toml
calibration_background_seconds = 1.5
calibration_speech_seconds = 6.0
calibration_max_seconds = 12.0
speech_target_rms = 0.15
max_gain = 8.0
gain_smoothing_seconds = 0.25
```

`min_energy_threshold = 0.05` and `max_energy_threshold = 0.40` bound the processed
RMS threshold. Background + speech durations must fit the configured deadline.

## Short operator check / Короткая ручная проверка

Launch with restrictions disabled:

```powershell
.\.venv\Scripts\python.exe -m proctoring --config config/default.example.toml
```

1. Select the intended named camera and microphone. Check preview and input meter.
2. Click Calibrate microphone; follow quiet and normal-speech prompts. Do not shout.
3. After success, speak normally and pause. The meter should respond; gain should not
   creep upward during silence. Repeat in debug mode only if numerical inspection is needed.
4. Switch microphone, verify calibration resets, and repeat. Successful gaze
   calibration must remain intact. Switch camera and verify gaze calibration clears.
5. Restart: selections should restore. Unplug a saved device and refresh; the UI
   must report it unavailable, never silently choose another input.
6. Retry with silence, constant fan noise, and intentionally over-loud input.
   Failure must not replace a valid same-device setting. Check exam audio behavior
   only in a deliberate safe demo; microphone loss must not pause the exam.

Выберите камеру и микрофон → нажмите калибровку → 1,5 секунды тишины → 6 секунд
обычной речи. Проверьте паузы, смену микрофона и восстановление выбора после
перезапуска. Усиление не должно расти при тишине. Смена микрофона не сбрасывает
взгляд, смена камеры требует новой калибровки взгляда. При отключённом
`audio.enabled` проверка микрофона не включает аудиоконтроль экзамена.

## Verification on 2026-10-12

Automated tests cover device resolution, format fallback, cleanup/late-buffer
rejection, missing/duplicate saved devices, calibration invalidation, bounded gain,
silence/noise/clipping failures, processed units and pre-exam event isolation.

Actual Windows startup and USB2.0_Camera capture succeeded: 640×480 negotiated
from the requested 1280×720, approximately 30 capture FPS and 4.4 CPU monitoring FPS.
Default input opened at 16 kHz mono, then an explicit switch to the named Fifine
WASAPI input opened at 48 kHz mono and produced fresh level measurements.
No media was saved; no exam or restrictions were activated.

Human normal-speech calibration: **NOT RUN**. Physical switching between two cameras:
**NOT RUN** (one camera available). Unplug/replug and permission changes: **NOT RUN**.
These mocked/automatic checks do not establish real speech-calibration accuracy.

API references: [Qt video sink](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QVideoSink.html),
[PortAudio input settings through sounddevice](https://python-sounddevice.readthedocs.io/en/0.4.7/api/checking-hardware.html).
