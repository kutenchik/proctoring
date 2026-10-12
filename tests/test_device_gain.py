from dataclasses import replace
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from proctoring.audio.gain import GainEnergyDetector
from proctoring.audio.monitor import AudioMonitor
from proctoring.clock import FakeClock
from proctoring.devices import microphones, restore_device, resolve_microphone, input_format, InputDevice
from proctoring.settings import AudioConfig


def wave(rms):
    return (np.sin(np.arange(800)*2*np.pi*220/16000)*rms*np.sqrt(2)).astype('float32')[:, None]


def run_check(detector, background=.002, speech=None, start=0.):
    speech = speech or [.018, .030, .008, .025, .045, .004]
    assert detector.begin_calibration()
    outputs = []
    for i in range(153):
        level = background if i <= 30 else speech[i % len(speech)]
        outputs.append(detector.observe(wave(level), start+i*.05))
    return outputs


def test_quiet_speech_bounded_fixed_gain_and_consistent_threshold_units():
    d = GainEnergyDetector(AudioConfig(enabled=True))
    observations = run_check(d)
    assert d.check_status['state'] == 'ready'
    assert 1 < d.gain <= 8
    assert d.baseline == pytest.approx(d._check_ambient*d.gain)
    assert d.baseline < d.threshold < d.speech_rms*d.gain
    assert all(not item.above_ambient for item in observations[:151])
    gain = d.gain
    for i in range(20):
        sample = d.observe(wave(.025), 7.7+i*.05)
    assert sample.rms == pytest.approx(.025*gain, rel=.03)
    assert sample.above_ambient
    for i in range(20):
        d.observe(wave(0), 8.7+i*.05)
    assert d.gain == gain  # Silence never drives automatic gain growth.


@pytest.mark.parametrize('background,speech', [(0., [0.]), (.01, [.01]), (.002, [.03]), (.15, [.16])])
def test_silence_and_constant_noise_cannot_calibrate(background, speech):
    d = GainEnergyDetector(AudioConfig(enabled=True))
    run_check(d, background, speech)
    assert d.check_status['state'] != 'ready'
    assert d.gain == 1 and d.custom_threshold is None


def test_failed_same_device_retry_preserves_good_gain_and_threshold():
    d = GainEnergyDetector(AudioConfig(enabled=True))
    run_check(d)
    good = d.gain, d.threshold
    run_check(d, 0., [0.], start=7.7)
    assert d.check_status['state'] == 'no_signal'
    assert (d.gain, d.threshold) == good


def test_clipping_is_not_repaired_or_accepted_and_runtime_limiter_protects_output():
    d = GainEnergyDetector(AudioConfig(enabled=True))
    d.begin_calibration()
    d.observe(np.ones((800, 1)), 0.)
    assert d.check_status['state'] == 'clipping'
    assert d.gain == 1.
    d.gain = 8
    before = d.applied_gain
    processed = d.process_samples(np.ones((800, 1))*.5, .05)
    assert before < d.applied_gain < 8
    assert np.max(np.abs(processed)) <= .95


def test_invalid_samples_and_late_timestamps_cannot_install_gain():
    d = GainEnergyDetector(AudioConfig(enabled=True))
    d.begin_calibration()
    with pytest.raises(ValueError):
        d.observe([np.nan], 0.)
    assert d.custom_threshold is None and d.gain == 1
    d.observe(wave(.01), 1.)
    assert d.observe(wave(.5), .5) is None


class Backend:
    def __init__(self):
        self.rows = [dict(name='Speakers', hostapi=0, max_input_channels=0, default_samplerate=48000),
                     dict(name='USB microphone', hostapi=0, max_input_channels=2, default_samplerate=48000)]
        self.default = SimpleNamespace(device=(1, 0))
        self.check_input_settings = Mock(side_effect=self.check)

    def query_hostapis(self): return [{'name': 'WASAPI'}]
    def query_devices(self, index=None, kind=None): return self.rows if index is None else self.rows[index]
    def check(self, **kwargs):
        if kwargs['samplerate'] != 48000 or kwargs['channels'] != 2:
            raise ValueError('Unsupported format')


def test_input_names_default_and_stable_restore_after_index_change():
    backend = Backend()
    choices = microphones(backend)
    assert len(choices) == 2 and choices[0].key == 'system-default'
    assert 'USB microphone' in choices[1].label and 'WASAPI' in choices[1].label
    backend.rows.insert(0, dict(backend.rows[0]))
    restored = restore_device(choices[1].key, microphones(backend))
    assert restored.index == 2
    assert resolve_microphone(choices[1], backend).index == 2


def test_missing_or_ambiguous_microphone_is_not_silently_substituted():
    backend = Backend()
    device = microphones(backend)[1]
    backend.rows[1]['name'] = 'Different input'
    with pytest.raises(RuntimeError, match='unavailable'):
        resolve_microphone(device, backend)
    backend.rows.append(dict(backend.rows[1]))
    duplicate = microphones(backend)[1]
    assert duplicate.ambiguous
    assert restore_device(duplicate.key, microphones(backend)) is None


def test_selected_backend_device_and_negotiated_format_reach_stream(monkeypatch):
    backend = Backend()
    opened = []
    class Stream:
        samplerate, channels = 48000, 2
        def __enter__(self): return self
        def __exit__(self, *_): opened.append('closed')
        def read(self, size):
            assert size == 2400
            monitor._stop.set()
            return np.zeros((size, 2)), False
    backend.InputStream = lambda **kwargs: (opened.append(kwargs) or Stream())
    monkeypatch.setitem(__import__('sys').modules, 'sounddevice', backend)
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock())
    monitor.selection = microphones(backend)[1]
    monitor.start()
    monitor._thread.join(2)
    assert opened[0] == dict(device=1, samplerate=48000, channels=2, dtype='float32', blocksize=2400)
    assert opened[-1] == 'closed'
    assert monitor.stream_format == {'sample_rate': 48000, 'channels': 2}
    assert monitor.drain() == []  # Buffer arriving after stop is discarded.


def test_switch_waits_for_old_stream_and_invalidates_gain(monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    calls = []
    class Stream:
        def __enter__(self): calls.append('open'); return self
        def __exit__(self, *_): calls.append('close')
        def read(self, size):
            entered.set(); finish.wait(3)
            monitor._stop.set()
            return wave(.1), False
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock(), lambda **_: Stream())
    monitor._detector.gain = 4.
    monitor.start(); assert entered.wait(1)
    assert monitor.select_device(InputDevice('new', 'New input'))
    assert monitor.check_status['state'] == 'initializing'
    assert len(calls) == 1
    finish.set(); monitor._switch_thread.join(3)
    monitor.stop()
    assert calls[:3] == ['open', 'close', 'open']
    assert monitor._detector.gain == 1
    assert monitor.drain() == []


def test_device_change_disallowed_after_exam_start():
    monitor = AudioMonitor(AudioConfig(enabled=False), FakeClock())
    monitor.begin_exam()
    assert not monitor.select_device(InputDevice('x', 'Input'))


def test_refresh_reinitializes_only_the_catalog_backend(monkeypatch):
    import sys
    from proctoring.devices import refresh_microphones
    backend = Backend()
    backend._terminate, backend._initialize = Mock(), Mock()
    monkeypatch.setitem(sys.modules, 'sounddevice', backend)
    assert len(refresh_microphones()) == 2
    backend._terminate.assert_called_once()
    backend._initialize.assert_called_once()


def test_device_refresh_excludes_concurrent_open_and_calibration():
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock(), Mock())
    monitor._device_refresh = True
    monitor.start()
    assert monitor._thread is None
    assert not monitor.begin_calibration()
    assert not monitor.select_device(InputDevice('other', 'Other'))
    assert monitor.check_status['state'] == 'initializing'


@pytest.mark.parametrize('kwargs', [{'max_gain': 0}, {'max_gain': 99},
                                    {'speech_target_rms': float('nan')}, {'calibration_max_seconds': 1}])
def test_gain_config_rejects_unsafe_limits(kwargs):
    with pytest.raises(ValueError): AudioConfig(**kwargs)
