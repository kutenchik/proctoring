"""Reporting checks do not need camera hardware or model inference."""
import importlib.util
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location("benchmark_script", Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_percentile_uses_nearest_rank_not_next_zero_based_index():
    assert benchmark.distribution(list(range(1, 21))) == {
        "samples": 20, "mean_ms": 10.5, "p95_ms": 19,
    }


def test_empty_and_single_sample_distribution():
    assert benchmark.distribution([]) == {"samples": 0, "mean_ms": None, "p95_ms": None}
    assert benchmark.distribution([12.345]) == {"samples": 1, "mean_ms": 12.35, "p95_ms": 12.35}


def test_provider_wheel_version_fallback(monkeypatch):
    def version(name):
        if name == "onnxruntime-gpu":
            return "1.23.0"
        raise PackageNotFoundError(name)
    monkeypatch.setattr(benchmark, "version", version)
    assert benchmark.package_version("onnxruntime", ("onnxruntime-gpu",)) == "1.23.0"
    assert benchmark.package_version("missing") is None


@pytest.mark.parametrize("timestamp,error,expected", [
    (9., None, True),
    (9., "Webcam disconnected", False),
    (8., None, False),
    (7., None, False),
    (11., None, False),
    (float("nan"), None, False),
])
def test_camera_must_be_fresh_and_error_free_at_end(timestamp, error, expected):
    camera = SimpleNamespace(error=error, latest=SimpleNamespace(timestamp=timestamp))
    healthy, reason = benchmark.camera_health(camera, 10., 2.)
    assert healthy is expected
    assert (reason is None) is expected


def test_camera_without_frames_is_unhealthy():
    assert not benchmark.camera_health(SimpleNamespace(error=None, latest=None), 10., 2.)[0]
