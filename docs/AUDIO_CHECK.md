# Microphone check before the exam

When audio is enabled, the camera setup page shows a live RMS meter, a vertical
trigger marker, and a **Calibrate Mic** button. The same audio worker is reused
for the exam. Audio input begins on the setup page after registration; audio is
never recorded, saved or uploaded.

The `[audio]` settings are:

```toml
enabled = true
adaptive_calibration = true
min_energy_threshold = 0.05
max_energy_threshold = 0.40
```

Keep existing `sample_rate`, `voice_duration_threshold`, and `energy_threshold`
settings in that section. Limits are absolute normalized RMS values in `(0, 1]`,
and the minimum must be below the maximum. `energy_threshold` remains the legacy
fallback increment, not the adaptive absolute trigger.

1. Select **Calibrate Mic** and stay quiet for **2.5 seconds**. The worker measures
   the median RMS background and recommends
   `max(ambient * 2.5, ambient + 0.08)`.
2. When prompted, say a few words at an ordinary volume. The check needs a level
   above the proposed threshold for at least 0.15 seconds within an eight-second
   test window. This verifies an energy rise, not intelligible speech.
3. **Microphone ready** confirms that check. The selected threshold stays in
   session memory and its numerical settings are included in session metadata.
4. The sensitivity slider lowers the threshold at **High** and raises it at
   **Low**, within configured bounds. It does not alter operating-system gain.
   Manual changes after a successful test remove the ready indication; repeat
   the check to verify the new setting.

A background floor requiring a threshold above the configured maximum is shown
as too noisy; it is not silently accepted at a threshold below that floor.
Missing input, denied permissions, stale input, and a test with no sufficient
level rise are displayed explicitly. Retry after checking the input device,
Windows microphone permission, hardware gain, and room noise.

The microphone check does not block exam start. If no adaptive/manual threshold
was committed, audio uses its previous static fallback, learning background for
three seconds and comparing with `max(ambient + energy_threshold, 3 * ambient)`.
A previously committed threshold survives a failed retry but is identified
separately from that retry's measurements. An unavailable microphone disables
audio observations; it does not pause the exam or camera monitoring.

On exam start, calibration/preview observations are discarded and the setup
controls are locked. Only fresh exam audio can accumulate the existing two-second
audio review event; clearing hysteresis is unchanged. Pre-exam test speech creates
no review events. Stopping the application releases the microphone worker.

## Short hardware check

Launch `python -m proctoring` from the project's virtual environment. Complete
registration and reach camera setup. Check that the meter responds, calibrate in
quiet, and then speak normally. Note the displayed threshold and confirm quiet
sound stays below it. Try the sensitivity slider and repeat calibration. Begin
the exam and confirm an ordinary brief sound does not create a two-second event,
while sustained sound does. Check microphone denial/disconnection separately:
the availability warning should appear while camera monitoring and the timer
continue. Confirm ordinary microphone use is restored after exit.

Automated tests use generated samples and mocked devices. Real speech/noise
separation on a particular laptop still requires this operator check.
