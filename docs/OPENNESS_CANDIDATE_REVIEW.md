# Calibrated eyelid-openness candidate: development review

This review uses `glasses-fresh-with-validation.json`,
`without-glasses-fresh-with-validation.json`, and the supplied eye close-up
screenshots. It is development evidence, not a new human test of the patched
candidate. Production gaze classification and calibration remain separate from
the optional **DEBUG / UNVALIDATED** candidate.

## Calibration selection and export

The entire calibration object is identical in both files. Its last accepted
timestamp is **634153.015** and last recorded timestamp is **634153.109**.
The canonical JSON SHA-256 is
`7b95e2f28b5160dd0d9886a48e75e445015f6c115cf493bd6e93f8a4c312c885`.
The glasses file has no validation. The other file's validation freezes this
same calibration, with training cutoff **634153.109**. These files are **not
independently calibrated glasses/no-glasses trials**.

The retry path clears the active collector and starts a new baseline; it also
retains the old numerical attempt intentionally. Validation and export use the
selected retained attempt, not whatever the operator is currently viewing in
the camera. A selection defect existed when remembering an identical latest
snapshot: the deduplication return could leave a previously selected older
attempt selected. That path now selects the existing latest snapshot. The
files alone cannot prove which operator path produced these two exports; they
contain no evidence that a second baseline was collected.

The existing panel and export now identify the current baseline, selected
retained attempt, and validation's source attempt. Previous-baseline selection
is called out explicitly. **Retry all targets (new baseline)** does not turn an
old retained snapshot into new calibration measurements.

## What the supplied measurements establish

All source frames are **640×480**. Training contains **109 accepted samples**:
CENTER 27, LEFT 28, RIGHT 27, DOWN 27. The 78 rejected records are timing-only:
74 captured before collection and four arriving after collection. There are no
recorded invalid-eye samples in this calibration or its 135 validation rows.

The frozen default classifier produced:

| Operator target | Correct label | Incorrect directional label | UNKNOWN | UNKNOWN rate |
| --- | ---: | ---: | ---: | ---: |
| CENTER | 11/27 | 0/27 | 16/27 | 59.26% |
| LEFT | 27/27 | 0/27 | 0/27 | 0% |
| RIGHT | 22/27 | 0/27 | 5/27 | 18.52% |
| DOWN | 2/27 | 0/27 | 25/27 | 92.59% |
| READING, CENTER expected | 0/27 | 0/27 | 27/27 | 100% |

Overall: **62/135 correct (45.93%)**, **73/135 UNKNOWN (54.07%)**. Reading had no
off-screen predictions but also no correct CENTER predictions. UNKNOWN is not
counted as correct. All 25 UNKNOWN DOWN predictions report
`outside_reference_core`. Lowering the 0.10 aperture validity cutoff cannot
resolve this recorded failure: all 27 DOWN measurements already passed
validity, and their minimum apertures were 0.119679/0.117646.

Only CENTER–DOWN fails the production training gate:

| Quantity | Normalized eye-width units |
| --- | ---: |
| Measured 2D iris separation | 0.048828 |
| Constant-floor contribution | 0.030000 |
| Assumed pixel-floor contribution | 0.091539 |
| Measured radial-spread contribution | 0.055469 |
| Final required separation | 0.091539 |
| Vertical-only separation | 0.040917 |
| Vertical-only spread contribution | 0.021144 |

The pixel assumption dominates, but removing it alone would still leave the
2D separation below the radial-spread gate. Unrelated horizontal variability
inflates that radial spread. Both eyes have positive DOWN vertical shifts
(**0.044604 left / 0.038262 right**) and disjoint CENTER/DOWN central-80%
vertical intervals in training. This supports investigating a feature-specific
candidate; it does not establish reliable future classifications.

Openness medians normalized by each eye's **training CENTER** baseline are:

| Collection and target | Left raw openness | Right raw openness | Left / baseline | Right / baseline |
| --- | ---: | ---: | ---: | ---: |
| Training CENTER | 0.330001 | 0.328077 | 1.000000 | 1.000000 |
| Training DOWN | 0.219074 | 0.196661 | 0.663859 | 0.599434 |
| Validation CENTER | 0.330850 | 0.319419 | 1.002573 | 0.973609 |
| Validation DOWN | 0.139112 | 0.147628 | 0.421549 | 0.449978 |
| Validation READING | 0.311392 | 0.308234 | 0.943610 | 0.939518 |

DOWN narrowing and iris displacement offer complementary evidence, but their
amplitudes shift between passes. DOWN vertical medians move from
**0.499554/0.493741** in training to **0.520592/0.512660** in validation. CENTER
vertical medians move from **0.454950/0.455479** to **0.430454/0.432697**. The
training DOWN openness range is also substantially higher than the validation
DOWN range. A candidate must not absorb arbitrary near-closure merely to
make this reused pass succeed.

Head pose changed as well: CENTER median yaw/pitch moved from
**−0.9568°/3.2333°** to **2.0731°/5.9691°**. These measurements do not isolate
eyewear, pose, target choice, or tracking as the cause. Head pose remains a
separate signal and does not supply an eye-gaze direction.

## Screenshot interpretation

The operator described the sequence as **UP / LEFT / RIGHT / DOWN**. UP is not
silently relabeled CENTER or used as a physical-screen-center reference.
Screenshots 3 and 6 are identical, as are 4 and 5; there are eight distinct
images. The DOWN close-ups show narrower lids while geometry remains valid.
The displayed iris markers can extend beyond the visible narrow opening.
These enlarged, static crops cannot establish whether the iris was truly
observable, whether markers followed it across frames, or whether glasses
caused a failure. They are not a validated automatic glare or blink detector.

## Short fresh operator test

From the project directory, launch with real Windows restrictions disabled:

```powershell
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

1. Use normal necessary glasses first. Keep seating, lighting and comfortable
   screen-facing head position consistent. Enable optional eye close-ups in
   the developer panel if useful. Images and video are not saved.
2. Press **Retry all targets (new baseline)**. Collect CENTER at the **physical
   screen center**, then LEFT, RIGHT and DOWN using the existing Prepare steps
   and three-second collection windows. UP is not CENTER. Use comfortable
   targets just beyond the screen edges, not extreme eye rotation.
3. In the developer panel, verify that the selected retained attempt belongs
   to the current baseline. Record its attempt ID and baseline ID. A failed
   production calibration can still be examined; it must not enable an exam.
4. Check **Evaluate calibrated eyelid-openness candidate · DEBUG / UNVALIDATED**,
   then **Start separate validation**. Verify its source attempt ID matches
   the selected attempt. The references stay frozen throughout the pass.
5. Follow the nine Prepare/collection steps: **CENTER → LEFT → RIGHT → DOWN →
   READING → BLINK → BRIEF_CLOSURE → SUSTAINED_CLOSURE → SQUINT**. Read the actual
   question and answer choices normally in READING. During BLINK, look at
   physical screen center and blink ordinarily. For BRIEF_CLOSURE, briefly
   close and reopen both eyes. For SUSTAINED_CLOSURE, gently keep them closed
   during the short collection window. For SQUINT, keep looking at screen
   center while gently narrowing the lids. Do not look down for these control
   conditions. Follow the start/end beeps for each window.
6. Explicitly enable numerical export and save the completed selected attempt
   with its validation. Confirm the exported calibration and validation source
   IDs match. Compare default and candidate predictions, including UNKNOWN and
   invalid-measurement counts. Check false off-screen labels during reading,
   blinks, closure, and squinting; do not score UNKNOWN reading as correct.
7. Only if comfortable, repeat without glasses from **Retry all targets (new
   baseline)** and save a separately named export with a different baseline
   and attempt ID. Removing necessary corrective glasses is not a product
   solution.

Fresh data collected after the patch evaluates the candidate. If those data
are used to choose another feature or boundary change, collect another
separate pass before claiming validation of that change. The existing
three-second review-event threshold is unchanged; this debug candidate does
not create events or authorize exams.

## Candidate implementation and verification status

`vision/openness_candidate.py` is used only by explicitly enabled diagnostic
validation. It copies accepted calibration rows and learns each eye's horizontal
iris, vertical iris, and CENTER-normalized aperture references. Production
calibration readiness is ignored for candidate fitting and is never modified.
The candidate's own `fit_ready` permits DEBUG predictions only.

Horizontal LEFT/CENTER/RIGHT separation is checked per eye. DOWN requires a
positive vertical iris shift and reduced normalized openness in **both** eyes.
Each gate and prediction uses the same per-axis units, constant contribution
(`calibration_min_signal_noise × calibration_eye_noise_floor`, divided by that
eye's CENTER aperture for normalized openness), and measured spread contribution
(`2.5 × p90 absolute deviation`). The candidate reports the assumed pixel term
for comparison but does not treat it as an established landmark-error bound.
This empirical alternative is an experimental assumption, not proof that the
production safeguard should be removed.

Predictions require membership in finite per-axis reference bounds. DOWN also
requires at least half of both learned vertical and openness displacements;
openness cannot compensate for missing vertical evidence. Its incidental
horizontal offset is allowed only within the bounded CENTER-to-DOWN span.
Invalid, missing, inconsistent or unsupported measurements, overlapping support,
and failed candidate fits return UNKNOWN. Head pose can veto coverage but cannot
supply a label. Numerical validity still does not establish optical iris
visibility; real closed-eye and squint controls remain necessary.

The shared calibration passes the candidate's own feature-specific gates.
Replaying the existing validation produces the following **development** results
(each row has 27 measurements):

| Target | Default correct | Default UNKNOWN | Candidate correct | Candidate UNKNOWN | Candidate incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| CENTER | 11 | 16 | 22 | 5 (18.52%) | 0 |
| LEFT | 27 | 0 | 15 | 12 (44.44%) | 0 |
| RIGHT | 22 | 5 | 3 | 24 (88.89%) | 0 |
| DOWN | 2 | 25 | 11 | 16 (59.26%) | 0 |
| READING → CENTER | 0 | 27 | 4 | 23 (85.19%) | 0 |

Candidate totals: **55/135 correct (40.74%)**, **80/135 UNKNOWN (59.26%)**,
zero incorrect non-UNKNOWN predictions and zero incoming invalid measurements.
Reading has zero false off-screen predictions, but only four correct CENTER
labels. The joint per-eye bounds reduce LEFT/RIGHT coverage: the candidate uses
vertical and openness support for every label, not just a DOWN override. This
is worse overall coverage than the default, despite more DOWN labels. No
boundary was retuned to these replay results. **Do not integrate this candidate
based on this replay.**

The glasses export has no validation, so it yields a fit report only. The
replay does not invent a second eyewear result. The new replay command rejects
contradictory source IDs/hashes and explicitly flags these legacy exports as
missing identity metadata. Their identical frozen calibration/reference values
can be compared, but filenames do not establish the collection conditions.

To reproduce the numerical development replay without a camera or exam:

```powershell
.\.venv\Scripts\python.exe scripts/replay_openness_candidate.py without-glasses-fresh-with-validation.json --output artifacts/openness-candidate-development-replay.json
```

The existing numerical export now contains `attempt_identity`,
`current_collection_at_export`, and `validation.source_attempt_identity`.
Candidate fit, per-target counts, confusion, and reasons are in
`validation.openness_candidate`; individual validation rows retain both default
and candidate labels. No images, video, or extra evidence-storage behavior was
added. Blink/closure windows include transitions, so their UNKNOWN results are
reported as abstentions, not automatically scored as correct classifications.
READING and SQUINT expect CENTER; their UNKNOWN counts remain separate.

Automated verification: **879 tests passed in 13.10 seconds**. Coverage includes
fresh-baseline reset/selection, validation source binding, export provenance,
normalization, fit rejection, iris/openness conjunction, invalid eyes and closure,
unsupported squint geometry, UNKNOWN accounting, and the full nine-target UI
sequence without starting an exam. A native Windows application startup and
visual panel check completed with protection **INACTIVE**, production calibration
not ready, and exam start disabled. That check opened no webcam.

Files changed in this task:

- `src/proctoring/ui/calibration.py`, `src/proctoring/ui/diagnostic_panel.py`:
  attempt identity, source binding, selection fix and opt-in validation controls.
- `src/proctoring/vision/diagnostic_validation.py`, new
  `src/proctoring/vision/openness_candidate.py`: parallel DEBUG predictions and
  challenge collection/scoring.
- New `scripts/replay_openness_candidate.py`: explicit numerical development
  replay with source checks.
- `tests/test_diagnostic_ui.py`, `tests/test_ui_stage3.py`, new
  `tests/test_openness_candidate.py`, `tests/test_openness_validation.py`,
  `tests/test_openness_replay.py`, and this document.

No new post-patch human gaze validation has been performed. Reliable eyes-only
DOWN, real closure/squint rejection and matched eyewear performance remain to
be established by the fresh sequence above. The oval, default classifier and
calibration gate, YOLO, face absence, event thresholds/hysteresis, timer/recovery,
evidence storage, Windows protection and emergency release were not changed.
