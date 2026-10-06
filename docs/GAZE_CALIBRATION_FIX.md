# Gaze calibration correction — 2026-10-05

**Follow-up:** human calibration still fails after this earlier correction. See [current rejection diagnostics and operator workflow](GAZE_DIAGNOSTIC_RUN.md). The automated results below do not establish eyes-only accuracy on this camera.

## Diagnosis and evidence

The screenshot establishes that CENTER and DOWN failed the old separation gate; it does not prove their distributions overlap. No numerical samples from that attempt were saved, so the exact contribution of eyelid movement, blink rejection, collection contamination and camera resolution cannot be reconstructed.

Inspection found reproducible implementation problems:

1. **Moving vertical reference.** The old feature subtracted the midpoint of the upper/lower lids from the iris center. When lids follow the iris down, this subtracts the gaze signal itself. The replacement measures displacement from the eye-corner axis, with both axes normalized by eye width in pixel coordinates. It does not divide by a narrowing eyelid aperture.
2. **Mixed units and head dominance.** The old Euclidean metric combined iris displacement in eye widths and yaw/pitch divided by 60. A 6-degree head change contributed 0.1 to distance, while a 4-pixel iris movement in an 80-pixel eye contributed at most 0.05. Head movement could supply calibration separation even when eye measurements overlapped.
3. **Collection timing.** The old click handler only excluded the last displayed result. An older captured frame still undergoing inference could arrive after the click and be accepted. Collection started immediately, so returning from the button to the target had no settling interval. Calibration consumed the slower combined YOLO result even though fresh face-only measurements were available.

The geometry regression uses fixed eye corners 80 pixels apart, eyelids initially 10 pixels above/below the axis, fixed head pose, and an iris initially on the axis. Moving the iris and both lids down 4 pixels produces:

| Measurement | CENTER | DOWN |
|---|---:|---:|
| Old vertical feature, eyelid midpoint reference | 0.500 | 0.500 |
| Corrected vertical feature, corner-axis reference | 0.500 | 0.550 |
| Openness / eye width | 0.250 | 0.250 |
| Head yaw / pitch | 0° / 0° | 0° / 0° |

This is a deterministic synthetic reproduction, **not a measurement of the user's eyes or evidence of real eyes-only accuracy**. The executable measurements are saved in `artifacts/calibration-geometry-reproduction.json`: corrected CENTER–DOWN eye separation 0.050, required separation 0.0375 for the 80-pixel fixture, and head separation 0 degrees.

## Geometry and classification

MediaPipe supplies landmarks, not gaze labels. Its left-eye connection group uses corners 362/263 and iris center 473; its right-eye group uses 33/133 and 468. Coordinates refer to the original camera image: horizontal increases along image-right, vertical along image-down. The application does not mirror inference or preview coordinates. User LEFT/RIGHT labels are learned from session targets rather than inferred from anatomical eye names.

References: [official eye connection constants](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/python/solutions/face_mesh_connections.py), [official iris landmark mapping](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/face_landmark/tensors_to_face_landmarks_with_attention.pbtxt), [FaceLandmarkerResult](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerResult).

The fixed blink/geometry limits were not relaxed. Openness below 0.10 eye widths still rejects a measurement. This could reject naturally narrow downward-looking eyes; the developer panel now reveals that reason instead of treating it as a calibration separation problem. Occlusion, inconsistent eyes, non-finite geometry and very small eyes remain invalid.

Calibration separation and gaze labels now use iris features only. Head medians/spread remain separately visible; head rotation cannot rescue overlapping eye measurements or create an eye-gaze label. A large departure from the calibrated head range returns UNKNOWN because that geometry is unvalidated.

The eye-separation requirement combines an assumed uncertainty floor with measured spread: the larger of three times the measurement-noise floor and 2.5 times the target's 90th-percentile eye spread. The noise floor is at least 0.01 eye widths and, when pixel measurements are available, at least one pixel divided by the smaller eye width. This is an assumed safeguard, not measured landmark accuracy. The existing 0.12 eye-spread ceiling remains. The old `calibration_min_separation` mixed eye/head metric is accepted only for configuration compatibility and is not used; it was removed from supplied configuration files. Diagnostics show the actual required separation and signal/noise ratio.

Off-screen labels require proximity to the calibrated off-screen reference, with a conservative gap between the center region and those references. Merely moving away from the exact center is insufficient. Ambiguous measurements return UNKNOWN, never an automatic CENTER. This remains an approximate four-target calibration; it does not locate gaze at exact screen pixels or guarantee that every reading position can be separated from off-screen gaze.

## Collection and diagnostics

Each target has a configurable preparation countdown (default 2 seconds), then a fixed collection interval (default 3 seconds). Start/completion audio cues let the student keep looking at the target. LEFT/RIGHT mean beyond the corresponding screen edge; DOWN means below the physical screen, not an application button. No deliberate head rotation is required.

The UI receives an atomic face/capture-timestamp pair independently of YOLO. Only fresh, valid, unique captures within the collection interval are eligible. Preparation frames, older in-flight frames, repeated captures and late results are excluded. Collection uses the whole interval and requires at least 20 accepted samples by default, with bounded memory. An insufficient target is discarded before retry. Monitoring interruption clears every target and returns to CENTER because the camera/baseline may have changed; failed final fits also require a fresh baseline. Completion or interruption sounds let the student look back without watching progress.

Run with real Windows restrictions disabled:

```powershell
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

The developer panel shows each eye's horizontal/vertical feature, openness, width, validity and rejection reason; head yaw/pitch; eye-gaze estimate; per-target accepted/rejected counts and reasons; medians/spreads; and CENTER–DOWN eye separation versus its required threshold, separately from head separation. The debug launch refuses an enabled protection configuration. Normal launches hide diagnostics.

No camera images or raw calibration samples are persisted by this change. Calibration remains session-local and a failed fit still prevents exam start. Windows protection, emergency recovery, event durations/hysteresis, exam timing, monitoring recovery, phone/person detection and evidence storage were not redesigned. Because UI/configuration source changed, the existing protection validation fingerprint must be renewed before a later protected run; calibration debugging does not enable restrictions.

## Validation

The automated regression suite passed: **562 tests in 13.21 seconds**, covering capture interval admission, stale/reused samples, unchanged-head eye-only references, genuine overlap, mixed UI/target samples, blink/invalid geometry, coordinate conventions, reading-region conservatism and baseline invalidation. Evidence: `artifacts/calibration-tests.txt`. A bounded application startup check opened the real Qt window in safe mode with developer diagnostics visible, the exam start gate disabled and protection INACTIVE; it exited normally. Evidence: `artifacts/calibration-startup.json` and `artifacts/calibration-debug-ui.png` (the preview was empty; this screenshot contains no camera image).

The isolated camera check succeeded outside the sandbox: **90 frames in 3 seconds, 29.67 FPS**, actual stream **640×480** despite a **1280×720** request. It saved metrics only (`artifacts/calibration-camera-check.json`). Camera connectivity is not validation of gaze classification.

The updated CPU vision pipeline also ran successfully: **100% healthy polls**, approximately **4.0 combined monitoring FPS**, mean YOLO latency **30.61 ms**, mean MediaPipe latency **6.62 ms**, over a three-second measurement window (`artifacts/calibration-live-pipeline.json`). This verifies startup/inference integration, not the semantic correctness of a person's gaze direction.

Changed production files: `vision/face.py`, `vision/types.py`, `vision/calibration.py`, `vision/monitor.py`, `vision/settings.py`, `ui/calibration.py`, `ui/window.py`, `config.py`, `__main__.py`, and both supplied TOML configurations. Regression changes: `test_face_features.py`, `test_calibration.py`, `test_calibration_ui.py`, `test_ui_stage3.py`, `test_real_monitor.py`, and `test_config_vision.py`. README and this report document the behavior and remaining validation.

| Human webcam scenario | Result |
|---|---|
| CENTER fixation | Pending |
| Eyes-only LEFT / RIGHT / DOWN, approximately fixed head | Pending |
| Head movement with and without eye movement | Pending |
| Ordinary reading across the quiz | Pending |
| Blinks and a brief glance back at the UI during collection | Pending |

**Eyes-only DOWN has not been validated with a labeled human webcam run.** The new diagnostics distinguish weak eye signal, narrow-eye rejection, excessive spread and head movement; they do not manufacture proof that the current camera can resolve a particular student's eye movement.
