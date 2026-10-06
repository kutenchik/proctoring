# Face positioning before calibration — 2026-10-06

The camera preview now shows a rectangular guide with corner brackets. It is amber while positioning is insufficient and green when ready. The rectangle uses exactly the same source-image coordinates as the containment check, including when the preview is resized or letterboxed. It appears before and during calibration and is removed for an exam.

Live feedback includes **Face aligned**, **Move closer**, **Center your face**, **Keep both eyes visible**, **Face the screen naturally**, and **Hold still**. The progress bar measures positioning stability, not gaze confidence or expected accuracy.

## Exact default checks

| Check | Requirement |
|---|---|
| Monitoring | Healthy, with a finite, fresh capture timestamp. A latest measurement older than 0.5 seconds cannot authorize collection, even if the broader monitoring timeout has not expired. |
| Guide containment | Entire detected face bounding box lies inside x=0.18–0.82 and y=0.08–0.92 of the original image. At 640×480, these are x=115.2–524.8 and y=38.4–441.6 pixels. |
| Source size | Original frame dimensions must be available. Requested camera resolution and resized preview dimensions are not substituted. |
| Face size | Detected face width at least 140 source pixels and height at least 160 source pixels. |
| Both eyes | Both existing per-eye landmark diagnostics valid; finite eye widths of at least 32 source pixels each. Combined eye features must remain valid/finite and the existing measurement quality must be at least 0.45. |
| Frontal head | Absolute yaw and pitch at most 15°, absolute roll at most 12°, with a finite measured pose. Natural forward-facing posture; no exaggerated rotation. |
| Stable position | At least 0.75 seconds and three distinct captures. Face center must stay within 0.02 image width/height on each axis of the stability anchor; face width and height must stay within 10% of the anchor. |
| Continuity | Adjacent positioning captures no more than 0.5 seconds apart. Missing/invalid data, excessive movement, resolution change or backward timestamps reset readiness. Duplicate UI polls never accumulate stability time. |

All positioning limits are configurable in `[vision.alignment]` in `config/default.toml`. Omitted values use `AlignmentConfig` defaults. Unknown, malformed or invalid settings fail at configuration loading. These are prototype positioning defaults, not measured guarantees of gaze accuracy. “Both eyes visible” means usable bilateral landmark measurements; the guide contains detected face bounds, not independently verified hair/head silhouette.

## Collection and diagnostics

**Prepare is disabled until alignment is sufficient.** Its handler checks freshness/readiness again at click time, so a stale enabled button cannot authorize a collection. Passing alignment begins the existing preparation countdown; collection cannot start accepting samples until alignment is still sufficient.

During a collection window, invalid alignment prevents that measurement from entering calibration. The fixed window is not extended to hide missing samples. The student must regain readiness, and insufficient accepted samples still require a retry. Existing eye-invalid reasons are preserved; positioning failures add reasons such as `alignment_face_not_contained`, `alignment_face_too_small`, `alignment_head_not_frontal`, and `alignment_hold_still`. The existing failed-attempt diagnostics/export retain those reasons and numerical face measurements.

The live developer diagnostics expose the current positioning state, measured face/eye sizes, pose, stability elapsed time/count, and the applied alignment policy. Existing pixel-floor/spread gate diagnostics remain intact. A green guide cannot make rejected gaze calibration ready or authorize an exam.

Separate operator-labeled validation remains observational: the guide can provide feedback, but this positioning filter does not remove held-out measurements or improve the reported UNKNOWN rate by discarding invalid samples. Its existing admission and reporting rules remain unchanged.

No gaze geometry/classifier, calibration separation threshold, event timing, phone/person detection, monitoring recovery, Windows restriction implementation or evidence persistence behavior was changed. Real restrictions remain disabled in the supplied default configuration and during verification. No images or video are saved by alignment.

## Files

- New `src/proctoring/vision/alignment.py`: independent positioning policy, status and timestamp-driven state.
- `src/proctoring/vision/settings.py`, `src/proctoring/config.py`, `config/default.toml`: configurable policy and validation.
- `src/proctoring/ui/calibration.py`: readiness indicator, Prepare/sample admission checks and diagnostic feedback.
- `src/proctoring/ui/preview.py`: source-coordinate guide and live feedback.
- `src/proctoring/ui/window.py`: setup/validation preview integration, guide removal for exams and scrollable setup controls.
- New `tests/test_alignment.py`, `test_alignment_preview.py`, `test_alignment_ui.py`; updated `test_config_vision.py`, `test_calibration_ui.py`, `test_diagnostic_ui.py`, `test_ui_stage3.py`.

## Verification and manual check

Full automated suite: **763 passed in 9.95 seconds** (`artifacts/alignment-tests.txt`). New coverage includes 80 alignment-model tests, 7 preview tests and 13 collection-UI tests, plus configuration validation and updated existing UI fixtures. Tests cover each rejection condition, unique capture-time stability, stale-button rejection, skipped misaligned samples, unchanged failed-fit behavior and visible letterboxed guide boundaries.

The native Windows UI check uses synthetic 640×480 frames, opens no webcam and starts no exam. It verifies green/aligned enables Prepare, moving the face outside the guide disables it, gaze calibration stays unready, and protection remains INACTIVE. Numerical result: `artifacts/alignment-layout.json`; screenshots: `artifacts/alignment-ready-ui.png` and `artifacts/alignment-blocked-ui.png`. These screenshots contain no human camera images. The ordinary entry-point startup check also remains in safe mode.

Run the actual app with restrictions disabled:

```powershell
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

Open the camera, center the detected face inside the guide, and move closer only if requested. Face the screen naturally and wait for **Face aligned**. Move outside the guide, turn the head moderately, or cover one eye to check feedback and the disabled Prepare button; then realign before collecting the existing gaze targets. During collection, keep the face steady while moving only the eyes. Review any positioning rejection reasons alongside the existing gaze diagnostics.

**Human webcam validation is pending.** This improves sample admission and usability; it does not establish that the current camera reliably distinguishes off-screen gaze from normal quiz reading.
