# Devices and voice-level microphone calibration

This source update adds device selection and application-side gain. The published
v0.4.0 executable is preserved and does not contain this update.

## Use

On the first screen, select a named camera and an input microphone under **Devices**.
This shared panel is above registration/selfie controls and works with empty form
fields. It moves to calibration after registration; without registration it starts
on setup. **Test camera (preview only)** explicitly activates the selected source;
selecting a camera alone does not activate capture. Selfie, gaze calibration and
exam monitoring use the same worker. Click **Calibrate microphone**,
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
  Normal labels are friendly names from supported WASAPI routes, falling back to
  the default supported API. Technical alternative routes, unsupported inputs and
  loopback inputs identified by backend metadata appear in **Advanced audio devices**.
  No English-name-only filtering or cross-API name merging is used. Sounddevice
  does not expose enough endpoint type information to identify every stereo-mix
  input. Outputs are excluded. System default shows and opens the supported WASAPI
  API default where available, otherwise PortAudio's default. Requested rate/mono are checked;
  the device-reported default rate and two-channel input are tried if needed.
  Processing sizes use the opened stream's actual rate and channel count.
- PortAudio does not expose a stable endpoint ID here. Preferences therefore use
  a name/API/channel fingerprint, resolved afresh rather than saving an index.
  Ambiguous duplicates have distinct live labels but are never restored silently.
- Preferences use `QSettings("LocalProctoring", "InputDevices")`, normally under
  `HKEY_CURRENT_USER\Software\LocalProctoring\InputDevices` on Windows. Only
  device choices are persisted there. The user's TOML files are not overwritten.
- A missing saved device is marked unavailable. Choose another device explicitly.
- If the system default changes while its old stream is active, the default entry
  shows the current input and the new target separately. Selecting it explicitly
  switches sources and resets microphone calibration; refresh alone does not.
- Switching is setup-only. The previous worker must exit before another is opened.
  Old frames/buffers are discarded. Camera switches clear gaze and identity baselines;
  microphone switches clear only microphone calibration. No competing capture worker
  is created when a driver refuses to release; the UI reports the condition.
- Refresh keeps active capture running and reads the cached audio catalog. The UI
  explains this limitation. **Advanced → Rescan audio hardware** explicitly releases
  the stream off the UI thread to discover new hardware. When no stream is active,
  normal refresh also renews the catalog. Paired `_terminate`/`_initialize` calls are isolated
  in `devices.refresh_microphones` because sounddevice 0.5.x has no public refresh API.
  Audio opens/calibration are excluded during refresh. A stuck enumeration times out
  in the UI without launching competing enumeration; reconnect/restart if necessary.
- Device opening, reads, release and inference run off the UI. A selected Qt camera
  that produces no frames for ten seconds stops and requires an explicit retry.

## Numerical processing

Floating samples retain their normalized scale; signed PCM is converted to float
before dividing by its full-scale value, and unsigned PCM is centered first. The
strongest RMS channel is used for both calibration and runtime, avoiding dilution
by silent channels and cancellation of opposite-polarity channels. This also admits
noise from that channel; it is not a noise-removal method. The opened sample rate
determines buffer durations and gain ramps.

The raw background estimate B is the 75th
percentile of quiet-window buffer RMS. Raw speech-level candidates exceed
`max(0.0001, 3*B, B+0.0001)`. At least 0.5 seconds and 20% of the speech window must be
usable. The small nonzero floor remains above three 16-bit PCM steps; actual
hardware usability still requires a human check. The window must show variation
(`P90/P10 >= 1.25`); steady noise/tone cannot
verify speech. This is an activity proxy, not a speech model: varying music or noise
can still resemble speech. Human checking is necessary.

Let S be median RMS of usable speech buffers and P the 95th percentile of active
buffer peaks. A single unrelated click need not set gain for the whole attempt;
the absolute maximum peak and whether it exceeds the representative peak by 1.5×
remain visible in diagnostics. The proposed fixed session gain is:

```
gain = min(max_gain, speech_target_rms / S, 0.90 / max(P, 0.001))
processed_noise = B * gain
processed_speech = S * gain
threshold = processed_noise + 0.4 * (processed_speech - processed_noise)
```

Reject if gain is below 0.1, threshold exceeds `max_energy_threshold`, or threshold
is at least 90% of processed speech RMS. Background must remain below the threshold.
The adaptive threshold may fall below the manual/fallback minimum: reaching the
preferred RMS of 0.15 is not required for clearly separated input. Below-target
success is informational. Gain is not estimated from silence. Raw
background above 0.12 is rejected; input with more than 0.1% of samples at absolute
amplitude >=0.995 is reported as clipping, not repaired.

Committed gain approaches its fixed target exponentially with a 0.25-second time
constant and a within-buffer linear ramp. Processed samples are limited to ±0.95.
The actual detector and displayed meter both consume these processed samples.
There is no per-frame normalization or gain growth during silence. Peak headroom
protects normal calibrated input; the limiter protects against later louder samples.
Gain cannot remove noise or recover already-clipped audio.

The regular UI shows simple instructions/progress. `--calibration-debug` additionally
shows resolved input, actual format, B/S/P, maximum peak, proposed/committed/applied
gain, processed speech/noise, threshold and rejection code; the old manual threshold slider
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
ambient/static-threshold fallback is retained.

## Active-exam event timing

The audio worker uses the existing event engine in an explicit captured-duration
mode. Each fresh buffer contributes its frame count divided by the opened stream's
actual sample rate only when its current processed RMS exceeds the effective
threshold. A moving-average tail does not count a silent buffer as activity. The
default activation requirement remains 2.0 seconds of qualifying audio.

Previously, one below-threshold buffer discarded a pending candidate. Ordinary
inter-word dips could repeatedly prevent activation. Audio candidates now survive
gaps shorter than the configured clearing period (0.75 seconds by default), without
counting that silence. A longer gap resets the candidate. Active events retain the
existing clearing/deduplication behavior; later independent activity can activate a
new event. Camera events retain their original timing mode.

Read completion jitter is not audio duration: sequential chunks advance a capture
timeline by sample count, with queued input age checked for freshness. Repeated,
reordered, stale and overflowed buffers cannot add activity. Session startup clears
setup buffers and excludes buffers crossing the start boundary. Missing optional
audio interrupts its event stream, without pausing the exam timer.

The journal's `activity_seconds` is accumulated qualifying audio; `duration_seconds`
is the elapsed event episode, which can include brief gaps. Thus two seconds of
qualifying audio can take more than two seconds of normal speech to accumulate.
Gain and the committed threshold remain bound to the same resolved microphone,
including a same-device worker restart. A different resolved device still resets
calibration. Adaptive thresholds below 0.05 are not clamped on exam startup.

With `--calibration-debug`, the existing status panel also shows the resolved config
path, enabled/session/worker state, microphone/format, buffer age, gain, processed
RMS, effective threshold/source, candidate duration, reset reason and event count.
Only this numerical whitelist is shown; no credentials or audio recordings are
exported.

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

`min_energy_threshold = 0.05` bounds manual thresholds, while measured adaptive
thresholds can be lower with validated contrast. `max_energy_threshold = 0.40`
still caps adaptive/manual thresholds. Background + speech durations must fit
the configured deadline.

## Short operator check / Короткая ручная проверка

Launch with restrictions disabled:

```powershell
.\.venv\Scripts\python.exe -m proctoring --config config/default.example.toml
```

1. Leave registration blank. Select the intended camera and microphone. Click Test
   camera; confirm its preview works before taking any selfie.
2. Click Calibrate microphone; follow quiet and normal-speech prompts. Do not shout.
3. After success, speak normally and pause. The meter should respond; gain should not
   creep upward during silence. Repeat in debug mode only if numerical inspection is needed.
4. Switch microphone, verify calibration resets, and repeat. Successful gaze
   calibration must remain intact. Switch camera and verify selfie/gaze must be
   collected again while entered names and microphone settings remain.
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
Final full suite: **1,772 passed** (`python -m pytest -q`).

The previous update's Windows startup and USB2.0_Camera capture succeeded: 640×480 negotiated
from the requested 1280×720, approximately 30 capture FPS and 4.4 CPU monitoring FPS.
Default input opened at 16 kHz mono, then an explicit switch to the named Fifine
WASAPI input opened at 48 kHz mono and produced fresh level measurements.
No media was saved; no exam or restrictions were activated.

This correction was launched on the interactive Windows desktop with restrictions,
exam audio monitoring and remote delivery disabled. The operator completed a real
Fifine quiet/normal-speech attempt before registration. The worker opened the selected
WASAPI input at 48 kHz, mono, float32. Measurements:

| Value | Result |
| --- | ---: |
| Raw background B | 0.00002924 |
| Raw usable activity S | 0.00534811 |
| Active-buffer P95 peak | 0.07215622 |
| Maximum observed peak | 0.12536621 |
| Committed gain | 8.0 |
| Processed background | 0.00023395 |
| Processed speech | 0.04278487 |
| Detector threshold | 0.01725431 |

Result: **ready, below preferred target but usable**. The operator confirmed quiet
during background, normal speech during the prompt, and no returning quiet warning
after pausing. The old 0.05 floor would exceed this attempt's processed speech level.
That supports the threshold-conflict diagnosis for this measured signal. It is one
human run, not a guarantee across rooms, devices or noise conditions. Integer and
channel fixes were tested synthetically; this real run used float32 mono.
No raw audio from the earlier failed attempts exists to replay their exact candidate
buffer selection. The new run does not prove every historical failure had this cause.

Physical switching between two cameras, unplug/replug and permission changes remain
**NOT RUN**; automated mocks cover their relevant lifecycle guards. No audio or
video was recorded. The published release and Git history were not changed.

### Active-exam warning correction: separate verification

Automated result: **1,793 tests passed** (`.\.venv\Scripts\python.exe -m pytest -q`).
New cases cover captured-duration accounting, short versus clearing-length gaps,
read scheduling jitter, queued/stale/repeated buffers, same-device worker restart,
calibration retention below 0.05, setup exclusion, disabled monitoring, the real
controller/journal/Qt warning path, summary delivery, deduplication and timer behavior.
These tests use controlled inputs and are separate from the operator run below.

The operator then completed registration/selfie/gaze setup and started a real camera
exam using the updated source and explicitly selected
`C:\Users\kuten\Desktop\case3_proctoring\config\default.example.toml`.
Audio monitoring was enabled; Windows restrictions and remote delivery were disabled.
The selected and resolved input was **Микрофон (fifine Microphone)** at **48 kHz,
mono, float32**. The worker was running during the exam, with fresh buffers.

| Measured value | Active-exam run |
| --- | ---: |
| Raw background RMS | 0.0000217394 |
| Raw representative calibration activity RMS | 0.0013051622 |
| Committed/applied gain | 8.0 |
| Effective adaptive threshold | 0.0042808680 |
| First activation: qualifying captured audio | 2.0 s |
| First activation: elapsed episode including short gaps | 6.25 s |
| Saved audio events across the run | 7 |
| Exam elapsed time | 116.547 s |

Gain and threshold remained unchanged from setup into the active exam and final
summary. The first `VOICE_DETECTED` activation was present in `events.jsonl` and the
Qt event table; all seven recorded audio events were also present in `summary.json`.
The operator confirmed **normal speech; warning visible**. Observed warnings did not
pause the timer. The session ended through the **emergency shortcut**, according to
the saved end reason, and the audio worker stopped. This run therefore verifies
active-exam delivery and emergency finalization; it is not a fresh human test of
the PIN-based End session path. Automated tests cover normal completion.

Local numerical trace: `artifacts/audio-active-exam-result.json`. Session records:
`sessions/session-1f88e3c270964ff1a9a8a9dca5fb30c9/`. These local artifacts are ignored
by Git. No audio was recorded; normal configured snapshot behavior was preserved.
One operator/device run establishes delivery for that run, not speech-recognition
accuracy or immunity to other sounds. Earlier saved failed sessions already had
adaptive gain/threshold metadata; without their buffer traces, the exact proportion
of earlier missing warnings caused by candidate resets cannot be reconstructed.

API references: [Qt video sink](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QVideoSink.html),
[PortAudio input settings through sounddevice](https://python-sounddevice.readthedocs.io/en/0.4.7/api/checking-hardware.html).
