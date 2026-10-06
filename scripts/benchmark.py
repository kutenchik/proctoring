"""Local CPU/camera diagnostic. Saves metrics only, never camera images or video."""
import argparse
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

from proctoring.clock import SystemClock
from proctoring.config import DEFAULT_CONFIG, load_config
from proctoring.vision.camera import LatestFrameCamera
from proctoring.vision.monitor import RealMonitor


def distribution(values):
    if not values:
        return {"samples": 0, "mean_ms": None, "p95_ms": None}
    ordered = sorted(values)
    return {"samples": len(values), "mean_ms": round(statistics.mean(values), 2),
            "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 2)}


def package_version(name, alternatives=()):
    """Record runtime versions even when an equivalent provider wheel is used."""
    for candidate in (name, *alternatives):
        try:
            return version(candidate)
        except PackageNotFoundError:
            continue
    return None


def camera_health(camera, now, stale_seconds):
    """A camera that delivered earlier frames may still be unavailable now."""
    error = camera.error
    if error:
        return False, error
    latest = camera.latest
    if latest is None:
        return False, "No camera frames received"
    age = now - latest.timestamp
    if not math.isfinite(age) or age < 0 or age >= stale_seconds:
        return False, "Camera frames stale or timestamp invalid"
    return True, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seconds", type=float, default=20., help="Measurement window after warmup")
    parser.add_argument("--warmup", type=float, default=3.)
    parser.add_argument("--camera-only", action="store_true")
    parser.add_argument("--models-only", action="store_true", help="Blank-frame diagnostic; not webcam performance")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seconds <= 0 or args.warmup < 0 or (args.camera_only and args.models_only):
        parser.error("Use positive seconds, nonnegative warmup, and one mode")
    config = replace(load_config(args.config).vision, prefer_gpu=False)
    clock = SystemClock()
    import psutil
    process = psutil.Process()
    report = {"mode": "camera_only" if args.camera_only else "blank_frame_models_only" if args.models_only else "live_cpu",
              "platform": platform.platform(), "python": platform.python_version(),
              "cpu": platform.processor(), "logical_cpus": psutil.cpu_count(),
              "ram_gib": round(psutil.virtual_memory().total / 1024 ** 3, 2),
              "versions": {
                  "numpy": package_version("numpy"),
                  "opencv-contrib-python": package_version("opencv-contrib-python", ("opencv-python", "opencv-contrib-python-headless", "opencv-python-headless")),
                  "onnxruntime": package_version("onnxruntime", ("onnxruntime-gpu",)),
                  "mediapipe": package_version("mediapipe"),
              },
              "requested_capture": f"{config.capture_width}x{config.capture_height}",
              "configured_yolo_size": config.yolo_input_size, "configured_yolo_fps": config.yolo_fps,
              "configured_face_fps": config.face_fps}
    yolo_times, face_times, cpu_values, process_values = [], [], [], []
    count, healthy_polls, polls = 0, 0, 0
    monitor = camera = detector = face = None
    try:
        if args.models_only:
            import numpy as np
            from proctoring.vision.yolo import YoloDetector
            from proctoring.vision.face import FaceAnalyzer
            detector, face = YoloDetector(config), FaceAnalyzer(config)
            frame = np.zeros((config.capture_height, config.capture_width, 3), dtype=np.uint8)
            report.update(provider=detector.provider, input_size=f"{detector.input_width}x{detector.input_height}")
        elif args.camera_only:
            camera = LatestFrameCamera(config, clock)
            camera.start()
        else:
            monitor = RealMonitor(config, clock)
            monitor.start()
        started = clock.monotonic()
        measure_at = started + args.warmup
        finish_at = measure_at + args.seconds
        last_sequence = None
        first_sequence = final_sequence = None
        psutil.cpu_percent()
        process.cpu_percent()
        next_cpu_at = measure_at
        while clock.monotonic() < finish_at:
            now = clock.monotonic()
            measuring = now >= measure_at
            if args.models_only:
                before = time.perf_counter()
                detector.detect(frame)
                yolo_ms = (time.perf_counter() - before) * 1000
                before = time.perf_counter()
                face.detect(frame, clock.monotonic())
                face_ms = (time.perf_counter() - before) * 1000
                if measuring:
                    yolo_times.append(yolo_ms)
                    face_times.append(face_ms)
                    count += 1
            elif camera is not None:
                captured = camera.latest
                if measuring and captured is not None and captured.sequence != last_sequence:
                    if first_sequence is None:
                        first_sequence = captured.sequence
                    final_sequence = captured.sequence
                    count += 1
                    last_sequence = captured.sequence
                if captured is not None:
                    report["actual_capture"] = f"{captured.image.shape[1]}x{captured.image.shape[0]}"
            else:
                observation = monitor.sample(now)
                if measuring:
                    polls += 1
                    healthy_polls += int(monitor.health(now).healthy)
                    if observation is not None:
                        result = monitor.delivered_result
                        yolo_times.append(result.yolo_latency_ms)
                        face_times.append(result.face_latency_ms)
                        count += 1
                frame = monitor.latest_frame
                if frame is not None:
                    report["actual_capture"] = f"{frame.shape[1]}x{frame.shape[0]}"
            if measuring and now >= next_cpu_at:
                cpu_values.append(psutil.cpu_percent())
                # Normalize psutil's multicore process percentage to machine capacity.
                process_values.append(process.cpu_percent() / (psutil.cpu_count() or 1))
                next_cpu_at = now + .5
            time.sleep(.005 if args.models_only else .01)
        measured = clock.monotonic() - measure_at
        report.update(measured_seconds=round(measured, 2), observed_samples=count,
                      yolo_latency=distribution(yolo_times), mediapipe_latency=distribution(face_times),
                      system_cpu_percent=round(statistics.mean(cpu_values), 2) if cpu_values else None,
                      process_cpu_percent_of_machine=round(statistics.mean(process_values), 2) if process_values else None,
                      process_memory_mib=round(process.memory_info().rss / 1024 ** 2, 2))
        if camera:
            healthy, error = camera_health(camera, clock.monotonic(), config.frame_stale_seconds)
            report.update(capture_fps=round((final_sequence - first_sequence) / measured, 2)
                          if final_sequence is not None else 0., camera_backend=camera.backend,
                          error=error, success=count > 0 and healthy)
        elif monitor:
            report.update(monitor.metrics)
            report.update(combined_monitoring_fps=round(count / measured, 2),
                          healthy_percent=round(100 * healthy_polls / max(1, polls), 2),
                          success=count > 0 and monitor.health(clock.monotonic()).healthy)
        else:
            report.update(combined_unthrottled_blank_frame_fps=round(count / measured, 2), success=count > 0)
    except Exception as error:
        report.update(success=False, error=f"{type(error).__name__}: {error}")
    finally:
        for resource in (monitor, camera):
            if resource:
                resource.stop()
        for resource in (detector, face):
            if resource and hasattr(resource, "close"):
                resource.close()
    output = json.dumps(report, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
