# Stage 3 validation — 2026-10-04

Environment: Windows 10 build 19045, Python 3.11.5, AMD CPU with 12 logical
processors, 31.1 GiB installed RAM. This is not a test on the minimum 8 GB machine.
Other desktop applications were running; CPU usage is not an isolated laboratory
measurement. All model inference used CPU, with no NVIDIA/CUDA requirement.

## Automated checks

- `python -m pytest -q`: **327 passed** in 7.70 seconds.
- `python -m pip check`: no broken requirements.
- `python -m compileall -q src scripts`: passed.
- `python scripts/fetch_models.py`: verified both existing local model hashes.
- Native desktop launch: camera setup window and calibration controls verified
  through Windows accessibility. Qt setup rendering also inspected. Native
  screenshot capture timed out, so no screenshot-based desktop claim is made.

The suite includes actual OpenCV preprocessing/JPEG persistence, mocked model
outputs, camera worker failure/recovery, calibration calculations, Qt interactions,
and exact 14.9/15.0-second session recovery boundaries. The existing event engine
and exam timer were retained.

## Real model CPU benchmark

Command:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py --models-only --seconds 20 --output artifacts/benchmark-cpu-models.json
```

This diagnostic processes generated black 1280×720 images using the real local
models. It is deliberately **not** a live-camera benchmark or detection-accuracy
measurement. The downloaded ONNX model has fixed 640×640 input, which overrides
the dynamic-model configuration value of 416.

| Measurement | Result |
|---|---:|
| Measured duration | 20.00 s |
| Inference pairs | 556 |
| YOLO mean / p95 | 27.92 / 30.26 ms |
| MediaPipe mean / p95 | 2.48 / 3.01 ms |
| Unthrottled blank-frame pairs | 27.80 FPS |
| Process resident memory | 232.68 MiB |
| Process CPU, normalized to whole machine | 15.86% |
| Whole-machine CPU | 55.34% |
| YOLO provider | CPUExecutionProvider |

Face-present frames may cost more than the blank-frame path, and the application
deliberately limits inference frequency to preserve responsiveness.

## Webcam and running application

The USB2.0_Camera is detected. Standalone probes initially received zero frames
through MSMF/DirectShow, including a 640×480/15 FPS fallback. The live CPU script
correctly reported failure and zero monitoring FPS. Later inspection of the
running desktop app showed **healthy monitoring**, approximately **31.5 capture
FPS**, **4.4 monitoring FPS**, **26 ms YOLO** and **2 ms face latency**. The app had
collected 20 CENTER calibration samples and was waiting at LEFT. These are live
panel readings, not aggregate benchmark statistics. Another process using the
same camera can prevent the standalone diagnostic from acquiring it.

Initial diagnostic outputs: `artifacts/camera-test.json` and
`artifacts/benchmark-cpu-live.json`. Model-only measurements:
`artifacts/benchmark-cpu-models.json`. No diagnostic saves camera images or video.

## Remaining empirical validation

Rehearse all four calibration poses on the actual exam seating setup, then
demonstrate phone visible/raised, a second person, face absence and gaze events.
Measure live rates with exclusive webcam access, and repeat on the target 8 GB
machine. Detection sensitivity/false-positive rates, GPU acceleration, and physical
disconnect/reconnect during an actual calibrated exam are not validated by the
mock tests. These limitations do not enable Windows restrictions; those remain
disabled for the next implementation stage.
