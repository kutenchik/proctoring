# Head-down posture assistance

The live vision result now retains two distinct signals:

- `gaze_direction`: the existing calibrated iris/aperture classifier. Occluded,
  closed or unreliable eyes still return `UNKNOWN`.
- `head_down`: an independent posture heuristic. With accepted session
  calibration, a present face and a finite current head transform, it becomes
  true when `14 < pitch < 90` degrees, `abs(yaw) <= 15` degrees and
  `abs(roll) <= 12` degrees. It does not require observable irises.

The observation mapper merges either calibrated eye DOWN or `head_down` into
the existing `gaze_down` review condition. Head-down takes precedence over a
conflicting eye direction. Head-only evidence has no fabricated confidence
score. The live panel explicitly displays the posture cue alongside the eye
estimate, including when the latter is UNKNOWN. This is a review heuristic,
not proof of a phone, notes, or misconduct.

`[vision]` settings are `head_down_pitch_degrees`,
`head_down_max_yaw_degrees`, and `head_down_max_roll_degrees`. Each must be
positive, finite and below 90 degrees. The shipped `[events].gaze_deviation`
was 1.0 seconds and is restored to the requested 3.0 seconds; this existing
shared setting applies to LEFT, RIGHT and DOWN. Clearing remains 0.75 seconds.
No new accumulator or event type is introduced. Sustained detections retain
one active event and the existing snapshot policy.

The alignment `max_pitch_degrees = 15` only controls calibration positioning;
it is not the live exam veto. That gate, the oval and calibration fit remain
unchanged. The eye classifier's pose coverage checks also remain in place;
they cannot suppress the independent posture cue after successful calibration.
Failed/reset calibration does not activate the posture cue or enable an exam.
Missing face, invalid pose, lateral/rolled pose and upward pitch do not activate
it. Existing fresh-frame, monitoring failure and recovery checks are unchanged.

## Angle convention and limits

The existing transform extractor uses `atan2(R[2,1], R[2,2])` for pitch.
MediaPipe's metric camera uses upward Y: see its
[geometry conversion](https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/mediapipe/modules/face_geometry/libs/geometry_pipeline.cc)
and [canonical face mesh](https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/mediapipe/modules/face_geometry/data/canonical_face_model.obj).
Positive X rotation turns the face's forward +Z normal toward -Y, hence positive
pitch means downward. A synthetic rotation test verifies the implementation's
sign; it does not establish camera accuracy. The threshold uses absolute
camera-relative pitch, not a learned neutral offset, so camera mounting and
natural posture can affect false alerts.

The earlier supplied JSON trials did not contain a labeled sustained >14-degree
head-down test. They therefore cannot validate this path. No fresh human gaze
or posture validation has been performed as part of this patch.

## Short operator check

Keep real Windows restrictions disabled. Launch `python -m proctoring`, register,
and complete normal calibration with a comfortable forward-facing head. Do not
bypass failed calibration. Start a test exam, then:

1. Read the quiz normally, blink, squint, and briefly close your eyes with a
   frontal head. Eye gaze may become UNKNOWN; no head-down cue should appear.
2. Look down at the desk, naturally tilting the head. Check that displayed pitch
   increases beyond 14 degrees while yaw/roll stay within 15/12 degrees. Hold
   for at least 3 seconds. The panel should show the posture cue even if eye
   gaze is UNKNOWN, and one `gaze_down` review event should activate.
3. Continue for several seconds: the same event should update without repeated
   activation snapshots. Return to normal reading for more than 0.75 seconds;
   the event should clear. The exam timer should continue throughout.
4. Repeat ordinary reading and the desk look a few times. Report any alert
   during normal reading, observed pitch/yaw/roll and whether the cue was
   sustained. An extremely lateral/rolled head is deliberately outside this
   fallback's supported range.

Actual camera performance and an appropriate threshold for its placement
remain subject to this separate operator check.
