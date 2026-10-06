# Gaze rejection diagnostics — 2026-10-05

**Operator follow-up:** an actual exported attempt has now been analyzed. See [numerical findings and the bounded DOWN correction](GAZE_OPERATOR_ANALYSIS.md). The historical pending status below describes the state before that collection.

Human calibration still fails. This patch makes rejection auditable and adds a separate operator-labeled collection pass. It does **not** establish that eyes-only LEFT, RIGHT or DOWN works on this camera. Production thresholds, eye geometry and classification remain unchanged pending measurements.

## What the supplied failures establish

Gate values are in normalized eye-corner widths. With defaults, the constant floor contribution is `3 × 0.01 = 0.0300`, below all three reported requirements.

| Pair | Separation | Required | Eye width if pixel term alone dominated | Radial p90 spread if spread alone dominated |
|---|---:|---:|---:|---:|
| CENTER–DOWN | 0.0466 | 0.0910 | 32.967 px | 0.03640 |
| CENTER–LEFT | 0.0730 | 0.1096 | 27.372 px | 0.04384 |
| CENTER–DOWN | 0.0556 | 0.0784 | 38.265 px | 0.03136 |

The last two columns are **conditional calculations, not measured eye widths or spreads**: `3 / required` and `required / 2.5`. Synthetic regressions reproduce each displayed failure through either a pixel-dominated or a spread-dominated gate. Screenshots cannot identify the actual dominant term, distribution overlap or unrelated-axis variation.

Still missing for those attempts: original per-eye widths, per-eye/per-axis target distributions, supplied pixel floors, combined-axis distributions and rejection counts/reasons. They were not saved by the previous build and cannot be reconstructed. Export a new failed attempt below.

## Camera and precision checks

The local camera returned **640×480** for every tested 1280×720 request: MSMF at 30 FPS, MSMF at 15 FPS, and DirectShow at 30 FPS. Width/height setters returned success while reported dimensions and delivered arrays remained 640×480. All workers stopped normally. Numerical evidence: `artifacts/resolution-negotiation.json`; helper: `artifacts/probe_resolution_negotiation.py`.

This establishes that these profiles do not deliver 720p, not that every device mode/format is incapable of it. No artificial upscaling or unverified capture-mode change was made. The UI now displays requested and actual dimensions separately; each numerical face record carries original source dimensions.

Landmarks remain floating point through source-pixel coordinates, corner-axis projections, normalization and calibration statistics. Face processing uses original frame dimensions; YOLO resizing does not substitute for them. A regression moves iris centers by 0.25 horizontal and 0.125 vertical source pixels at 640×480 and verifies those fractional movements survive. The one-pixel floor is an **assumed safeguard**, not integer quantization or measured landmark error.

## Numerical fields and units

Records include monotonic capture time, source dimensions, per-eye horizontal/vertical coordinates, openness, original-pixel width, validity/reason, combined features, and separate head pose. Missing metadata remains missing. No images, video or raw landmark arrays are exported.

`calibration.diagnostics.targets` gives accepted/rejected counts and reasons, per-eye and combined-axis medians, p90 absolute deviations, empirical p10–p90 intervals, head statistics and frame-size counts. `all_recorded_eyes` also includes rejected eye measurements. Calibration rejection counts include repeated/stale deliveries, so they are **not** a unique invalid-camera-frame fraction. Per-eye summaries cover retained records; combined statistics cover accepted feature samples. Retained/dropped counts expose capacity truncation.

`calibration.diagnostics.pairs` exposes:

- Production distance: 2D Euclidean distance between medians of the two-eye mean horizontal/vertical features. Head features are excluded.
- Constant contribution: multiplier × configured floor, **0.0300** by default.
- Pixel contribution: multiplier × the larger target p90 supplied floor. A frame's supplied floor is `1 / min(left eye width, right eye width)` in original pixels.
- Spread contribution: `2.5 × max(target radial p90 spread)`.
- Final required separation: maximum contribution, with all dominant terms listed, including ties.
- Separate horizontal and vertical 1D distances, axis spreads and diagnostic thresholds. Horizontal is relevant for CENTER–LEFT/RIGHT; vertical for CENTER–DOWN. Unrelated-axis spread and radial-tail energy fractions expose irrelevant-axis effects.

Every contribution uses normalized eye-width units. The pixel bound is an assumed scalar radial safeguard in 2D, **not** a per-axis standard deviation. The 1D diagnostic comparisons reuse that safeguard conservatively and do not change production acceptance. Empirical interval overlap is not a confidence interval or proof of generalizable overlap. Assessing this assumption requires repeated real measurements and separate reading validation.

Failure feedback names the measured dominant gate, excessive spread, or insufficient valid samples with actual reasons. It does not infer genuinely overlapping gaze or inadequate resolution from threshold failure alone.

## Exact operator workflow

1. From `C:\Users\kuten\Desktop\case3_proctoring`, run:

   ```powershell
   .\.venv\Scripts\python.exe -m proctoring --calibration-debug
   ```

   Use the default safe configuration. Debug mode refuses an enabled Windows-protection configuration. Do not start an exam during this run.
2. Open the camera. Check actual source dimensions. Keep lighting, camera and seating fixed. Expand **Developer calibration diagnostics**; scroll the setup page to reach all controls.
3. Collect CENTER, LEFT, RIGHT and DOWN. For each **Prepare** button, move your eyes to the indicated physical target and hold through the completion beep. Keep the head comfortable and approximately steady. Defaults: 2 seconds preparation, 3 seconds collection. DOWN means below the physical screen, not a button. The operator supplies labels; the program cannot verify compliance.
4. Select the retained **production fit rejected** attempt. Insufficient/interrupted attempts also remain inspectable before clearing. Incomplete references produce UNKNOWN during exploratory validation. The latest eight snapshots remain in memory; export before additional retries if needed.
5. Check **Enable local numerical export (no images or video)**, click **Export diagnostics…**, and choose `gaze-failed-attempt.json`. Successful calibration is not required. Files are never written automatically; closing loses unexported attempts.
6. With that same attempt selected, click **Start separate validation**. Collect **CENTER → LEFT → RIGHT → DOWN → READING**, clicking **Prepare validation …** for each and following the two beeps. References are frozen; all captures are from new intervals after training, not reused samples or random adjacent-frame splits.
7. **Prepare validation READING** opens the actual quiz area, read-only. Read the question and answer choices normally until the completion beep, then the app returns to diagnostics. The exam remains unstarted, the timer stays stopped, and no answers or misconduct events are recorded. Monitoring failure cancels validation; recover and start a fresh complete pass.
8. Export again as `gaze-failed-attempt-with-validation.json`. Review `validation.confusion_matrix`, per-target predictions/UNKNOWN rates, prediction/rejection reasons, independent per-eye/axis and head distributions, and `reading_offscreen_prediction_rate`. Reading expects CENTER, with UNKNOWN reported separately. Fresh invalid measurements count as UNKNOWN; stale/duplicate/outside-window deliveries are excluded from the rate denominator.
9. Retain the JSON for review. Predictions remain **DEBUG / UNVALIDATED**, including after collection completes. The report says `operator_review_required`, never automatically "passed". Failed production calibration still prevents exam start. Review repeatability, invalid-sample rates, head drift and reading confusion before altering uncertainty assumptions.

Ctrl+Shift+Alt+Q remains the existing emergency recovery shortcut. This workflow does not enable Windows restrictions.

## Verification and limits

- Automated suite: **631 passed in 9.94 seconds** (`artifacts/gaze-diagnostics-tests.txt`). Includes existing session/event/protection regressions plus gate decomposition, source dimensions, subpixel precision, failed exports, independent validation, invalid UNKNOWN rates, reading isolation, exam-start guard and reachable debug controls.
- Actual Windows Qt startup: normal exit; protection **INACTIVE**, calibration not ready, exam start disabled. `artifacts/calibration-startup.json` and `artifacts/calibration-debug-ui.png` document an empty-camera layout check; no webcam image was saved.
- Real camera negotiation: all three profiles returned 640×480 and closed normally. Connectivity/resolution checks do not measure gaze accuracy.
- **Separate human validation: pending.** No labeled human pass was performed. Eyes-only LEFT/RIGHT/DOWN accuracy, UNKNOWN rates, confusion and reading false-offscreen rate on this camera remain unknown.

No production threshold, geometry, classification rule, Windows protection/emergency implementation, phone/person detection, event threshold/hysteresis, timer/recovery or normal evidence behavior was changed. The patch corrects missing observability and the operator validation path; an algorithm correction awaits measurements.

Production files: `vision/types.py`, `vision/face.py`, `vision/monitor.py`, `vision/calibration.py`, new `vision/diagnostic_validation.py`, `ui/calibration.py`, new `ui/diagnostic_panel.py`, `ui/window.py`. Tests: `test_face_features.py`, `test_real_monitor.py`, `test_ui_stage3.py`, and new `test_calibration_diagnostics.py`, `test_diagnostic_validation.py`, `test_diagnostic_ui.py`.
