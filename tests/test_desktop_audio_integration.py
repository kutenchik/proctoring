"""Synthetic captured PCM through the real Electron workflow/audio services.

No webcam, microphone, hidden legacy window, or human accuracy claim is used.
"""
import json
from unittest.mock import Mock

import pytest

from proctoring.devices import InputDevice
from proctoring.domain import EventType
from test_audio_exam_delivery import calibrate_audio, samples
from test_desktop_workflow import make_ready, make_workflow


VOICE = EventType.VOICE_DETECTED.value


def configured_audio(bridge, monkeypatch):
    audio = bridge.audio
    monkeypatch.setattr(audio, 'start', Mock())  # Suppress hardware only.
    audio.selection = InputDevice('mic-a', 'Synthetic Fifine', 18, 'mic-a')
    audio.device_key = 'mic-a'
    bridge.audio_key = 'mic-a'
    audio.resolved_device = 'Synthetic WASAPI input'
    audio.stream_format = {'sample_rate': 48000., 'channels': 1, 'dtype': 'float32'}
    audio._set_status('available', 'Synthetic captured PCM')
    return audio


def feed(bridge, rms, *, poll=True):
    bridge.clock.advance(.05)
    sample = bridge.audio._detector.observe(samples(rms), bridge.clock.monotonic(), 48000)
    if sample is not None:
        bridge.audio._observations.append(sample)
    if poll:
        bridge.tick()
    return sample


def rows(bridge):
    return [json.loads(line) for line in (bridge.controller.store.path/'events.jsonl').read_text(encoding='utf-8').splitlines()]


def test_calibrated_gapped_audio_reaches_bridge_journal_and_summary(tmp_path, monkeypatch):
    bridge = make_workflow(tmp_path, audio_enabled=True)
    try:
        make_ready(bridge)
        audio = configured_audio(bridge, monkeypatch)
        detector = audio._detector
        gain, threshold = calibrate_audio(audio, bridge.clock)
        bridge.tick()
        assert not bridge.controller.review_events
        assert not bridge.controller.session.started
        assert bridge.controller.session.elapsed_seconds == 0
        assert bridge.controller.store is None
        assert gain == 8. and 0 < threshold < .05

        bridge.dispatch('exam.start', {})
        assert bridge.controller.audio is audio and audio._detector is detector
        assert (detector.gain, detector.threshold) == (gain, threshold)
        assert detector.check_status['threshold_source'] == 'adaptive'
        assert audio.drain() == []

        positives = 0
        for index in range(80):
            positive = index % 10 < 7
            sample = feed(bridge, .0053 if positive else 0.)
            assert sample.above_ambient is positive
            positives += positive
            if positives < 40:
                assert not bridge.controller.review_events
            else:
                break
        event = bridge.controller.review_events[0]
        event_id = event['event_id']
        assert event['event_type'] == VOICE
        assert event['activity_seconds'] == pytest.approx(2.)
        assert event['duration_seconds'] > 2.
        assert bridge.controller.session.elapsed_seconds == pytest.approx((index+1)*.05)
        state = bridge.state()['workflow']
        assert state['session']['running'] and not state['session']['pause_reasons']
        assert state['events']['records'][0]['event_id'] == event_id
        page = bridge.event_page(0, 100)
        activation = [r['record'] for r in page['records'] if r['record'].get('action') == 'activated']
        assert len(activation) == 1 and activation[0]['event_id'] == event_id

        for _ in range(25): feed(bridge, .0053)
        assert len(bridge.state()['workflow']['events']['records']) == 1
        for _ in range(16): feed(bridge, 0.)
        assert bridge.controller.review_events[0]['state'] == 'closed'
        for _ in range(40): feed(bridge, .0053)
        assert len(bridge.controller.review_events) == 2
        assert bridge.controller.review_events[1]['event_id'] != event_id
        bridge.dispatch('exam.submit', {})
        summary = bridge.state()['workflow']['summary']
        persisted = json.loads((bridge.controller.store.path/'summary.json').read_text(encoding='utf-8'))
        assert summary['event_counts'] == persisted['event_counts'] == {VOICE: 2}
        assert summary['events'][0]['event_id'] == event_id
        assert persisted['audio_check']['threshold'] == pytest.approx(threshold)
        assert persisted['audio_check']['gain'] == gain
        assert len([r for r in rows(bridge) if r.get('action') == 'activated']) == 2
    finally:
        bridge.close()


@pytest.mark.parametrize('enabled', [False, True])
def test_disabled_audio_or_optional_loss_does_not_pause_exam(tmp_path, monkeypatch, enabled):
    bridge = make_workflow(tmp_path, audio_enabled=enabled)
    try:
        make_ready(bridge)
        audio = configured_audio(bridge, monkeypatch)
        calibrate_audio(audio, bridge.clock)
        bridge.dispatch('exam.start', {})
        if enabled:
            for _ in range(20): feed(bridge, .0053)
            audio._set_status('unavailable', 'Synthetic microphone loss')
            for _ in range(12):
                bridge.clock.advance(.1)
                bridge.tick()
        else:
            assert bridge.controller.audio is None
            for _ in range(70): feed(bridge, .0053)
        state = bridge.state()['workflow']
        assert state['session']['running'] and not state['session']['pause_reasons']
        assert not state['events']['records']
        assert not [row for row in rows(bridge) if row.get('event_type') == VOICE]
    finally:
        bridge.close()
