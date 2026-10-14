"""Fixed session gain from a quiet/speak check; no recordings, AGC or voice identity."""
import math
import numpy as np
from .monitor import EnergyDetector, AudioObservation


def normalized_input(samples):
    """Normalize PCM once, then use the strongest input channel without mixing.

    Mixing stereo can cancel opposite-polarity channels; RMS over all channels
    dilutes a microphone carried on only one channel. Choosing the strongest
    channel on every buffer applies the same conservative rule to noise, speech,
    the displayed meter and the detector. It is not a noise-removal operation.
    """
    source = np.asarray(samples)
    if not source.size or source.ndim not in (1, 2) or source.dtype.kind not in 'fiu':
        raise ValueError('Invalid audio samples')
    values = source.astype(np.float64)
    if source.dtype.kind == 'i':
        values /= float(2 ** (source.dtype.itemsize * 8 - 1))
    elif source.dtype.kind == 'u':
        midpoint = float(2 ** (source.dtype.itemsize * 8 - 1))
        values = (values-midpoint)/midpoint
    if not np.isfinite(values).all() or np.max(np.abs(values)) > 1.001:
        raise ValueError('Invalid normalized audio samples')
    channel = 0
    if values.ndim == 2:
        channel = int(np.argmax(np.mean(values*values, axis=0)))
        values = values[:, channel]
    return values, str(source.dtype), channel


class GainEnergyDetector(EnergyDetector):
    def __init__(self, config):
        super().__init__(config)
        self.gain = self.applied_gain = 1.
        self.raw_rms = self.raw_peak = 0.
        self.speech_rms = self.input_peak = None
        self._check_records = []
        self._gain_timestamp = None
        self._raw = (0., 0., 0.)
        self.sample_dtype = None
        self.selected_channel = 0
        self.buffer_duration = 0.
        self.proposed_gain = self.processed_noise = self.processed_speech = None
        self.transient_peak = self.peak_limit = None
        self.rejection_code = None
        self.gain_limited = False
        self._committed_speech = None

    @property
    def check_status(self):
        return {**super().check_status, 'threshold': self.threshold,
                'gain': self.gain, 'applied_gain': self.applied_gain,
                'input_rms': self.raw_rms, 'input_peak': self.raw_peak,
                'input_clipped_fraction': self._raw[2], 'ambient_rms_raw': self._check_ambient,
                'ambient': None if self._check_ambient is None else self._check_ambient*self.gain,
                'speech_rms_raw': self.speech_rms, 'calibration_peak_raw': self.input_peak,
                'proposed_gain': self.proposed_gain, 'processed_noise': self.processed_noise,
                'processed_speech': self.processed_speech, 'gain_limited': self.gain_limited,
                'committed_processed_speech': self._committed_speech,
                'observed_peak_raw': self.transient_peak, 'peak_limit_raw': self.peak_limit,
                'peak_policy': 'p95_active_buffer_peaks; clipped_input_rejected; output_limited',
                'transient_peak_excluded': (self.transient_peak is not None and self.peak_limit is not None
                                            and self.transient_peak > 1.5*self.peak_limit),
                'rejection_code': self.rejection_code, 'sample_dtype': self.sample_dtype,
                'selected_channel': self.selected_channel, 'channel_strategy': 'strongest_rms_channel',
                'buffer_duration_seconds': self.buffer_duration,
                'units': 'processed_normalized_rms', 'voice_gain_check': True}

    def begin_calibration(self):
        if not super().begin_calibration():
            return False
        self._check_records = []
        self.speech_rms = self.input_peak = None
        self.proposed_gain = self.processed_noise = self.processed_speech = None
        self.transient_peak = self.peak_limit = None
        self.rejection_code = None
        self.gain_limited = False
        self._check_reason = 'Please stay quiet for a moment.'
        return True

    def reset(self, reason="Audio gap; retry microphone check"):
        super().reset(reason)
        # Stop/reopen of this same resolved device retains the committed
        # reference. A changed device installs a new detector in AudioMonitor.
        # Do not spend another three seconds treating exam speech as ambient.
        if self.custom_threshold is not None and self._committed_ambient is not None:
            self.baseline = self._committed_ambient

    def _failure(self, state, reason, code=None):
        self._check_state, self._check_reason = state, reason
        self.rejection_code = code or state
        self._check_records = []
        self._progress = 0.

    def _commit_threshold(self, threshold, source, ambient=None, recommended=None):
        # The configured minimum remains the manual/fallback limit. A measured
        # calibration uses its measured contrast instead of imposing a target
        # loudness that quiet, otherwise usable microphones cannot attain.
        if source == 'adaptive':
            if (not math.isfinite(threshold) or ambient is None or
                    not 0 <= ambient < threshold <= self.limits[1] or
                    self.processed_speech is None or threshold >= .9*self.processed_speech):
                raise ValueError('Adaptive threshold must separate measured noise and speech')
            self.custom_threshold = float(threshold)
            self._threshold_source = source
            self._committed_ambient, self._committed_recommendation = ambient, recommended
            self._committed_speech = self.processed_speech
            self._recent.clear()
            return
        super()._commit_threshold(threshold, source, ambient, recommended)

    def _advance_check(self, _processed_rms, timestamp):
        if self._check_state not in {'ambient', 'speak'}:
            return
        rms, peak, clipped = self._raw
        if self._check_start is None:
            self._check_start = timestamp
        elapsed = timestamp-self._check_start
        self._progress = min(1., elapsed/(self.config.calibration_background_seconds+self.config.calibration_speech_seconds))
        if elapsed > self.config.calibration_max_seconds:
            self._failure('no_signal', 'Microphone check timed out. Check the selected input and retry.')
            return
        if clipped > .001:
            self._failure('clipping', 'The input is clipping. Reduce microphone input volume and retry.')
            return
        if self._check_state == 'ambient':
            self._quiet_samples.append(rms)
            if elapsed < self.config.calibration_background_seconds-1e-9:
                return
            self._check_ambient = float(np.percentile(self._quiet_samples, 75))
            if self._check_ambient > .12:
                self._failure('noisy', 'Background noise is too high. Reduce noise and retry.')
                return
            self._check_state, self._check_reason = 'speak', 'Now speak normally, as you would during the exam.'
            self._speak_start = timestamp
            return
        self._check_records.append((rms, peak, self.buffer_duration))
        if timestamp-self._speak_start < self.config.calibration_speech_seconds-1e-9:
            return
        values = np.asarray(self._check_records)
        noise = self._check_ambient
        # Keep nonzero absolute and contrast guards, but don't impose the old
        # .003 raw loudness target. 1e-4 is above three 16-bit PCM steps.
        usable = values[:, 0] > max(.0001, noise*3, noise+.0001)
        enough = float(np.sum(values[usable, 2])) >= max(.5, self.config.calibration_speech_seconds*.20)-1e-9
        if not enough:
            if np.max(values[:, 0]) < .0001:
                reason, code = 'No speech-level activity detected. Speak naturally and retry.', 'insufficient_activity'
            elif np.percentile(values[:, 0], 90) <= max(noise*3, noise+.0001):
                reason, code = 'Input activity is not sufficiently above background. Reduce noise or move closer and retry.', 'insufficient_contrast'
            else:
                reason, code = 'Not enough speech-level activity detected. Speak a few more words and retry.', 'insufficient_activity'
            self._failure('no_signal', reason, code)
            return
        speech = float(np.median(values[usable, 0]))
        self.speech_rms = speech
        # Steady noise/tone alone cannot verify normal speech. This is a light
        # activity proxy, not a claim of acoustic speech recognition.
        if np.percentile(values[:, 0], 90) < max(1e-6, np.percentile(values[:, 0], 10))*1.25:
            self._failure('no_signal', 'No varying speech-level input. Speak naturally and retry.', 'steady_activity')
            return
        self.transient_peak = float(np.max(values[:, 1]))
        # A startup/click peak in a pause must not set gain for all speech. Use
        # P95 of active-buffer peaks; retain the absolute maximum diagnostically.
        # Any actually clipped input still fails above; output remains limited.
        peak = float(np.percentile(values[usable, 1], 95))
        self.input_peak = self.peak_limit = peak
        gain = min(self.config.max_gain, self.config.speech_target_rms/speech, .90/max(peak, .001))
        self.proposed_gain = gain
        if gain < .1:
            self._failure('clipping', 'Input level is too high. Reduce microphone input volume and retry.')
            return
        processed_noise, processed_speech = noise*gain, speech*gain
        self.processed_noise, self.processed_speech = processed_noise, processed_speech
        threshold = processed_noise+.4*(processed_speech-processed_noise)
        if threshold >= processed_speech*.9 or threshold > self.limits[1]:
            self._failure('no_signal', 'Noise and activity levels cannot be separated safely. Reduce noise or move closer and retry.', 'processed_contrast')
            return
        self.gain = gain
        self._recommended = threshold
        self._commit_threshold(threshold, 'adaptive', processed_noise, threshold)
        self.baseline = processed_noise
        self._check_state, self._check_reason = 'ready', 'Microphone calibrated.'
        self.gain_limited = processed_speech < self.config.speech_target_rms*.95
        if self.gain_limited:
            self._check_reason = 'Microphone calibrated. The level is below the preferred target but usable.'
        self._progress = 1.
        self._check_records = []

    def process_samples(self, samples, timestamp, sample_rate=None):
        values, self.sample_dtype, self.selected_channel = normalized_input(samples)
        rate = self.config.sample_rate if sample_rate is None else sample_rate
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError('Invalid audio sample rate')
        self.buffer_duration = len(values)/rate
        self.raw_rms = float(np.sqrt(np.mean(values*values)))
        self.raw_peak = float(np.max(np.abs(values)))
        self._raw = (self.raw_rms, self.raw_peak, float(np.mean(np.abs(values) >= .995)))
        dt = self.buffer_duration
        end = self.applied_gain + (self.gain-self.applied_gain)*(1-math.exp(-dt/self.config.gain_smoothing_seconds))
        ramp = np.linspace(self.applied_gain, end, len(values))
        processed = np.clip(values*ramp, -.95, .95)
        self.applied_gain, self._gain_timestamp = end, timestamp
        return processed

    def observe(self, samples, timestamp, sample_rate=None):
        if not math.isfinite(timestamp):
            raise ValueError('Invalid audio timestamp')
        if self._last is not None and timestamp <= self._last:
            return None
        checking = self._check_state in {'ambient', 'speak'}
        processed = self.process_samples(samples, timestamp, sample_rate)
        observation = super().observe(processed, timestamp)
        if observation is None:
            return None
        # Only the current measured chunk earns activity duration. Candidate
        # hysteresis tolerates inter-word dips without crediting a silent tail
        # from the legacy three-buffer moving average.
        positive = (not checking and self._check_state not in {'ambient', 'speak'}
                    and observation.baseline is not None and observation.rms > self.threshold)
        return AudioObservation(timestamp, positive, observation.rms, observation.baseline,
                                observation.healthy, self.buffer_duration)
