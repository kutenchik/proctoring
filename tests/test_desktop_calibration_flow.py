from dataclasses import replace

import pytest

from proctoring.clock import FakeClock
from proctoring.desktop_bridge.calibration_flow import CalibrationFlow
from proctoring.desktop_bridge.protocol import BridgeError
from proctoring.vision.calibration import Calibration
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import Box, EyeDiagnostic, GazeDiagnostics
from test_alignment import result, face


GEOMETRY = {'geometry_id': 'display-1', 'center_visible': True}


def measurement(stamp, x=.5, y=.5, **changes):
    eye = EyeDiagnostic(horizontal=x, vertical=y, opening=.25, valid=True, reason='', width_pixels=35.)
    return result(stamp, face(features=(x, y, 0., 0.), diagnostics=GazeDiagnostics(eye, eye, True, ''), **changes))


def setup_flow():
    config = replace(VisionConfig(), calibration_samples=3, calibration_preparation_seconds=.2,
                     calibration_collection_seconds=.5, calibration_max_collection_seconds=1.)
    clock = FakeClock()
    flow = CalibrationFlow(Calibration(config), config, clock)
    for stamp in (0., .375, .75):
        clock.now = stamp
        flow.update(measurement(stamp), stamp, True)
    assert flow.state()['alignment']['ready']
    return flow, clock


def feed(flow, clock, seconds=.1, x=.5, y=.5, **changes):
    clock.advance(seconds)
    flow.update(measurement(clock.now, x, y, **changes), clock.now, True)


def collect(flow, clock, x=.5, y=.5):
    token, target = flow.presentation_token, flow.direction.value
    flow.present(token, target, GEOMETRY)
    for _ in range(12):
        feed(flow, clock, x=x, y=y)
        if flow.phase not in {'preparing', 'collecting'}:
            return
    pytest.fail('Collection did not reach its bounded outcome')


def test_target_must_be_presented_before_prep_and_capture_window_starts():
    flow, clock = setup_flow()
    flow.begin()
    token = flow.presentation_token
    for _ in range(6):
        feed(flow, clock)
    assert flow.phase == 'awaiting_presentation'
    assert sum(flow.calibration.counts.values()) == 0
    assert flow.window is None
    flow.begin()
    assert flow.presentation_token == token
    flow.present(token, 'CENTER', GEOMETRY)
    start = flow.window.starts_at
    feed(flow, clock)
    flow.present(token, 'CENTER', GEOMETRY)
    assert flow.window.starts_at == start
    assert sum(flow.calibration.counts.values()) == 0
    with pytest.raises(BridgeError, match='no longer matches'):
        flow.present('old', 'CENTER', GEOMETRY)


def test_complete_real_fit_uses_backend_samples_and_separate_target_ack():
    flow, clock = setup_flow()
    flow.begin()
    positions = [(.5, .5), (.2, .5), (.8, .5), (.5, .8)]
    for index, (x, y) in enumerate(positions):
        assert flow.phase == 'awaiting_presentation'
        assert len(flow.completed) == index
        collect(flow, clock, x, y)
    state = flow.state()
    assert state['phase'] == 'complete' and state['ready']
    assert state['completed_targets'] == ['CENTER', 'LEFT', 'RIGHT', 'DOWN']
    assert state['cue_sequence'] == 8  # Backend start/end, not animation completion.


def test_overlapping_target_fit_is_rejected_even_after_all_collections_complete():
    flow, clock = setup_flow()
    flow.begin()
    for _ in range(4):
        collect(flow, clock)
    assert flow.phase == 'fit_failed'
    assert not flow.state()['ready']
    flow.cancel()
    assert flow.phase == 'fit_failed'
    with pytest.raises(BridgeError):
        flow.begin()
    attempt = flow.attempt_id
    flow.reset()
    assert flow.attempt_id != attempt
    assert not any(flow.calibration.counts.values())
    assert any(row['attempt_id'] == attempt for row in flow.state()['retained_attempts'])


def test_resize_invalidates_incompatible_baseline_and_stale_ack():
    flow, clock = setup_flow()
    flow.begin()
    collect(flow, clock)
    attempt, token = flow.attempt_id, flow.presentation_token
    flow.geometry_changed({'geometry_id': 'resized', 'center_visible': True})
    assert flow.phase == 'idle'
    assert flow.attempt_id != attempt
    assert not any(flow.calibration.counts.values())
    with pytest.raises(BridgeError):
        flow.present(token, 'LEFT', GEOMETRY)


def test_offscreen_center_and_unaligned_begin_are_rejected():
    flow, clock = setup_flow()
    flow.begin()
    with pytest.raises(BridgeError, match='physical screen center'):
        flow.present(flow.presentation_token, 'CENTER', {'geometry_id': 'a', 'center_visible': False})
    flow.cancel()
    feed(flow, clock, box=Box(.02, .2, .42, .8))
    with pytest.raises(BridgeError):
        flow.begin()


def test_unique_capture_admission_and_bounded_invalid_measurements():
    flow, clock = setup_flow()
    flow.begin()
    flow.present(flow.presentation_token, 'CENTER', GEOMETRY)
    feed(flow, clock, .2)
    count = flow._count()
    for _ in range(5):
        flow.update(flow.current_result, clock.now, True)
    assert flow._count() == count
    # Eye-invalid samples retain valid face geometry but cannot fill a target.
    for _ in range(11):
        clock.advance(.1)
        invalid = result(clock.now, face(features=None))
        flow.update(invalid, clock.now, True)
    assert flow.phase == 'target_failed'
    assert not flow.calibration.ready
    assert flow._count() == count


def test_monitor_loss_requires_new_baseline_not_same_attempt_resume():
    flow, clock = setup_flow()
    flow.begin()
    collect(flow, clock)
    attempt = flow.attempt_id
    flow.update(None, clock.now, False)
    assert flow.attempt_id != attempt
    assert not flow.completed
    assert 'fresh baseline' in flow.message


def test_capture_from_before_collection_cannot_be_admitted_after_delayed_ack():
    flow, clock = setup_flow()
    flow.begin()
    flow.present(flow.presentation_token, 'CENTER', GEOMETRY)
    previous = flow.current_result
    clock.advance(.25)
    flow.update(previous, clock.now, True)
    assert flow._count() == 0
    assert flow.calibration.diagnostics['targets']['CENTER']['rejection_reasons']['captured_before_collection'] == 1


def test_missing_presentation_times_out_without_samples_or_fit():
    flow, clock = setup_flow()
    flow.begin()
    for _ in range(81):
        feed(flow, clock)
    assert flow.phase == 'target_failed'
    assert not flow.state()['ready']
    assert not any(flow.calibration.counts.values())
