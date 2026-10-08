# Pixel-gate and eye-validity evidence, 2026-10-06

The current reported failures and the saved operator export are **different attempts**. No fresh numerical export matching the latest failures is present. This investigation does not justify changing the calibration gate or accepting a failed calibration. It also does not establish that a passing gate would give reliable gaze classifications.

## Current reported failures

| Pair | Reported 2D separation | Required | Shortfall | Reported dominant term |
|---|---:|---:|---:|---|
| CENTER–RIGHT | 0.0785 | 0.0900 | 0.0115 | Assumed pixel floor |
| CENTER–DOWN | 0.0734 | 0.0865 | 0.0131 | Assumed pixel floor |

The reported DOWN vertical separation is 0.0611. These are rounded user-reported values, not independently reconstructed raw measurements. The diagnostics identify which gate wins, but these summary numbers do not supply target spreads, rejection counts, eye-size distributions, or separate validation results. They cannot establish whether currently accepted samples are repeatable or whether the assumed floor is excessively conservative for this attempt.

With unchanged defaults, the constant contribution is 0.0300. A dominant pixel threshold of 0.0900 or 0.0865 corresponds to an effective reciprocal-width value of approximately 33.33 or 34.68 source pixels (`3 / threshold`). These are **conditional inverse calculations**, not measured eye widths or camera resolution. The actual calculation uses the larger target's p90 supplied reciprocal width, not a median eye width. No source dimensions or measured spread can be recovered from these messages.

## Existing operator file: historical evidence only

Both `gaze-failed-attempt.json` and `gaze-failed-attempt-with-validation.json` contain exactly the same training attempt. Their last-write times are 2026-10-05 13:13 and 13:15 local time; more decisively, their numerical failures differ from the current report. The latter file's SHA-256 is `d036a0fe8f04ebec4f2828da6ef6fa2a2c06e7ab00f7976c03aef51d3e75600e`. The training cutoff is monotonic time 508580.593; it is not a calendar timestamp. No eyewear condition is recorded, so this cannot be called either the current glasses or no-glasses attempt.

Every recorded training frame was 640×480. The historical CENTER–RIGHT separation is **0.111530**, and passed. Historical CENTER–DOWN is **0.079398**, with vertical separation **0.070283**, and failed. These do not match the current 0.0785 / 0.0734 / 0.0611 values.

| Historical pair | 2D separation | Constant term | Pixel term | Radial spread × 2.5 | Dominant term |
|---|---:|---:|---:|---:|---|
| CENTER–LEFT | 0.105661 | 0.030000 | 0.090035 | 0.053368 | Pixel |
| CENTER–RIGHT | 0.111530 | 0.030000 | 0.090035 | 0.053368 | Pixel |
| CENTER–DOWN | 0.079398 | 0.030000 | 0.090035 | 0.056452 | Pixel |
| LEFT–RIGHT | 0.215967 | 0.030000 | 0.089060 | 0.038215 | Pixel |
| LEFT–DOWN | 0.094529 | 0.030000 | 0.089060 | 0.056452 | Pixel |
| RIGHT–DOWN | 0.155979 | 0.030000 | 0.086955 | 0.056452 | Pixel |

All terms have normalized eye-width units. The production metric is 2D Euclidean distance between two-eye mean horizontal/vertical references. The reciprocal-pixel term is an assumed **scalar radial safeguard**, not an independently measured localization standard deviation and not integer rounding. Source-frame landmark calculations retain floating-point coordinates. The current 1D diagnostics reuse that scalar safeguard; they do not supply a measured per-axis uncertainty estimate.

For historical CENTER–DOWN, the vertical spread contribution alone is **0.024439**, smaller than both the pixel term and the combined radial spread term. DOWN's horizontal variation contributed 98.896% of squared displacement in its radial p90 tail. This unrelated-axis variation affected spread but did **not** determine rejection: the pixel term remained dominant. That evidence identifies a conservative assumption relative to observed training variability, but does not determine a safe replacement for current measurements.

Historical relevant-axis movements were repeatable across the two separate passes:

| Target axis, relative to that pass's CENTER | Training displacement | Separate-pass displacement |
|---|---:|---:|
| LEFT horizontal | +0.105531 | +0.141748 |
| RIGHT horizontal | −0.110053 | −0.113947 |
| DOWN vertical | +0.070283 | +0.063553 |

Each relevant-axis central 80% interval was disjoint from CENTER in each pass. These short correlated windows demonstrate directional signal in that collection, not broad accuracy or repeatability with glasses.

## Historical eye-validity evidence is separate

There were 105 accepted training samples. The 81 rejected deliveries were 77 captures before the collection window and four arrivals after it; **none were an eye-validity rejection**. All 134 separate validation measurements were valid according to the then-current rules. Historical DOWN had left/right median normalized openness **0.179965 / 0.167989**, versus CENTER **0.334728 / 0.312934**. Accepted DOWN minima were **0.151670 / 0.110713**. Separate DOWN validation minima were **0.148051 / 0.135379**.

Thus the old pass contains natural narrowing that was admitted, not measurements of the currently reported almost-closed-eye failure. It contains no labeled deliberate closure, labeled blink sequence, eyewear condition, or matching visual inspection of iris placement. It cannot justify globally relaxing eye validity or equating predicted landmarks with observed irises. Narrowing, true closure, occlusion and glare remain distinct hypotheses for the new failures.

## Historical separate validation is not current validation

The first validation capture occurred 95.828 seconds after the last recorded training measurement. The table reproduces predictions **stored in the file**, using the original point-core classifier before the existing bounded-DOWN correction:

| Operator target | Correct label | Incorrect label | UNKNOWN | Invalid measurements |
|---|---:|---:|---:|---:|
| CENTER | 26/26 (100%) | 0 | 0 | 0 |
| LEFT | 19/27 (70.37%) | 0 | 8/27 (29.63%) | 0 |
| RIGHT | 27/27 (100%) | 0 | 0 | 0 |
| DOWN | 2/27 (7.41%) | 0 | 25/27 (92.59%) | 0 |
| Normal READING, expected CENTER | 8/27 (29.63%) | 13/27 LEFT (48.15%) | 6/27 (22.22%) | 0 |

Overall UNKNOWN was 39/134 (29.10%); UNKNOWN is not correct. All UNKNOWN reasons were `outside_reference_core`, not invalid eyes or a head-pose veto. The existing bounded-DOWN change was chosen using this data; its development replay is documented in `GAZE_OPERATOR_ANALYSIS.md` and must not be called new human validation. The stored reading false-offscreen rate is already sufficient reason not to equate a looser acceptance gate with usable classification. There is no new independent validation result for the current report.

## Exactly what is still needed

For the **current gate**, export a new attempt whose recorded CENTER–RIGHT/DOWN separations match the displayed failure, together with a subsequent independent validation pass. Existing fields already cover source dimensions, per-eye horizontal/vertical/opening/width, validity and reason, sample time, combined features, accepted/rejected records, head pose, gate decomposition and held-out predictions. No new gate-diagnostics format is required.

For **current eye validity**, observe the live eye close-ups against natural DOWN, ordinary blinks and a brief intentional closure. The specific missing observation is whether each iris is visibly exposed and correctly tracked when the numerical low-openness/invalid reason appears, including how long the narrowing persists and whether readings recover immediately on reopening. Landmark existence alone cannot answer that. The close-ups need not be saved.

Use distinct filenames or accompanying operator notes to identify **with glasses** versus **without glasses, only if comfortable**, with fresh baseline calibration per condition. Keep seating/lighting/targets fixed. Without eyewear notes the two conditions cannot be compared reliably; this is operator-supplied context, not automatic glasses/glare detection. The developer-panel sequence `CENTER → RIGHT → CENTER → DOWN → CENTER → normal reading`, then ordinary blinks and a brief deliberate closure, provides a short visual check. Use the existing separate numerical validation sequence for quantitative target/reading rates. Any correction selected from these observations needs another new pass afterward, not replay of its selection data.

No calibration uncertainty setting or classifier was changed by this investigation. No human validation of the current build has been performed by the agent. Required corrective glasses are not a product defect or a proposed workaround; gaze must remain explicitly unavailable when eye evidence is insufficient, while independently functioning monitoring continues.
