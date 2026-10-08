# Eye visibility and calibration gate: short operator check

The oval is unchanged. This update does not relax eye validity, alter the pixel uncertainty gate, or replace eye gaze with head pose. See [GAZE_GATE_INVESTIGATION.md](GAZE_GATE_INVESTIGATION.md) for the separate numerical investigation and the limits of the older saved export.

## What the code establishes

An eye with eyelid aperture / corner width below **0.10** is rejected even when finite iris landmarks exist. The measured quality is `min(1, left opening / .22, right opening / .22)`; the **0.45** quality minimum corresponds to **0.099** aperture, so the 0.10 aperture safeguard is slightly stricter. Alignment also requires both valid eyes, source eye widths at least 32 px, and its existing 0.75 s / three-capture stability interval. Invalid eyes reset that interval; reopening does not immediately restore collection readiness.

These rules can reject sustained downward narrowing. They do not prove that rejected iris positions were observable or correct. The previous wording combined closed and narrow eyes; it now says **low eyelid aperture; iris visibility unverified**. Thresholds and the rejected set are unchanged. Missing eyes do not turn a present face into an absent face, turn a working pipeline into a failure, or supply a CENTER/DOWN estimate.

The new optional view uses each face result's **matching original source frame**, retained atomically with the landmarks/capture time in debug mode. A newer camera frame is never substituted. Two crops show corner/upper/lower lid anchors in amber and iris center/ring in green, with per-eye openness, original eye width in pixels, and rejection reasons. Markers can be visually wrong even when numerical geometry passes; that status explicitly does not verify iris visibility. No automatic glasses/glare detection is implemented.

The short temporal description measures a continuous low-aperture episode from unique capture timestamps. Repeated UI polls do not add time. Stale/future/nonfinite/missing pairs, timestamp regression or a gap longer than 0.5 s clear history. Short and sustained episodes can be compared, but neither duration nor predicted landmarks alone distinguishes a blink, true closure, occlusion or downward gaze. No temporal observation admits a rejected sample or assigns a gaze direction.

Crops clear when disabled, the panel closes, data is stale (0.5 s maximum age), a pair is unavailable, monitoring fails, or an exam starts. They are live in memory only. No image/video save path was added. Existing numerical export remains explicit and excludes frames and overlay geometry. Exam UI now shows **Gaze availability reduced** with the available quality reason while independently functioning detectors remain healthy.

## One short repeatable comparison

1. Run from the repository root, with the supplied safe default configuration:

   ```powershell
   .\.venv\Scripts\python.exe -m proctoring --calibration-debug
   ```

   Open the camera, expand **Developer calibration diagnostics**, then check **Show live eye close-ups (inspection only; never saved)**. Scroll the setup panel if needed. Neither successful calibration nor an exam is required for the view.

2. Keep lighting, seat and comfortable fixed targets consistent. With your normal corrective glasses first, do **CENTER → RIGHT → CENTER → DOWN → CENTER → normal question-and-options reading**, about 3 seconds each. Use comfortable eyes-only targets, not extreme rotation; small natural head motion is acceptable and remains a separate displayed measurement. Follow with ordinary blinks and a brief deliberate closure, then reopen and return CENTER. An operator can observe the close-ups while you hold the targets. For a first visual comparison, use a question/options at the usual quiz position beside the preview; the separate validation below displays the actual quiz area.

3. Note four things at each step: whether each iris is visibly exposed, whether the cross/ring follows it rather than a reflection or eyelid, the two openness values/reasons, and whether the low-aperture duration is momentary or sustained. On deliberate closure the gaze should be unavailable, not DOWN/CENTER. If it remains numerically valid while visibly wrong, report that exact observation; do not interpret numerical validity as success. After reopening, distinguish immediate gaze measurement recovery from the additional 0.75 s alignment hold.

4. Collect a **fresh four-target calibration attempt**, even if it fails. Select that retained attempt, run **Start separate validation**, and complete its newly measured CENTER/LEFT/RIGHT/DOWN/READING windows. This is a separate collection, not reusing calibration frames. It runs in DEBUG / UNVALIDATED mode after a rejected fit and cannot enable the exam or create review events. Enable numerical export explicitly and save a new filename such as `glasses-fresh-with-validation.json`. Include the visual notes from step 3. The close-up panel remains on setup; actual quiz-area reading temporarily displays the existing diagnostic quiz page and returns afterward.

5. Only if comfortable, repeat with glasses removed, using **Retry all targets (new baseline)** and a different filename. Removing necessary corrective glasses is not a proposed product solution. Keep conditions consistent and identify eyewear in the filenames/notes; it is not automatically detected.

The exact missing evidence is a new export matching the current 0.0785/0.0900 and 0.0734/0.0865 failures, plus observation of iris exposure/marker placement at the moment low openness is rejected. Without those, the dominant assumed pixel term is known from the messages, but its conservatism relative to current repeatability and independent reading errors is unknown. Existing exports already contain the needed numerical gate fields; no extra gate-diagnostics framework was added.

If those observations justify an admission or uncertainty correction, select the change using that collection, then perform **another fresh calibration and separate validation pass** to evaluate it. A replay or passing unit tests cannot establish human gaze performance.

## Files changed for this investigation

- `vision/types.py`, `vision/face.py`: transient eye overlay coordinates and precise low-aperture wording.
- `vision/monitor.py`: debug-only matching face/frame pairing; event observations/evidence delivery unchanged.
- `ui/eye_closeups.py`, `ui/calibration.py`: opt-in live inspection in the existing developer panel.
- `ui/window.py`: explicit reduced gaze availability and clearing inspection images at exam start.
- Regression tests cover source pairing, stale/missing clearing, fractional crop/marker mapping, aperture history, closed/narrow admission, disabled calibration, numerical-only export, and healthy phone/person monitoring with UNKNOWN gaze.

No changes were made in this task to the oval, positioning thresholds, calibration gate, gaze classifier, YOLO detector, face-absence mapping, event thresholds/hysteresis, timer/recovery, Windows protection or emergency release. Real restrictions remain disabled. Human validation of this update is pending.

## Verification

- Full automated suite: `python -m pytest -q` — **820 passed in 10.12 s**.
- Native Windows application startup completed with protection inactive, calibration not ready, and exam start disabled.
- Native developer-panel layout was inspected using synthetic eye drawings; both close-ups and markers rendered correctly. This check opened no webcam and started no exam.
- Human gaze validation, including eyes-only DOWN with glasses, remains **pending**. These checks do not establish gaze accuracy.
