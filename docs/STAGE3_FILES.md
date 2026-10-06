# Stage 3 implementation inventory

Stage 3 connects the existing exam/session/event system to local camera inference.
Windows keyboard and window restriction hooks remain disabled.

## New modules and tools

Paths below are relative to the project root.

| Files | Responsibility |
|---|---|
| `src/proctoring/vision/settings.py`, `types.py` | Configurable camera/CV settings; normalized boxes, head pose, face measurements, results and health |
| `src/proctoring/vision/camera.py` | OpenCV capture thread, one latest-frame slot, monotonic capture timestamps and reconnect |
| `src/proctoring/vision/yolo.py` | Local YOLO11n ONNX loading, CPU/optional GPU provider selection, letterboxing, person/phone detection and NMS |
| `src/proctoring/vision/face.py` | Local CPU MediaPipe Face Landmarker, primary-face selection, head pose and iris geometry |
| `src/proctoring/vision/calibration.py` | Thread-safe in-memory session samples, quality checks and calibrated gaze classification |
| `src/proctoring/vision/rules.py` | Tiny/noisy detection filtering, raised-phone geometry and existing-event observation mapping |
| `src/proctoring/vision/monitor.py`, `health.py` | Background inference scheduling, latest results, capture/result/heartbeat freshness and failure status |
| `src/proctoring/ui/calibration.py`, `preview.py` | Guided CENTER/LEFT/RIGHT/DOWN collection and lightweight annotated preview |
| `src/proctoring/storage/snapshots.py` | Bounded background JPEG writer with error reporting |
| `scripts/fetch_models.py`, `models/README.md` | One-time preparation of local model files with pinned sources and SHA-256 verification |
| `scripts/benchmark.py` | Camera-only, live CPU and explicitly labelled blank-frame model diagnostics |

Required local binaries are `models/yolo11n.onnx` and
`models/face_landmarker.task`. They are excluded from Git. Inference never
downloads files or sends frames to a remote service.

## Updated integration files

| Files | Change |
|---|---|
| `src/proctoring/__main__.py` | Camera mode by default; explicit `--synthetic` option |
| `src/proctoring/config.py`, `config/default.toml` | Validated vision settings and paths while preserving event/timer defaults |
| `src/proctoring/controller.py` | Calibration/health startup gates, vision observations, monitoring recovery and snapshot evidence |
| `src/proctoring/ui/window.py` | Camera setup, calibration, live monitoring metrics, retry controls and existing quiz/PIN/summary flow |
| `src/proctoring/storage/session_store.py` | Snapshot queue integration and successful evidence paths in the final summary |
| `pyproject.toml`, `requirements.lock` | Runtime CV/benchmark dependencies |
| `.gitignore`, `README.md` | Generated model/evidence exclusions, startup, configuration, offline preparation and limitations |

The existing `events/engine.py`, `session.py`, quiz, PIN and no-op protection
architecture remain the owners of alert timing, exam time and protected controls.

## Data flow

1. The capture thread publishes only the newest BGR frame with its monotonic
   acquisition timestamp. Slow consumers do not accumulate a queue of old frames.
2. One inference worker schedules Face Landmarker and YOLO independently. A
   combined event result requires fresh face and object measurements for the
   same frame; face-only updates never refresh old phone evidence.
3. Face landmarks produce normalized iris positions and head yaw/pitch features.
   MediaPipe does not supply gaze labels. The current session's four calibrated
   references classify these features; poor or ambiguous measurements are UNKNOWN.
4. Pure rules map measurements to existing observations. They never create alerts.
   The existing event engine applies thresholds, deduplication and hysteresis.
5. Camera errors, stale frames/results and inference failures feed the existing
   monitoring pause/recovery path. Fresh frames without a face remain a review
   condition, rather than a pipeline failure. Proctor pause remains independent.
6. The controller journals lifecycle/event changes. When enabled, event activation
   queues one snapshot; the final summary records successful paths and write errors.

No continuous video or calibration samples are saved. Real restrictions are still
disabled; the existing application shortcut and watchdog retain emergency recovery.

## Added automated coverage

- `tests/test_camera.py`, `test_real_monitor.py`, `test_vision_health.py`: camera,
  worker scheduling/failures, result delivery and freshness.
- `tests/test_yolo.py`, `test_face_features.py`, `test_vision_rules.py`: model
  output handling, landmark geometry, person/phone filtering and observation mapping.
- `tests/test_calibration.py`: sample deduplication, quality, separation,
  classification and session reset.
- `tests/test_config_vision.py`, `test_controller_camera.py`, `test_ui_stage3.py`,
  `test_snapshots.py`: configuration, lifecycle integration, Qt camera/calibration
  flow and evidence persistence.
- `tests/test_benchmark.py`: percentile reporting, runtime wheel metadata and
  end-of-test camera health.

Benchmark measurements and hardware validation are reported separately from these
deterministic tests; this inventory does not imply a camera-performance result.
