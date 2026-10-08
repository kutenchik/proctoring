# Pixel gate and guarded aperture DOWN supplement

This is a configurable calibration/classifier change. The automated checks below
do not establish accuracy on a human webcam. Collect a fresh session baseline;
the reported failed-fit numbers alone do not measure future classification error.

## Fit gate

`vision.calibration_pixel_uncertainty_multiplier` defaults to `0.8` in
`config/default.toml`. The constant floor remains
`calibration_min_signal_noise * calibration_eye_noise_floor` (default `0.03`).

For CENTER–DOWN, fit now compares absolute vertical displacement of the two-eye
mean with:

```
max(constant floor,
    0.8 * max(supplied pixel floor p90 for CENTER and DOWN),
    2.0 * max(CENTER vertical p90 spread, DOWN vertical p90 spread))
```

Other pairs retain radial separation and `2.5 * radial p90 spread`, using the
new pixel multiplier. Required sample counts, the maximum-spread check and all
other target-pair checks still apply. Head pose cannot supply target separation.
Diagnostics identify the actual one-dimensional or two-dimensional metric,
each contribution, the dominant term and the separate radial distance.

For the reported old pixel contribution `0.0906`, the source floor is
`0.0906 / 3 = 0.0302` (about 33.11 source pixels per eye width). The new pixel
contribution is `0.02416`. A vertical displacement of `0.0463` exceeds the
required `0.03` at low spread; at vertical p90 spread `0.0199`, the requirement
is `0.0398`. This explains the changed gate; it does not prove gaze accuracy.

## Aperture assistance

The live observation path passes its matching `FaceMeasurement` into the
session classifier. Accepted paired CENTER samples supply a separate median
opening for each eye. DOWN iris references also come from the same attempt.
Resetting, discarding a target or failing fit clears the fitted references.

- Either eye below `0.08` absolute opening or `0.35` of its own CENTER opening
  vetoes all gaze directions to UNKNOWN, including apparently valid iris output.
- The existing measurement rejection below `0.10` aperture remains unchanged;
  `0.08` is an additional closure guard, not a relaxation of iris visibility.
- DOWN assistance requires both valid eyes to move at least 35% of their learned
  CENTER→DOWN vertical displacement, with each relative opening below `0.70`.
  The learned sign is used. Finite horizontal/vertical bounds around the observed
  CENTER/DOWN references prevent arbitrary off-distribution iris positions from
  receiving a supplemental DOWN label.
- Reduced opening between `0.40` and `0.70` supports CENTER only when the iris
  remains in the bounded calibrated CENTER region, below the soft DOWN boundary.
  The exact soft boundary gives DOWN precedence when its aperture guards pass.
  Unrelated positions are not automatically labeled CENTER.
- Missing/invalid eye measurements or missing aperture references yield UNKNOWN
  in the live path. No landmark-presence claim substitutes for iris visibility.
- The existing head-pose veto runs before a positive supplement. Aperture results
  have no fabricated confidence/probability. Eyes-only numerical comparison calls
  remain available to old tests/tools; the live camera path always supplies the
  current eye measurements and applies the guards.

Fit readiness is still determined by measured calibration gates. The supplement
cannot enable a failed calibration. Face absence and monitoring health are not
derived from aperture. The 3-second review threshold and 0.75-second hysteresis
are unchanged, as are phone/person detection, timer/recovery, evidence and
Windows protection.

## Replay and verification

New four-target exports identify `guarded_aperture_down_v1` and freeze required
sample counts and radius settings. Separate validation applies the same helper
to each new measurement's eye metadata. Old exports retain their original
iris-only comparison; they are not silently relabeled as new human results.
The separate screen-region experiment keeps its existing iris-only baseline.

Automated suite: **1,088 passed**. Coverage includes the `0.0463` vertical case
at p90 spreads `0`, `0.01`, `0.0199`; unstable/overlapping fit rejection; closure,
one-eye closure, squint and guarded DOWN; missing/nonfinite data; head veto;
reference reset; and actual observation/event activation at 3.0 seconds and
clearing at 0.75 seconds. Native Windows Qt startup and guided collection also
completed with synthetic inputs, no webcam, no exam and restrictions disabled.

## Short fresh human check (pending)

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

1. Leave Windows protection disabled and the screen-region experiment unchecked.
   Collect a new CENTER/LEFT/RIGHT/DOWN calibration with normal seating, lighting
   and any needed glasses. Inspect the updated fit contributions if it fails.
2. After collection, use the existing developer panel's `eye_only_estimate`
   direction/reason and optional live eye close-ups. With an operator observing,
   repeat CENTER → LEFT → RIGHT → DOWN → ordinary reading, then screen-facing
   squint, ordinary blinks, a brief closure and a sustained closure. Keep head
   pose comfortable; it is not a substitute for the eye signal.
3. Check whether closures return UNKNOWN, whether screen-facing squint avoids
   DOWN, and whether DOWN repeats without ordinary reading being mislabeled.
   Use the existing separately collected validation/export when recording new
   labeled results; UNKNOWN is an abstention, never counted as correct reading.

No new human validation has been performed for this patch.
