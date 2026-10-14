"""Signal-path regressions, not a claim of validated human speech recognition."""
from unittest.mock import Mock

import numpy as np
import pytest

from proctoring.audio.gain import GainEnergyDetector, normalized_input
from proctoring.audio.monitor import AudioMonitor
from proctoring.clock import FakeClock
from proctoring.devices import InputDevice
from proctoring.settings import AudioConfig


def tone(rms, rate=16000, channels=1):
    values = np.sin(np.arange(int(rate*.05))*2*np.pi*220/rate)*rms*np.sqrt(2)
    return np.repeat(values[:, None], channels, axis=1).astype('float32')


def calibrate(detector, background=.0005, speech=None, *, start=0., rate=16000, click=False):
    if speech is None:
        speech = [.003, .005, .007, .004, .006, 0., 0.]
    assert detector.begin_calibration()
    for index in range(153):
        rms = background if index <= 30 else speech[index % len(speech)]
        if click and index == 45:
            rms = .6
        detector.observe(tone(rms, rate), start+index*.05, rate)
    return detector.check_status


@pytest.mark.parametrize('dtype', [np.int16, np.int32, np.int64])
def test_signed_pcm_converts_before_squaring_without_overflow(dtype):
    bits = np.dtype(dtype).itemsize*8
    source = np.array([-2**(bits-1), 0, 2**(bits-2)], dtype=dtype)
    actual, reported, channel = normalized_input(source)
    np.testing.assert_allclose(actual, [-1., 0., .5])
    assert reported == np.dtype(dtype).name and channel == 0


def test_unsigned_pcm_silence_midpoint_and_float_not_scaled_again():
    np.testing.assert_allclose(normalized_input(np.array([0, 128, 192], np.uint8))[0], [-1., 0., .5])
    source = np.array([-.2, 0., .5], np.float32)
    np.testing.assert_allclose(normalized_input(source)[0], source)


@pytest.mark.parametrize('second', ['silent', 'opposite', 'same'])
def test_stereo_speech_neither_diluted_nor_cancelled(second):
    mono = tone(.02)[:, 0]
    other = {'silent': np.zeros_like(mono), 'opposite': -mono, 'same': mono}[second]
    detector = GainEnergyDetector(AudioConfig(enabled=True))
    observation = detector.observe(np.column_stack([mono, other]), 0.)
    assert detector.raw_rms == pytest.approx(.02, rel=1e-5)
    assert observation.rms == pytest.approx(.02, rel=1e-5)
    assert detector.check_status['channel_strategy'] == 'strongest_rms_channel'


def test_second_channel_microphone_selected_without_averaging():
    mono = tone(.02)[:, 0]
    actual, _, selected = normalized_input(np.column_stack([np.zeros_like(mono), mono]))
    assert selected == 1
    np.testing.assert_allclose(actual, mono)


@pytest.mark.parametrize('source', [np.array([True]), np.zeros((2, 2, 2)), np.array([np.nan]),
                                   np.array([1.2]), np.empty((2, 0))])
def test_invalid_shapes_types_and_values_fail_explicitly(source):
    with pytest.raises(ValueError):
        normalized_input(source)


@pytest.mark.parametrize('rate', [16000, 48000])
def test_low_amplitude_high_contrast_uses_consistent_threshold_not_preferred_loudness(rate):
    detector = GainEnergyDetector(AudioConfig(enabled=True))
    status = calibrate(detector, rate=rate)
    assert status['state'] == 'ready'
    assert status['gain'] == 8.
    assert status['gain_limited']
    assert status['ambient_rms_raw'] == pytest.approx(.0005, rel=1e-5)
    assert status['speech_rms_raw'] == pytest.approx(.005, rel=1e-5)
    assert status['processed_noise'] == pytest.approx(.004, rel=1e-5)
    assert status['processed_speech'] == pytest.approx(.04, rel=1e-5)
    assert status['threshold'] == pytest.approx(.0184, rel=1e-5)
    assert status['processed_noise'] < status['threshold'] < status['processed_speech']
    assert status['buffer_duration_seconds'] == pytest.approx(.05)
    # Same gain and threshold reach the runtime detector, not just the UI meter.
    for index in range(30):
        observation = detector.observe(tone(.005, rate), 7.7+index*.05, rate)
    assert observation.above_ambient
    assert observation.rms == pytest.approx(.04, rel=.01)
    for index in range(30):
        detector.observe(tone(0., rate), 9.2+index*.05, rate)
    assert detector.gain == 8. and detector.check_status['state'] == 'ready'


def test_speech_below_old_raw_floor_can_be_usable_but_silence_cannot():
    detector = GainEnergyDetector(AudioConfig(enabled=True))
    assert calibrate(detector, .0001, [.001, .002, .0015, .0008, 0.])['state'] == 'ready'
    good = detector.gain, detector.threshold
    failed = calibrate(detector, 0., [0.], start=8.)
    assert failed['rejection_code'] == 'insufficient_activity'
    assert 'voice is too quiet' not in failed['reason']
    assert (detector.gain, detector.threshold) == good


@pytest.mark.parametrize('background,speech,reason', [
    (.002, [.002], 'insufficient_contrast'),
    (.002, [.002, .003, .004, .005], 'insufficient_contrast'),
    (.0005, [.005], 'steady_activity'),
])
def test_contrast_and_temporal_quality_guards_remain(background, speech, reason):
    detector = GainEnergyDetector(AudioConfig(enabled=True))
    result = calibrate(detector, background, speech)
    assert result['state'] != 'ready'
    assert result['rejection_code'] == reason
    assert detector.custom_threshold is None


def test_single_unclipped_peak_is_explained_and_does_not_dominate_speech_gain():
    detector = GainEnergyDetector(AudioConfig(enabled=True))
    result = calibrate(detector, click=True)
    assert result['state'] == 'ready'
    assert result['transient_peak_excluded']
    assert result['observed_peak_raw'] > .8
    assert result['peak_limit_raw'] < .02
    assert result['gain'] == 8.


def test_clipped_integer_input_still_rejected_and_good_calibration_retained():
    detector = GainEnergyDetector(AudioConfig(enabled=True))
    calibrate(detector)
    good = detector.gain, detector.threshold
    detector.begin_calibration()
    detector.observe(np.full((800, 1), 32767, dtype=np.int16), 7.7)
    assert detector.check_status['state'] == 'clipping'
    assert (detector.gain, detector.threshold) == good


def test_same_selected_device_does_not_restart_or_discard_calibration():
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock())
    monitor.selection = InputDevice('same', 'Mic', 5, 'same-signature')
    calibrate(monitor._detector)
    original = monitor._detector
    monitor.start = Mock()
    assert monitor.select_device(InputDevice('same', 'Mic', 8, 'same-signature'))
    assert monitor._detector is original and not monitor._switching
    assert monitor._switch_thread is None
    monitor.start.assert_not_called()


def test_actual_rate_and_dtype_are_used_in_stream_processing():
    from PySide6.QtCore import Qt
    clock = FakeClock()
    class Stream:
        samplerate, channels, dtype = 48000, 2, 'int16'
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, size):
            assert size == 2400
            clock.advance(.05)
            return np.column_stack([np.zeros(size, np.int16), np.full(size, 16384, np.int16)]), False
    monitor = AudioMonitor(AudioConfig(enabled=True), clock, lambda **_: Stream())
    def received(_): monitor._stop.set()
    monitor.audio_level_changed.connect(received, Qt.ConnectionType.DirectConnection)
    monitor.start()
    monitor._thread.join(1.)
    status = monitor.check_status
    assert status['input_rms'] == .5
    assert status['sample_dtype'] == 'int16' and status['selected_channel'] == 1
    assert status['buffer_duration_seconds'] == .05
    assert status['stream_format'] == {'sample_rate': 48000., 'channels': 2, 'dtype': 'int16'}
    monitor.stop()


def test_explicit_changed_system_default_reselection_resets_only_audio():
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock())
    monitor.selection = InputDevice('system-default', 'Default A', default_target_key='mic-a')
    monitor.device_key = 'mic-a'
    calibrate(monitor._detector)
    previous = monitor._detector
    monitor.start = Mock()
    assert monitor.select_device(InputDevice('system-default', 'Default B', default_target_key='mic-b'))
    monitor._switch_thread.join(1.)
    assert monitor._detector is not previous
    assert monitor._detector.gain == 1.
    assert monitor._detector.custom_threshold is None
    monitor.start.assert_called_once()


def test_same_resolved_system_default_retains_calibration_without_restart():
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock())
    selected = InputDevice('system-default', 'Default A', default_target_key='mic-a')
    monitor.selection = selected
    monitor.device_key = 'mic-a'
    calibrate(monitor._detector)
    previous = monitor._detector
    monitor.start = Mock()
    assert monitor.select_device(selected)
    assert monitor._detector is previous
    assert monitor._switch_thread is None
    monitor.start.assert_not_called()
