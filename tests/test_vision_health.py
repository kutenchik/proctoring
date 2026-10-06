from dataclasses import replace

import pytest

from proctoring.vision.health import assess_health
from proctoring.vision.settings import VisionConfig


def health(**kwargs):
    values = dict(config=VisionConfig(), now=10., started_at=0., frame_at=9.9,
                  result_at=9.8, heartbeat_at=9.9)
    values.update(kwargs)
    return assess_health(**values)


def test_fresh_pipeline_healthy_without_any_face_requirement():
    assert health().healthy


@pytest.mark.parametrize("field,stamp,label", [("frame_at", 8., "Camera frames"),
                                                 ("result_at", 8., "Vision results"),
                                                 ("heartbeat_at", 5., "heartbeat")])
def test_stale_boundary_is_inclusive(field, stamp, label):
    result = health(**{field: stamp})
    assert not result.healthy
    assert label in result.reason
    assert result.since == 10.


def test_just_before_stale_boundary_stays_healthy():
    assert health(frame_at=8.001, result_at=8.001, heartbeat_at=5.001).healthy


def test_reports_earliest_expired_deadline_when_ui_tick_is_late():
    result = health(now=20., frame_at=5., result_at=6., heartbeat_at=8.)
    assert result.since == 7.


def test_exception_immediately_fails_health():
    result = health(error="Inference exception", error_at=9.95)
    assert not result.healthy
    assert result.reason == "Inference exception"
    assert result.since == 9.95


@pytest.mark.parametrize("field", ["frame_at", "result_at", "heartbeat_at"])
def test_missing_first_data_remains_unhealthy(field):
    assert not health(**{field: None}).healthy


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), 11.])
def test_invalid_or_future_timestamp_fails_health(timestamp):
    assert not health(result_at=timestamp).healthy


def test_stopped_monitor_never_healthy():
    assert not health(stopped=True).healthy


def test_stale_thresholds_are_configurable():
    result = health(config=replace(VisionConfig(), result_stale_seconds=.1), result_at=9.8)
    assert not result.healthy
    assert result.since == pytest.approx(9.9)
