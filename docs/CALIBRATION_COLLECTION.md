# Guided calibration collection

This changes collection and interaction, not gaze accuracy. Classifier boundaries,
fit thresholds, eyelid validity thresholds, the face oval, and exam monitoring
rules are unchanged. Use the safe default configuration (Windows restrictions off).

## Defects observed in the supplied recording

The recording shows LEFT discarded at 19/20, and DOWN discarded at 0/20 and
15/20. Monitoring remained healthy. The fixed three-second window discarded
near-complete targets. Eye validity failures also erased independently observed
face stability, adding a hold-still delay after an otherwise brief invalid eye
measurement. Preparation exclusions were displayed among user-facing errors.
These observations do not establish poor target separation or gaze accuracy.

## Collection policy

- One Start calibration runs preparation and collection automatically through
  CENTER, LEFT, RIGHT, DOWN. Each target has a start/completion audio cue. CENTER
  has a marker at the physical screen center. Off-screen targets have physical
  edge instructions and no on-screen fixation marker.
- Collection lasts at least the configured nominal interval (default 3 seconds).
  If the valid sample count is insufficient, it continues to a fixed maximum
  elapsed interval (default 6 seconds). Neither invalid measurements nor repeated
  polling move this deadline. A burst cannot finish the target before the nominal
  interval. The required count (default 20) is unchanged.
- Only fresh unique captures in the current target interval are admitted; late
  inference arriving at or after the hard deadline cannot fill it retroactively.
- Brief invalid eyes reject eye samples while fresh valid face geometry continues
  to establish stability. Missing face geometry is never considered stable.
  The existing eye/pose/size checks still gate sample admission.
- A fixed face-position reference uses the existing alignment drift/scale limits.
  Significant movement or geometry continuity loss invalidates the affected
  unfinished target. Return to the previous position and retry locally. Completed
  compatible targets remain; resettling at a different position cannot silently
  mix baselines. Camera changes or monitoring interruption invalidate the baseline.
- Pause/cancel preserves completed compatible targets and discards the unfinished
  collection. Retry this target replaces that target's samples; it does not pool
  failed attempts. An explicit new-baseline control remains available.
- Position stability, valid sample count and overall target completion are shown
  separately. Detailed numerical rejections remain in developer diagnostics.

The optional screen-region experimental training uses the same bounded collection
policy and automatic target progression, with existing target positions and fit
rules. Its separate held-out developer validation remains optional and cannot
authorize an exam. Retained attempt and validation-source identities are preserved.

## Short real-camera check

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

1. Open the camera, keep the same seating/lighting, and align normally. Keep your
   necessary corrective glasses. Leave the experimental backend unchecked to
   test the ordinary four-target workflow first.
2. Click **Start calibration** once. Follow CENTER → LEFT → RIGHT → DOWN, allowing
   the preparation interval and completion cue for each target. Keep your head
   comfortable and approximately frontal. Only CENTER has an on-screen marker.
3. Blink normally during one target. The blink's eye samples must be rejected;
   stable fresh face positioning and earlier valid samples should remain. If the
   count is below 20 at three seconds, the target should remain for the extension.
4. If a target times out, use **Retry this target**. Verify earlier targets remain
   completed. Optionally pause/resume once, or move away and return: incompatible
   unfinished samples must be cleared, not combined across positions.

Stop after this short collection check. No extended developer validation is
required to exercise the workflow. Report which target reached the maximum,
the sample count and the displayed reason if it still cannot be collected.
Passing collection does not guarantee that the unchanged calibration fit will
pass, or that human gaze classification is accurate. That remains a separate
fresh human-validation question.

## Verification performed

- Full automated suite: **1,017 passed** (16.53 seconds).
- Native Windows Qt startup and automatic four-target collection completed with
  synthetic measurements, including 19/20 at the nominal boundary followed by
  the twentieth sample during extension. The physical-center marker was checked.
- Native Windows Qt experimental training completed all 13 targets automatically
  with synthetic measurements; the separate validation pass was not required.
- No exam, webcam, or Windows restriction hooks were activated by those UI checks.
  Exam elapsed time remained zero. These are collection/UI checks, not human
  accuracy results. The short real-camera check above remains pending.

Main implementation files are `vision/collection.py`, `vision/alignment.py`,
`ui/calibration.py`, `ui/diagnostic_panel.py`, `ui/window.py`, and the adaptive
window support in `vision/diagnostic_validation.py`. The maximum collection
duration is configured by `vision.calibration_max_collection_seconds` in
`config/default.toml` (loaded through `config.py` / `vision/settings.py`).
