"""Bounded audio observations and session-only RMS calibration, never speech recognition."""
from collections import deque
from dataclasses import dataclass
import logging
import math
import threading

import numpy as np
from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class AudioObservation:
    timestamp: float
    above_ambient: bool
    rms: float
    baseline: float | None
    healthy: bool = True


class EnergyDetector:
    """Process every buffer, retaining only numerical RMS measurements.

    An explicit quiet/speak check recommends an absolute RMS trigger. Until a
    check succeeds, the original three-second/3x ambient static fallback applies.
    The shared EventEngine still owns the sustained activity duration.
    """
    QUIET_SECONDS = 2.5
    SPEAK_SECONDS = 8.0
    SPIKE_SECONDS = .15

    def __init__(self, config):
        self.config = config
        self._start = self._last = None
        self._ambient = []
        self._recent = deque(maxlen=3)
        self.baseline = None
        self.custom_threshold = None
        self._threshold_source = "fallback"
        self._committed_ambient = self._committed_recommendation = None
        self._check_state = "idle" if config.enabled else "disabled"
        self._check_reason = ""
        self._check_start = None
        self._quiet_samples = []
        self._speak_start = self._spike_start = None
        self._check_ambient = self._recommended = None
        self._candidate_threshold = None
        self._sensitivity = 1.0
        self._progress = 0.0
        self._rms = 0.0
        self._exam_started = False

    @property
    def limits(self):
        return (getattr(self.config, "min_energy_threshold", .05),
                getattr(self.config, "max_energy_threshold", .40))

    @property
    def threshold(self):
        if self.custom_threshold is not None:
            return self.custom_threshold
        if self.baseline is None:
            return self.config.energy_threshold
        return max(self.baseline + self.config.energy_threshold, self.baseline * 3.)

    @property
    def check_status(self):
        displayed = self._candidate_threshold if self._check_state == "speak" else self.threshold
        return {"state": self._check_state, "reason": self._check_reason,
                "rms": self._rms, "timestamp": self._last,
                "ambient": self._check_ambient, "recommended_threshold": self._recommended,
                "threshold": displayed, "progress": self._progress,
                "sensitivity": self._sensitivity,
                "threshold_source": self._threshold_source,
                "committed_threshold": self.threshold,
                "committed_ambient": self._committed_ambient,
                "committed_recommended_threshold": self._committed_recommendation}

    def begin_calibration(self):
        if (not self.config.enabled or self._exam_started
                or not getattr(self.config, "adaptive_calibration", True)):
            return False
        self._check_state, self._check_reason = "ambient", "Remain quiet for 2.5 seconds"
        self._check_start = self._speak_start = self._spike_start = None
        self._quiet_samples = []
        self._check_ambient = self._recommended = self._candidate_threshold = None
        self._progress = 0.
        return True

    def set_custom_threshold(self, threshold):
        """An explicit manual override is usable, but never verifies a test."""
        self._commit_threshold(threshold, "manual")
        if self._check_state in {"ambient", "speak", "ready"}:
            self._check_state, self._check_reason = "idle", "Manual threshold set; run microphone check to verify"
            self._progress = 0.

    def _commit_threshold(self, threshold, source, ambient=None, recommended=None):
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold) or not self.limits[0] <= threshold <= self.limits[1]):
            raise ValueError("Audio threshold must be finite and within configured limits")
        self.custom_threshold = float(threshold)
        self._threshold_source = source
        self._committed_ambient, self._committed_recommendation = ambient, recommended
        self._recent.clear()

    def set_sensitivity(self, multiplier):
        if (isinstance(multiplier, bool) or not isinstance(multiplier, (int, float))
                or not math.isfinite(multiplier) or not .5 <= multiplier <= 2.):
            raise ValueError("Audio sensitivity multiplier must be between 0.5 and 2.0")
        self._sensitivity = float(multiplier)
        # A failed retry's measurements must not replace the retained reference.
        pending = self._check_state == "speak"
        reference = self._recommended if pending else self._committed_recommendation
        reference = self.config.energy_threshold if reference is None else reference
        ambient = self._check_ambient if pending else self._committed_ambient
        value = min(self.limits[1], max(self.limits[0], reference * multiplier))
        if ambient is not None and value <= ambient:
            self._check_state, self._check_reason = "noisy", "Ambient noise exceeds the usable threshold"
            return
        if pending:
            self._candidate_threshold = value
            self._spike_start = None  # Verify a fresh spike at the changed threshold.
        else:
            self._commit_threshold(value, "manual", ambient, self._committed_recommendation)
            if self._check_state == "ready":
                self._check_state = "idle"
                self._progress = 0.
            if self._check_state == "idle":
                self._check_reason = "Manual sensitivity set; run microphone check to verify"

    def begin_exam(self):
        self._exam_started = True
        self._recent.clear()
        if self._check_state in {"ambient", "speak"}:
            self._check_state, self._check_reason = "idle", "Check incomplete; using retained threshold"

    def reset(self, reason="Audio gap; retry microphone check"):
        self._start = self._last = None
        self._ambient = []
        self._recent.clear()
        self.baseline = None
        self._rms = 0.
        if self._check_state in {"idle", "ambient", "speak", "ready"}:
            self._check_state, self._check_reason = "no_signal", reason
            self._quiet_samples = []
            self._spike_start = None
            self._progress = 0.

    def unavailable(self, reason):
        self.reset(reason)
        self._check_state, self._check_reason = "unavailable", reason

    def retry_input(self):
        if self._check_state == "unavailable":
            # Reopening a device restores the preview, not a verified mic check.
            # A requested quiet-window retry is already in ambient and stays so.
            self._check_state, self._check_reason = "idle", "Microphone retrying; run microphone check to verify"
            self._progress = 0.

    def _advance_check(self, rms, timestamp):
        if self._check_state == "ambient":
            if self._check_start is None:
                self._check_start = timestamp
            elapsed = timestamp - self._check_start
            self._progress = min(1., elapsed / self.QUIET_SECONDS)
            if elapsed < self.QUIET_SECONDS - 1e-9:
                self._quiet_samples.append(rms)
                return
            self._check_ambient = float(np.median(self._quiet_samples))
            self._recommended = max(self._check_ambient * 2.5, self._check_ambient + .08)
            if self._recommended > self.limits[1]:
                self._check_state, self._check_reason = "noisy", "Ambient noise exceeds the usable threshold"
                return
            self._candidate_threshold = min(self.limits[1], max(
                self.limits[0], self._recommended * self._sensitivity))
            self._speak_start, self._spike_start = timestamp, None
            self._check_state, self._check_reason = "speak", "Speak a few words to test the level"
            self._progress = 0.
        elif self._check_state == "speak":
            elapsed = timestamp - self._speak_start
            self._progress = min(1., elapsed / self.SPEAK_SECONDS)
            if elapsed >= self.SPEAK_SECONDS:
                self._check_state, self._check_reason = "no_signal", "No sustained level increase detected; retry"
                return
            if rms > self._candidate_threshold:
                if self._spike_start is None:
                    self._spike_start = timestamp
                elif timestamp - self._spike_start >= self.SPIKE_SECONDS - 1e-9:
                    self._commit_threshold(self._candidate_threshold, "adaptive",
                                           self._check_ambient, self._recommended)
                    self.baseline = self._check_ambient
                    self._check_state, self._check_reason = "ready", "Level increase detected; energy only, not verified speech"
                    self._progress = 1.
            else:
                self._spike_start = None

    def observe(self, samples, timestamp):
        if not math.isfinite(timestamp):
            raise ValueError("Invalid audio timestamp")
        if self._last is not None and timestamp <= self._last:
            return None
        values = np.asarray(samples, dtype=np.float64)
        if not values.size or not np.isfinite(values).all() or np.max(np.abs(values)) > 1.001:
            raise ValueError("Invalid normalized audio samples")
        if self._last is not None and timestamp - self._last > .5:
            self.reset()
        self._last = timestamp
        if self._start is None:
            self._start = timestamp
        rms = min(1., float(np.sqrt(np.mean(values * values))))
        self._rms = rms
        self._recent.append(rms)
        self._advance_check(rms, timestamp)
        if self.baseline is None:
            if timestamp - self._start < 3.0:
                self._ambient.append(rms)
                return AudioObservation(timestamp, False, rms, None)
            self.baseline = float(np.median(self._ambient)) if self._ambient else rms
        moving_rms = float(np.mean(self._recent)) if self._recent else rms
        return AudioObservation(timestamp, moving_rms > self.threshold, rms, self.baseline)


class AudioMonitor(QObject):
    """One optional daemon reads audio; Qt receives at most 20 level updates/s."""
    audio_level_changed = Signal(float)

    def __init__(self, config, clock, stream_factory=None):
        super().__init__()
        self.config, self.clock = config, clock
        self._stream_factory = stream_factory
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._observations = deque(maxlen=40)
        self._status = {"state": "disabled" if not config.enabled else "not_started", "reason": ""}
        self._thread = None
        self._detector = EnergyDetector(config)
        self._last_level_signal = None

    @property
    def status(self):
        with self._lock:
            return dict(self._status)

    @property
    def check_status(self):
        with self._lock:
            value = self._detector.check_status
            if (value["timestamp"] is not None and self.clock.monotonic() - value["timestamp"] > .5
                    and self._status["state"] not in {"disabled", "stopped", "unavailable"}):
                value.update(state="no_signal", rms=0., reason="Audio input is stale; retry microphone check")
            return value

    @property
    def latest_level(self):
        return self.check_status["rms"]

    def _set_status(self, state, reason=""):
        with self._lock:
            self._status = {"state": state, "reason": reason}

    def start(self):
        with self._lock:
            if not self.config.enabled or (self._thread is not None and self._thread.is_alive()):
                return
            self._stop.clear()
            self._last_level_signal = None
            self._detector.retry_input()
            self._status = {"state": "initializing", "reason": ""}
            self._thread = threading.Thread(target=self._run, name="audio-monitor", daemon=True)
            self._thread.start()

    def begin_calibration(self):
        with self._lock:
            if not self._detector.begin_calibration():
                return False
        self.start()
        return True

    def set_custom_threshold(self, new_threshold):
        with self._lock:
            self._detector.set_custom_threshold(new_threshold)

    def set_sensitivity(self, multiplier):
        with self._lock:
            self._detector.set_sensitivity(multiplier)

    def begin_exam(self):
        with self._lock:
            self._observations.clear()
            self._detector.begin_exam()
        self.start()

    def drain(self):
        with self._lock:
            values = list(self._observations)
            self._observations.clear()
            return values

    def _run(self):
        try:
            factory = self._stream_factory
            if factory is None:
                import sounddevice
                factory = sounddevice.InputStream
            size = max(1, int(self.config.sample_rate * .05))
            with factory(samplerate=self.config.sample_rate, channels=1, dtype="float32",
                         blocksize=size) as stream:
                with self._lock:
                    if self._stop.is_set():
                        return
                    self._set_status("calibrating", "Keep quiet for the first three seconds")
                while not self._stop.is_set():
                    samples, overflow = stream.read(size)
                    now = self.clock.monotonic()
                    emit_level = None
                    with self._lock:
                        # A device read may finish after bounded stop() returned.
                        # Never publish its late frame or resurrect availability.
                        if self._stop.is_set():
                            return
                        if overflow:
                            self._detector.reset("Audio overflow; retry microphone check")
                            self._observations.append(AudioObservation(now, False, 0., None, False))
                            self._status = {"state": "calibrating", "reason": "Audio overflow; resetting ambient baseline"}
                            emit_level = 0.
                        else:
                            observation = self._detector.observe(samples, now)
                            if observation is not None:
                                self._observations.append(observation)
                                if observation.baseline is not None:
                                    self._status = {"state": "available", "reason": "Energy only; speech is not verified"}
                                if (self._last_level_signal is None
                                        or now - self._last_level_signal >= .05 - 1e-9):
                                    emit_level = observation.rms
                        if emit_level is not None:
                            self._last_level_signal = now
                            self.audio_level_changed.emit(emit_level)
        except Exception as error:
            # Missing devices/permissions never alter camera health or exam time.
            with self._lock:
                if self._stop.is_set():
                    return
                self._status = {"state": "unavailable", "reason": type(error).__name__}
                self._detector.unavailable("Microphone unavailable (Audio monitoring disabled)")
                self.audio_level_changed.emit(0.)
            logging.getLogger(__name__).info("Optional audio input unavailable (%s)", type(error).__name__)

    def stop(self, timeout=.5):
        with self._lock:
            self._stop.set()
            self._status = {"state": "stopped", "reason": ""}
            self._detector.reset("Audio monitoring stopped")
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(max(0., min(timeout, 2.)))
