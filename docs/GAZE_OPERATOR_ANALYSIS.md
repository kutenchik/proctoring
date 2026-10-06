# Operator gaze analysis — 2026-10-05

Source: `gaze-failed-attempt-with-validation.json`, SHA-256 `d036a0fe8f04ebec4f2828da6ef6fa2a2c06e7ab00f7976c03aef51d3e75600e`. The file is unchanged. This is an actual operator collection, unlike earlier synthetic regressions. Its predictions were exploratory because production calibration failed.

The export identifies three distinct issues: pixel-floor rejection of CENTER–DOWN, sensitivity of the DOWN classifier to horizontal movement, and ordinary reading overlapping the LEFT reference. Only the bounded DOWN classification defect was patched. No acceptance threshold was lowered, and the supplied calibration remains rejected. Reading/LEFT discrimination remains unresolved.

## Gate decomposition

Every recorded source frame is **640×480**. All distances and contributions below are in normalized eye-corner widths, with 2D Euclidean distance for the production gate. The threshold is the maximum of the constant, pixel and radial-spread terms.

| Pair | Separation | Constant | Pixel floor | Measured spread × 2.5 | Required | Result |
|---|---:|---:|---:|---:|---:|---|
| CENTER–LEFT | 0.105661 | 0.030000 | 0.090035 | 0.053368 | 0.090035 | Pass |
| CENTER–RIGHT | 0.111530 | 0.030000 | 0.090035 | 0.053368 | 0.090035 | Pass |
| **CENTER–DOWN** | **0.079398** | **0.030000** | **0.090035** | **0.056452** | **0.090035** | **Fail** |
| LEFT–RIGHT | 0.215967 | 0.030000 | 0.089060 | 0.038215 | 0.089060 | Pass |
| LEFT–DOWN | 0.094529 | 0.030000 | 0.089060 | 0.056452 | 0.089060 | Pass |
| RIGHT–DOWN | 0.155979 | 0.030000 | 0.086955 | 0.056452 | 0.086955 | Pass |

**The pixel term dominates every pair; CENTER–DOWN is the only failed pair in this file.** It is a different attempt from the three earlier screenshots. CENTER's p90 supplied floor is 0.030011536; multiplying by three gives 0.090034608. CENTER–DOWN fails by 0.010636733 eye widths. Its relevant vertical separation is 0.070283421, rather than the larger combined 2D separation 0.079397875.

| Training target | Accepted | Rejected deliveries | Median left/right eye widths, source px |
|---|---:|---:|---|
| CENTER | 26 | 20 | 33.812 / 35.028 |
| LEFT | 27 | 20 | 34.234 / 34.761 |
| RIGHT | 26 | 21 | 34.946 / 36.283 |
| DOWN | 26 | 20 | 35.334 / 35.644 |

The 81 rejected deliveries comprise 77 preparation captures and four post-window arrivals. They are **not** 81 invalid-eye measurements. No records were dropped by capacity limits. All 105 accepted training and all 134 validation measurements have valid features; the held-out pass has zero invalid measurements. Narrow-eye/blink handling does not explain this failure.

The one-pixel bound is demonstrably stricter than observed training spread here. That does not establish its appropriate replacement or justify lowering it: separate validation exposes serious classification failures even if the gate were bypassed.

## Directional repeatability

Relevant-axis displacement from that pass's CENTER median:

| Direction and relevant axis | Training | Separate validation |
|---|---:|---:|
| LEFT horizontal | +0.105531 | +0.141748 |
| RIGHT horizontal | −0.110053 | −0.113947 |
| DOWN vertical | +0.070283 | +0.063553 |

Each target's relevant-axis central 80% interval is disjoint from CENTER in both passes. Horizontal direction is repeatable for LEFT/RIGHT, and the vertical DOWN signal repeats. LEFT's amplitude changes more than RIGHT's. This is evidence of usable directional signal in these windows, **not** proof of accurate gaze classification or generalization.

Training per-eye coordinates, shown as median / p90 absolute deviation:

| Target | Left horizontal | Right horizontal | Left vertical | Right vertical |
|---|---|---|---|---|
| CENTER | 0.537411 / 0.019228 | 0.465984 / 0.020762 | 0.440468 / 0.010945 | 0.435958 / 0.009209 |
| LEFT | 0.626435 / 0.021501 | 0.589545 / 0.023114 | 0.457737 / 0.007465 | 0.428477 / 0.007385 |
| RIGHT | 0.417755 / 0.020189 | 0.363760 / 0.022606 | 0.447895 / 0.009625 | 0.463565 / 0.006671 |
| DOWN | 0.547372 / 0.027442 | 0.532987 / 0.019773 | 0.511138 / 0.005347 | 0.504600 / 0.008183 |

DOWN's combined horizontal spread is 0.022305 versus vertical spread 0.005368. Horizontal variation accounts for 98.896% of squared displacement in its radial p90 tail. This affects its radial spread contribution, but **does not determine the failed gate**, because the pixel contribution is still larger.

## Separate validation, before patch

The first held-out measurement is 95.828 seconds after the last recorded training measurement. Raw timestamps are unique, inside their new target windows and separate from training. Replaying the original frozen-reference classifier reproduces all 134 stored labels.

| Operator target | Correct | Incorrect | UNKNOWN | Invalid |
|---|---|---|---|---:|
| CENTER | 26/26, 100% | 0 | 0 | 0 |
| LEFT | 19/27, 70.37% | 0 | 8/27, 29.63% | 0 |
| RIGHT | 27/27, 100% | 0 | 0 | 0 |
| DOWN | 2/27, 7.41% | 0 | 25/27, 92.59% | 0 |
| READING, expected CENTER | 8/27, 29.63% | 13/27 LEFT, 48.15% | 6/27, 22.22% | 0 |

Overall: 82/134 expected matches (61.19%), 13 wrong labels (9.70%), and 39 UNKNOWN (29.10%). UNKNOWN is never counted as correct. These are per-measurement results from short, temporally correlated windows, not independent-trial accuracy estimates.

All 39 UNKNOWN predictions have reason `outside_reference_core`. None result from invalid features, head-pose veto or an ambiguous nearest-reference margin.

**DOWN cross-axis sensitivity:** its training reference is `(0.539737, 0.508078)` and validation median is `(0.502676, 0.510834)`. Horizontal shift −0.037061 exceeds its old radius 0.023819, while vertical shift is only +0.002756. All 27 DOWN samples fall within that radius vertically; 24 exceed it horizontally, and one additional sample fails when the two axes are combined. Both eyes repeat the vertical signal: left 0.511138 → 0.514058, right 0.504600 → 0.507140.

**LEFT amplitude shift:** validation's horizontal median moves +0.025533 relative to its frozen reference. All eight LEFT UNKNOWN samples exceed the relevant horizontal tolerance 0.031698. Ignoring vertical variation would not fix these eight, and widening LEFT would be particularly questionable given the reading errors.

**Reading ambiguity:** reading horizontal p10–p90 `[0.468518, 0.611138]` overlaps LEFT training `[0.599518, 0.621435]`. Thirteen valid reading samples actually receive LEFT, so this is observed feature-space/classification confusion, not a hypothetical risk. The longest uninterrupted LEFT run is ten samples spanning 0.969 seconds; the export does not show a misconduct event, and this span is shorter than the unchanged three-second event threshold.

Matched-target head median changes are approximately +0.925° to +1.425° yaw and −0.477° to −0.926° pitch. Reading's head median is yaw +0.835°, pitch +0.750°. Small pose changes may affect eye geometry, but this file cannot establish them as the causal explanation. Head pose is neither substituted for gaze nor used to rescue a classification.

## Targeted correction

The original classifier required proximity to a 2D point for DOWN. The patch adds only a **finite horizontal DOWN region**:

1. Its vertical position is the trained DOWN vertical coordinate.
2. Its horizontal endpoints are the trained CENTER and DOWN horizontal coordinates. No endpoint is fitted to validation measurements.
3. Distance is 2D Euclidean distance to that finite segment. Its radius is no greater than the original DOWN radius and is capped at 0.4 times distance to the nearest other reference. It is not an unlimited horizontal stripe.
4. Overlap with an accepted non-DOWN region returns UNKNOWN with no similarity. Original point classification remains the fallback when the extension is not entered; original DOWN-disk decisions and radii remain unchanged.
5. The existing head veto runs first. A shared helper keeps production and debug predictions consistent.

Only `vision/calibration.py` and `vision/diagnostic_validation.py` change runtime behavior. All production fit gates remain unchanged. Reconstructing the supplied training attempt still rejects CENTER–DOWN; production `ready` stays false and production gaze labels remain UNKNOWN. The debug path can inspect the partial correction without enabling an exam.

**Development replay after patch:** DOWN becomes 27/27, with precisely 25 UNKNOWN→DOWN changes. CENTER, LEFT, RIGHT and READING labels are identical to the supplied pre-patch pass. Reading still has 13/27 false LEFT labels. Because this data informed the change, the replay is not a new human validation result and must not be presented as post-patch accuracy.

No new diagnostic collection infrastructure or fields were added. No field is missing for the diagnosis above. Windows protection/emergency behavior, phone/person detection, event thresholds/hysteresis, monitoring recovery, exam timing and normal evidence behavior are unchanged. Real Windows restrictions remain disabled during this work.

## Automated verification

- Before the patch, 846 assertions checked the supplied raw record counts, source dimensions, fractional per-eye feature averaging, pixel floors, target medians/spread, production rejection, independent timestamps and exact replay of all 134 original validation labels. Aggregate evidence and the input digest are saved in `artifacts/gaze-operator-analysis.json`.
- After the patch, the full suite passed: **651 tests in 9.69 seconds**, including 20 new regressions in `tests/test_down_reference_extension.py`. The new tests cover finite horizontal/vertical limits, reversed endpoints, preserved original radii, proximity to other references, UNKNOWN on overlap, degenerate references, unchanged acceptance gates, head veto, and production/debug parity plus original fallback behavior across 6,552 synthetic points. They do not depend on the operator JSON. Output: `artifacts/gaze-operator-regression-tests.txt`.
- Development replay of the inspected operator data confirms exactly 25 DOWN UNKNOWN labels change; no other stored target labels change. The original JSON is retained unchanged. These replay results are not independent human validation.
- Application startup was checked in calibration-debug with protection INACTIVE and exam start disabled; the check opens no camera and starts no exam. No post-patch human gaze collection was performed.

## What to repeat manually

Restart the patched application with:

```powershell
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

Keep camera/seating fixed and use identifiable physical LEFT/RIGHT/DOWN targets so training and validation do not unintentionally use different positions. Collect fresh CENTER/LEFT/RIGHT/DOWN calibration, then a **new** separate CENTER/LEFT/RIGHT/DOWN/READING pass. During READING, read normally across the actual quiz question and options, including its leftmost text and lower answer lines. This is needed to check the new DOWN region against ordinary lower-screen reading as well as the unresolved LEFT confusion.

If calibration still fails, leave it failed and run debug validation as before; do not lower the floor. Export to a new filename, retaining this original file for comparison. All predictions remain DEBUG / UNVALIDATED. The minimum next evidence is one completely new five-target pass; further tuning must not reuse this already-inspected pass as independent validation.

**Current status:** the uploaded human pass shows a repeatable eye signal but inadequate classification. The patch addresses one specific DOWN defect. Post-patch human accuracy and reading safety are pending a new operator run; LEFT/reading overlap remains unresolved.
