# Optional proctoring checks and local PDF audits

These additions are opt-in hackathon components, not a validated identity or
misconduct assessment system. All new toggles ship disabled. Existing camera,
calibration, head-down review, quiz/browser, timing and emergency recovery stay
in place. No additional models or Internet setup are required.

Edit the corresponding existing sections in a private complete TOML config;
do not paste duplicate sections. Launch it with:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
.\.venv\Scripts\python.exe -m proctoring --config C:\path\demo.toml
```

| Section / option | Default | Effect when enabled |
| --- | --- | --- |
| `security.system_checks.block_multimonitor` | false | Count Qt-visible screens; block exam start if more than one is attached. |
| `security.system_checks.clipboard_guard_enabled` | false | Clear changed/nonempty clipboard contents during the exam and log `CLIPBOARD_ACCESSED`; never retain clipboard contents. |
| `security.system_checks.vm_check_enabled` | false | Background Windows BIOS/vendor registry check; store heuristic result and record `VIRTUAL_MACHINE_DETECTED` when matched. |
| `exam.identity.selfie_verification_enabled` | false | Require a reference selfie before calibration/exam; periodically compare face geometry. |
| `audio.enabled` | false | Monitor local microphone energy; no recording or transcription. |
| `vision.accessories.earphone_detection_enabled` | false | Run an experimental ear-adjacent patch appearance heuristic. |
| `reporting.generate_pdf_report` | false | Generate a local PDF after the session summary is saved. |
| `reporting.send_pdf_to_telegram` | false | Upload the generated PDF only when remote delivery and Telegram are also enabled. |

Changing these toggles does not enable Windows keyboard restrictions. Keep
`protection.enabled = false` during development checks. The preflight screen
count is not a production anti-tamper or virtual-display detection mechanism.
VM vendor matches are warnings, not a reason to block the exam. Missing display
enumeration/registry access is reported as unavailable rather than a positive
VM or multi-monitor finding.

## Reference selfie and identity review

With selfie verification enabled, enter candidate details on the registration
screen, open its preview, and select **Take Baseline Photo** with one clearly
visible, approximately frontal face. The existing vision worker opens the same
webcam used for calibration. Capture uses a fresh matching frame and landmarks;
the worker crops/normalizes the image to a 256-pixel square JPEG. The saved
`sessions/<session_id>/reference_face.jpg` is linked to the candidate and reused
by that same exam session. Four-target gaze calibration is still required.

The reference shape uses normalized 3D face landmarks and a Procrustes residual
after translation, scale and rotation alignment. These are **not trained identity
embeddings**. A geometric match does not authenticate identity, and expression,
camera placement or tracking errors can cause a mismatch. Shape coordinates
remain in session memory; only the explicitly captured selfie and descriptive
metadata are stored.

Default `impersonation_threshold = 0.40` is a unitless shape residual and
`periodic_check_interval_seconds = 30.0`. More than three consecutive valid
comparisons above the threshold produce `IMPERSONATION_SUSPECTED`, marked high
review priority. One subsequent fresh observation activates the existing event
pipeline. Invalid/missing/multiple/non-frontal faces reset the mismatch streak;
they do not count as a failed identity match. Existing face-absence handling
remains separate. Human/operator validation is still required for any useful
threshold or claimed identity discrimination.

## Audio energy

The optional daemon reads 50 ms mono buffers at `sample_rate = 16000` and exposes
live RMS at up to 20 Hz. The setup page now offers a microphone check: measure
quiet background for 2.5 seconds, then speak when prompted. The recommended
absolute trigger is `max(ambient * 2.5, ambient + 0.08)`, within configured limits.
A short sustained rise verifies that the input can cross the chosen threshold;
it does not recognize speech. Manual sensitivity changes the trigger, not hardware
gain. See [AUDIO_CHECK.md](AUDIO_CHECK.md) for the flow and fallback behavior.

Until a check succeeds or a manual threshold is selected, the original fallback
learns ambient RMS for three seconds and uses
`max(ambient + energy_threshold, 3 * ambient)`. The default fallback increment
`energy_threshold = 0.15` is normalized full-scale RMS amplitude, not a speech
probability or a decibel value.

Fresh above-threshold observations feed the same EventEngine class with
`voice_duration_threshold = 2.0` seconds and existing clearing hysteresis. Audio
uses its own observation stream and prefixed event IDs, so audio updates cannot
clear or prolong camera events. `VOICE_DETECTED` is the requested technical
event code; its UI label says **sustained audio activity** because noise, music,
fans and speech cannot be distinguished by RMS. No audio samples are saved or
sent remotely. Missing libraries/devices, input overflows and disconnects reduce
audio availability, log status and leave the exam timer/camera running.

## Accessory suspicion

MediaPipe Face Mesh has no verified ear-canal, tragus or earlobe landmarks.
This experiment uses small patches adjacent to the outer cheek contour, with
variance, low-saturation light/dark regions and strong boundaries as cues.
It requires five consecutive fresh anomalies with sufficient source pixels and
moderate yaw (`min_ear_yaw_trigger = 12.0` by default), then maps
`EARPHONE_SUSPECTED` to the existing review pipeline. Head pose, clipped patches
and stale samples invalidate the streak. Hair, glasses, shadows and skin can
produce similar patterns; this is not a validated earphone detector.

## Local report and dispatch

After local `summary.json` is finalized, a Qt `QTextDocument`/`QPdfWriter` worker
writes `exam_integrity_report.pdf` (configurable safe basename) atomically.
The report includes candidate/session/system metadata, available reference
selfie, and a timeline with one row per recorded event. Each row embeds its saved
snapshot as an aspect-preserving thumbnail, or says "No capture". The timeline
uses `HH:MM:SS` in the recorded timestamp's UTC offset; complete timestamps remain
in the session journal and summary. Identical snapshot content with identical
overlays reuses one image resource, and there is no separate repeated gallery.
Available person/phone boxes are rendered on report image copies; original JPEGs
are unchanged. Missing images are identified. Candidate strings are escaped and
images are restricted to local session paths.

The requested rule-based Trust Score is:

`max(0, 100 - 30*phone_events - 15*audio_events - 10*gaze_events - 50*identity_events)`

Each distinct event ID is counted once, even when the journal has many updates.
Phone-visible and phone-raised are distinct recorded event types and each can
contribute a penalty. Risk colors summarize this rule only; a 100% score does not
establish clean monitoring or absence of misconduct. Events are described as
review findings, not confirmed cheating.

With all three flags enabled (`reporting.send_pdf_to_telegram`, `remote.enabled`,
`remote.telegram_enabled`), the existing bounded remote worker sends the PDF via
Telegram `sendDocument`. This report may contain the candidate selfie and event
snapshots: enabling its upload authorizes transmitting those saved materials to
the configured recipient. Existing upload timeouts, drop-on-failure behavior and
two-second network shutdown limit apply. No retry/durable outbox is added. A
failed upload never deletes the local PDF. The UI remains responsive and defers
normal final close while PDF generation is using Qt font services.

## Operator validation

Use a controlled test identity and private test config. Keep real Windows
restrictions and remote delivery disabled until checking local behavior.

1. Enable one option at a time. Check a second monitor blocks start and removing
   it unblocks start. During a test exam, copy a harmless test string and confirm
   one clipboard audit record; after ending, clipboard use must work normally.
2. Enable selfie capture, take a baseline and finish calibration. Check the
   saved image/session metadata. Keep the same person under ordinary posture and
   lighting for several comparison intervals; collect any false mismatch. An
   intentional consenting second-person comparison is a separate human test.
3. Enable audio; stay quiet for three seconds, then sustain a sound for more
   than two seconds. Confirm one review event, clearing and uninterrupted timer.
   Test unavailable/disconnected microphone separately.
4. Test the accessory heuristic with/without earbuds and with hair/glasses under
   the same lighting. Record both missed and false suspicions; no accuracy claim
   follows from synthetic patch tests.
5. Enable local reporting, end a session and inspect the PDF. For a deliberate
   remote test, use a destination you control, explicitly enable the three upload
   flags and verify receipt. Automated tests mock every HTTP request; they do not
   prove actual Telegram delivery.

No new human identity, audio speech-recognition, or earphone accuracy validation
has been performed by implementing these modules.
