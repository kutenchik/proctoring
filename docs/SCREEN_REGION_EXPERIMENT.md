# Screen-region experiment: collection, rules and validation

This is an explicitly selected **DEBUG / UNVALIDATED**, iris-only experiment.
It does not replace production calibration/classification or integrate the
earlier eyelid-openness candidate. Its own fit result permits debug predictions
only. It cannot authorize an exam, create evidence, or enable Windows restrictions.

## Evidence and limits of the existing replay

The user reports that an offline replay of the review's half-space code gave
134 correct labels and one RIGHT incorrectly labeled CENTER across 135 legacy
validation measurements. The same result without the aperture conditions is a
useful hypothesis about decision-region geometry. The supplied reading snippet
uses `reason: default_center`; that fallback is not positive evidence of an
on-screen gaze measurement. This result is development replay, not an independent
accuracy measurement, and it does not validate the new region model.

The two previous glasses/no-glasses exports have the same frozen calibration;
they are not independent eyewear baselines. That four-target calibration has no
known on-screen boundary/layout fixations or repeated CENTER anchor. The new
model deliberately cannot fit it. Held-out reading or other validation samples
are never converted into missing training points. Review claims about backend
accuracy, optical causes, CPU usage, universal fractions, or exact event timing
remain hypotheses rather than specifications.

## Targets and collection

The existing diagnostic panel, attempt selector, numerical export, countdown,
beeps, freshness checks and alignment readiness are reused. New target markers
are fixation points over the quiz layout; the camera oval is unchanged.

Training uses these 13 separate fixations:

| Target | Role and position |
| --- | --- |
| CENTER_START | On-screen; physical screen center, repeated at the end |
| SCREEN_LEFT / SCREEN_RIGHT | On-screen; requested client positions (0.08, 0.50) / (0.92, 0.50) |
| SCREEN_UPPER / SCREEN_LOWER | On-screen; requested client positions (0.50, 0.10) / (0.50, 0.88) |
| QUIZ / OPTIONS | On-screen; actual displayed question and answer-area centers |
| CONTROLS / MONITOR | On-screen; actual End-session control and camera-preview centers |
| OFF_LEFT / OFF_RIGHT / OFF_DOWN | Operator-known physical targets just beyond the corresponding screen edges |
| CENTER_END | On-screen; same physical screen-center position as CENTER_START |

The app maximizes for a fixed, visible diagnostic layout and restores the prior
window geometry afterward. Target coordinates are measured from the rendered
layout rather than assumed from requested fractions. Exported positions include
client and desktop coordinates, screen-normalized coordinates, screen/client
geometry, and device pixel ratio. Qt coordinates are logical pixels; these are
not camera pixels or iris features. Actual quiz, options, controls and monitor
layout positions are retained. Physical off-screen locations are explicitly
marked operator-known and unmeasured; their coordinates are not fabricated.

Definitions identify the role as `on_screen_calibration`,
`off_screen_calibration`, or `held_out_validation`. Moving/resizing the layout
during collection interrupts the pass. Use the same physical off-screen markers
and unchanged seating/lighting for training and validation.

At defaults, each training target has two seconds of preparation and three
seconds of collection. Prepare requires a fresh aligned face; training admission
also retains alignment checks during collection. At least 20 unique valid paired
eye samples per target are required by default. A target with insufficient
samples remains a failed fit; collection does not invent replacements.

Validation freezes the selected attempt and collects **new** measurements in
17 windows: center plus four near-edge on-screen fixations; READING/LEFT/RIGHT/
DOWN twice; BLINK, BRIEF_CLOSURE, SUSTAINED_CLOSURE, and SQUINT. Each validation
window is at least six seconds, plus the existing preparation interval. Invalid
fresh measurements stay in the denominator as UNKNOWN. The training alignment
admission does not discard the deliberate closure challenge measurements.

The default timed intervals total `13 × (2+3) + 17 × (2+6) = 201 seconds`, about
3.5 minutes, plus clicks, alignment and any retry time. This is not a guarantee
that every camera will deliver enough valid measurements in three seconds.

## Exact fit criteria

Each eye retains its own horizontal and vertical iris coordinates, expressed in
eye-width units. All medians, spreads, margins and feature bounds below use those
same units. No screen-coordinate projection, head-derived gaze label, or extra
openness membership requirement is introduced.

For target `T`, eye `E`, and iris axis `A`, the candidate computes:

```text
median = median(admitted measurements for T/E/A)
spread = nearest-rank p90(abs(measurement - median))
constant = calibration_eye_noise_floor * calibration_min_signal_noise
radius = max(constant, 2.5 * spread)
support = [median - radius, median + radius]
```

The default constant is `0.01 × 3 = 0.03` eye widths. Spread greater than
`calibration_max_spread` (default 0.12) fails the corresponding target/eye/axis.
Within-fixation spread is distinct from the intentional displacement between
on-screen target medians. These empirical supports are assumptions, not measured
optical error bounds or confidence intervals. The old `3 / eye_width_pixels`
assumption is exported for comparison but is not a term in this candidate's fit.
No replacement 0.8-pixel claim is made.

For each eye, CENTER_START to CENTER_END median change on each axis must be no
greater than the larger of the two support radii. This is a repeatability check;
it does not silently recenter validation or compensate from known target labels.
One repeated CENTER does not establish longer-term repeatability.

The on-screen region is the convex hull of the corners of all on-screen
per-target support boxes in that eye's `(horizontal, vertical)` feature plane.
The unexpanded target medians must themselves form a two-dimensional hull.
Convex interpolation between those observations is an experimental model, not
proof that all physical screen positions map into a rectangle or convex region.

For LEFT and RIGHT, the relevant axis is horizontal. For DOWN it is vertical.
The sign toward each off-screen target is learned from its displacement from
the repeated CENTER anchors. Both eyes must agree about that convention;
LEFT and RIGHT must have opposite horizontal signs. No mirroring sign is assumed.

On the learned signed axis:

```text
screen_outer = largest (signed on-screen median + its radius)
off_inner = smallest (signed matching off-screen median - its radius)
off_outer = largest (signed matching off-screen median + its radius)
uncertainty_gap = off_inner - screen_outer
```

Every eye/direction requires a **strictly positive** uncertainty gap. Thus DOWN
is compared with the most downward supported on-screen target, including lower
quiz/controls/monitor targets, rather than just CENTER. Overlap fails the
candidate's own fit and is reported by target and eye. The old point-core ready
flag is neither required nor forced true. Every training median must also receive
its intended label under the candidate's actual decision rules; this consistency
check is not a held-out accuracy estimate.

## Exact decision rules and UNKNOWN

Existing measurement validity remains: finite paired eye features and metadata,
quality at least 0.45, source eye width at least eight pixels, eye aperture
between 0.10 and 0.75 eye widths, supported iris geometry, and existing inter-eye
agreement limits. Feature averages must match their per-eye metadata. Aperture
is only a validity check, not a learned feature in this comparison. Landmarks
passing numerical checks do not prove that the iris is optically visible.

Each valid observation must also remain within training yaw/pitch coverage plus
10 degrees. Head pose is a veto only. Each eye must lie inside a bounded operating
domain: horizontal extent is supported by on-screen and lateral training;
vertical extent is supported by on-screen training, extended only toward the
calibrated DOWN support. Unsupported upper positions outside that domain return
UNKNOWN. There is no UP event and no unlimited half-space.

Within this domain, per eye:

- ON_SCREEN requires membership in the learned convex on-screen hull.
- LEFT/RIGHT require membership in the corresponding supported off-screen
  horizontal interval; there is no narrow per-target vertical membership rule.
- DOWN requires membership in the supported off-screen vertical interval;
  there is no narrow per-target horizontal membership rule.
- No supported region, an uncertainty gap, or more than one matching direction
  returns UNKNOWN. The two eyes must independently support the same final label.

Consequently, diagonal overlaps, unsupported extreme positions, failed fits,
invalid eyes, and out-of-coverage poses remain UNKNOWN. There is no final
`default_center`. Unknown or stale gaze does not become face absence or camera
failure. UNKNOWN is not counted as correct ON_SCREEN/reading. A physical gaze
position whose measured features incorrectly resemble supported data can still
be mislabeled; only fresh human validation can expose that limitation.

## Comparison and timing report

For a new region attempt, the existing point-core comparison is fitted from
only its new CENTER_START and OFF_LEFT/OFF_RIGHT/OFF_DOWN training rows. The
region model uses its explicit multipoint training rows. Both then predict the
same fresh held-out rows. Baseline CENTER is canonicalized to ON_SCREEN for
comparison; default production behavior is unchanged. No openness candidate is
included in this comparison.

Reports distinguish correct, incorrect, UNKNOWN, invalid, scored and unscored
measurements. Counts and predictions are retained per target, including both
reading/off-screen repetitions. Reading UNKNOWN is an abstention, not success.
The fit report exposes support terms, boundary gaps, repeatability and failures.

BLINK and BRIEF_CLOSURE have prompted phases. In the default six-second window,
the first and last two seconds instruct open eyes at screen center and are scored
against ON_SCREEN. The middle two seconds are mixed blink/closure transitions
and unscored; BRIEF_CLOSURE separately prompts closing and reopening within that
middle interval. The sustained closure interval is also unscored because labels
are operator instructions, not frame-level verified eyelid ground truth. UNKNOWN
rates and all directional outputs remain visible for review. SQUINT expects
ON_SCREEN, with UNKNOWN reported separately. Follow the phase instructions;
ordinary open-eye intervals are not automatically expected to be UNKNOWN.

An isolated instance of the **existing** event engine reports what each debug
stream would produce, independently for each classifier and validation window.
It receives the application's gaze threshold (default **3.0 seconds**), clearing
hysteresis (**0.75 seconds**), and observation-gap limit. It has no session,
evidence store, screenshots or physical alerts. It never feeds the production
event controller.

Strict contiguous false-direction runs are measured from the first to last
same-direction captured sample, with no unobserved tail. UNKNOWN, invalid data,
changed direction or a stale gap ends the run. These differ from already-active
engine events, which can bridge a brief clearing interval under existing
hysteresis. Mixed blink/closure windows expose directional runs/events but leave
whole-window false-direction scoring unassigned.

Timing reports include capture gaps, activation capture duration, threshold
overshoot, capture-to-UI-receipt delay, and matched face-inference latency. Missing
latency remains null. Capture gaps describe the observed diagnostic cadence;
the live panel also shows capture/monitoring FPS. A six-second fixation allows
testing a three-second threshold, but activation occurs on the first eligible
sample, not necessarily at exactly 3.000 seconds. This uses face-cadence debug
results and does not claim identical production combined-YOLO alert latency.

## Exact fresh operator workflow

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

1. Use necessary glasses normally. Keep seating and lighting consistent. Place
   comfortable repeatable physical targets just beyond the left, right and bottom
   edges. Avoid extreme eye rotation; head pose stays natural and separate.
2. Open the webcam and expand **Developer calibration diagnostics**. Enable
   **Screen-region experiment · DEBUG / UNVALIDATED**. Leave the openness
   candidate unused. Confirm Windows protection is inactive; do not start an exam.
3. Click **Begin new screen-region calibration**. For each of the 13 targets,
   wait for alignment readiness, click **Prepare screen calibration …**, then
   look at the displayed marker or requested physical target until the ending
   beep. CENTER means the physical screen center; UP is not silently CENTER.
   The actual quiz layout appears during each window and Prepare returns between
   windows. Keep its layout fixed.
4. After CENTER_END, inspect the new selected attempt's ID, baseline ID, and own
   `region_fit` result. A failed fit remains inspectable/exportable and can be
   checked in validation, but predictions remain UNKNOWN. It cannot enable an
   exam. Do not substitute a previously retained attempt.
5. Click **Start separate validation**. Follow its 17 Prepare steps: five
   center/near-edge on-screen positions; **READING → LEFT → RIGHT → DOWN** twice;
   then ordinary **BLINK**, **BRIEF_CLOSURE**, **SUSTAINED_CLOSURE**, and on-screen
   **SQUINT**. Read the question and options naturally. Use the same physical
   off-screen markers. Follow the open/close phase cues and wait for each ending
   beep. These are new capture intervals after training, not a random frame split.
6. Explicitly enable **local numerical export** and save the selected attempt
   with validation, for example `screen-region-fresh-with-validation.json`.
   Verify that the selected attempt ID/hash and validation source ID/hash match.
   Exports contain numerical data and target-layout provenance, not images/video.
7. Review per-target errors, UNKNOWN, invalid counts, false-direction runs and
   isolated event timing. Record whether eye markers actually followed visible
   irises during reading, DOWN, squint and closure. Necessary glasses are not a
   problem to solve by removal. An optional without-glasses comparison requires
   another **Begin new screen-region calibration** and its own baseline/export.

If these new data are used to choose any further rule or margin, collect another
separate validation pass before claiming that revised version works. A passing
fit or automated suite cannot replace operator validation.

## Replay commands and preserved behavior

Legacy diagnostic replay explicitly reports that region comparison is unavailable:

```powershell
.\.venv\Scripts\python.exe scripts/replay_openness_candidate.py without-glasses-fresh-with-validation.json --candidate screen-region --output artifacts/screen-region-legacy-replay.json
```

After collecting a fresh multipoint attempt and validation:

```powershell
.\.venv\Scripts\python.exe scripts/replay_openness_candidate.py screen-region-fresh-with-validation.json --candidate screen-region --output artifacts/screen-region-development-replay.json
```

Replay uses source identities/hashes and saved fit/timing configuration. It is
development replay of already-collected measurements, never another human test.

The oval, production calibration and gaze classifier, eye-openness validity
cutoff, YOLO phone/person detection, face-absence handling, three-second gaze
threshold, event hysteresis, timer, monitoring recovery, evidence storage,
Windows protection and emergency release remain unchanged. Real Windows
restrictions stay disabled for development and this operator workflow.

## Verification status

- Final automated regression run: **965 passed in 13.84 seconds**.
- Native Windows QA completed all **13 training + 17 validation windows** on a
  1920×1080 display using synthetic numerical measurements and real widget
  coordinates. All displayed fixation markers were inside the client and
  physical screen. Phase prompts and matching source IDs were checked. The
  process exited successfully; production calibration remained unready, no
  exam started, and protection stayed **INACTIVE**. No webcam was opened.
- The synthetic native export was replayed successfully with matching attempt
  IDs/hashes and frozen configuration. This checks collection, comparison and
  event-report plumbing; its label counts are not human accuracy measurements.
- Legacy replay returned **comparison unavailable: missing multipoint on-screen
  training**. It did not fabricate screen-boundary samples from reading or
  score every missing-reference UNKNOWN as correct.
- Live validation displays the DEBUG region label and point-baseline label.
  Missing/stale results show UNKNOWN. Numerical text refresh is limited to four
  updates per second during collection; measurements/classification continue at
  full cadence. Explicit exports retain the numerical samples. Rendered target
  positions are stored once per target definition and referenced by sample ID.

Implementation files: `vision/screen_region.py`, `vision/screen_region_protocol.py`,
`vision/screen_region_timing.py`, and the existing `vision/diagnostic_validation.py`;
UI changes are in `ui/diagnostic_panel.py`, `ui/calibration.py`, `ui/window.py`, and
the small new `ui/screen_target.py`. `vision/monitor.py` now includes its atomically
matched face-inference latency in diagnostic results. The existing
`scripts/replay_openness_candidate.py` gained the explicit `--candidate screen-region`
option. Four focused region test files and the existing monitor regression test
cover the new behavior.

**Fresh post-patch human region validation is pending.** No claim is made yet
about reliable eyes-only DOWN, full-screen reading coverage, glasses performance,
closure/squint rejection, or readiness to replace production gaze.
