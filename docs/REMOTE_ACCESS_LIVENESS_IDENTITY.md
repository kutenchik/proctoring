# Optional remote access, liveness and face consistency

Source implementation and automated validation, 2026-10-15. Localhost only.
This is an experimental review aid, not an academic misconduct decision or legal identity service.

## Inventory and scope

| Capability | Before this change | Current implementation / verification |
|---|---|---|
| VM, display and clipboard checks | EXISTING | Preserved; these are not remote-control detection |
| Windows remote application/session observations | MISSING | Implemented with Toolhelp/WTS; mocked observations tested, physical coverage UNVERIFIED |
| Geometric face consistency | EXISTING | MediaPipe landmark Procrustes comparison, independent of new biometric matching |
| Primary face selection | PARTIAL | Existing single-face/pose/landmark gate reused; second detector must agree on face region |
| Passive liveness | MISSING | Actual DeepFace MiniFASNet outputs; synthetic runtime and decision tests passed; real attack accuracy UNVERIFIED |
| Trained face embeddings | MISSING | Facenet512 local enrollment/cosine comparison; generated-array runtime and mocked vector tests passed; real matching accuracy UNVERIFIED |
| Consent | EXISTING v3 | Conditional v4 for any new capability; v3 remains valid only for old monitoring |
| Teacher catalog/profiles | EXISTING schema 1 | Schema 2, explicit migration with new capabilities disabled |
| Active liveness challenge | MISSING | NOT IMPLEMENTED |

No age, ethnicity, gender, emotion, institutional identity lookup, external face API, separate webcam stream, program termination or remote-session disconnection is implemented.

## Remote access coverage

`advanced/remote.py` uses Windows Toolhelp process-name snapshots and `WTSQuerySessionInformationW` for the current session's protocol and connection state. The APIs run with ordinary user privileges. Only exact case-insensitive basenames are matched:

| Category | Signatures |
|---|---|
| AnyDesk | `anydesk.exe` |
| TeamViewer | `teamviewer.exe`, `teamviewer_service.exe` |
| RustDesk | `rustdesk.exe` |
| Chrome Remote Desktop | `remoting_host.exe` |
| Quick Assist | `quickassist.exe` |
| RDP client | `mstsc.exe` |
| Current RDP session | WTS protocol 2 **and** active connection state |

Running processes produce `process_running / active_control: unverified`. The current active RDP signal produces `active_session / os_verified`. Three repeated observations at the default five-second interval create `remote_access_detected`. Persistence is per matched category/state, with no accumulation across gaps. A single episode is updated rather than recreated each poll; clear observations close it and later reappearance creates a new ID.

After consent, a one-time bounded uninstall-registry lookup recognizes exact product display names. An installed-only match never activates an event. Incomplete process enumeration yields `installed_running_unknown`, not `installed_not_running`. Registry coverage is incomplete, especially for portable/UWP/per-user variants. A missing registry entry is never reported as proof of absence. Continuous polling retains only matched categories, not the process list, executable paths, users, IP addresses or PIDs. Installation-only matches are not uploaded as accusations.

Renamed processes, other tools, browser-based tools, other Windows sessions and the actual control state of third-party applications are blind spots. Empty complete observations still carry `not_proof_of_absence: true`. Partial/unavailable observations cannot establish absence. Neither installation nor a running process proves misconduct.

Primary references: [Toolhelp snapshot](https://learn.microsoft.com/en-us/windows/win32/toolhelp/taking-a-snapshot-and-viewing-processes), [WTS query](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/nf-wtsapi32-wtsquerysessioninformationw), [WTS information classes](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ne-wtsapi32-wts_info_class).

## Optional runtime and model preparation

See [pinned feasibility research](DEEPFACE_FEASIBILITY.md) for upstream API, license and artifact sources. DeepFace **0.0.102** supports an ONNX path without TensorFlow/Keras or PyTorch. The working student `.venv` was not modified. A separate `.venv-face` was created and tested on Windows 10, Python 3.11.5. Exact installed dependencies are recorded in `requirements-face.lock.txt`. Runtime checks require DeepFace 0.0.102, ONNX Runtime 1.31.0, NumPy 2.4.6 and opencv-contrib-python-headless 5.0.0.93.

Only **Facenet512** is approved in this implementation. ArcFace was researched but is not exposed: its referenced pretrained-model rights need separate clearance. DeepFace wrapper and referenced Facenet source are MIT; MiniFASNet source is Apache-2.0. Those code licenses must not be treated as blanket clearance of all training data or converted weights. Retain upstream notices and review model-specific distribution rights before deployment/packaging; neither is performed here.

Deliberate preparation from the repository root (PowerShell):

```powershell
.venv/Scripts/python.exe -m venv .venv-face
.venv-face/Scripts/python.exe -m pip install --index-url https://pypi.org/simple -r requirements-face.lock.txt
.venv-face/Scripts/python.exe src/proctoring/advanced/resources.py --prepare build/advanced-face
```

The preparer also prepares official OpenCV 4.9.0 [face](https://github.com/opencv/opencv/blob/4.9.0/data/haarcascades/haarcascade_frontalface_default.xml) and [eye](https://github.com/opencv/opencv/blob/4.9.0/data/haarcascades/haarcascade_eye.xml) cascade XMLs. Their SHA-256 pins were computed from these versioned upstream source bytes. OpenCV 5 wheels omit them; without them the offline guard correctly rejects the first detector use. Both cascades are now hash-verified and loaded before readiness, with their embedded Intel/OpenCV license notices retained.

The preparer downloads official Hugging Face ONNX artifacts at immutable revision `d1783fe36379546024d548c77e23600a02ce1696`, verifies their upstream LFS SHA-256 values and only then promotes temporary files. Existing mismatched files are rejected, not overwritten silently. It is never called by exam startup.

| Model file | SHA-256 |
|---|---|
| `facenet512_weights.onnx` | `a7a4fbcc6af3175f5c4e91de0b92b4fa387e0e9f141efd59616337220363da33` |
| `2.7_80x80_MiniFASNetV2.onnx` | `2e0b0bdcdaf2ed0e8ceae7a8588a8b029c0f1bf2b15876eee942b68ce51bbb29` |
| `4_0_0_80x80_MiniFASNetV1SE.onnx` | `1e2645be6e42759714f19ee23641366cf3d86cba5f169964880894a1fc188275` |
| `haarcascade_frontalface_default.xml` (OpenCV 4.9.0) | `0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0` |
| `haarcascade_eye.xml` (OpenCV 4.9.0) | `71cc64fc305a355dc60067880f6fbbd43dd155bd63ee3844661a1bda34b2fd8c` |

Configure the source launcher environment before launching the student app, when separately authorized:

```powershell
$env:PROCTOR_FACE_PYTHON=(Resolve-Path .venv-face/Scripts/python.exe).Path
$env:PROCTOR_FACE_RESOURCES=(Resolve-Path build/advanced-face).Path
```

No student app was launched for this task. These are host settings, not teacher-editable paths. A required feature with missing resources/runtime remains blocked at readiness. Each ONNX load re-verifies its file hash. The worker forces ONNX/CPU, two intra-op threads and one inter-op thread; OpenCV uses one thread. Upstream download functions and socket connection functions are disabled in this dedicated worker. No models download when starting an exam.

## Liveness and enrollment semantics

Frames come from the existing authorized MediaPipe camera pipeline. The existing face-quality gate requires a single forward-facing, fully contained face with usable landmarks; the optional worker adds minimum crop size, brightness and sharpness checks. DeepFace `extract_faces(..., detector_backend='opencv', enforce_detection=True, anti_spoofing=True)` is used when liveness is requested. Exactly one DeepFace face must agree spatially with the existing primary face (IoU at least 0.4); background faces are not arbitrarily selected.

In the pinned release `antispoof_score` is the **winning class's confidence**, not always the probability of a real person. Only a finite score at least 0.8 with an actual boolean `is_real` is accepted as a decisive observation. `is_real=False` means suspected spoof; `True` means a passed observation. Otherwise the state is inconclusive. Three independent suspected observations at the default ten-second interval activate `presentation_attack_suspected`. Inconclusive, missing, ambiguous, low-quality and unavailable observations break the streak and are never labeled passed. This passive model cannot reliably exclude every printed photograph, screen replay, video replay or deepfake. No active randomized challenge is implemented.

The existing Capture reference action requests advanced enrollment as well as geometric enrollment when each is enabled. If liveness is enabled, repeated successful liveness observations are required before requesting the final enrollment frame, and that frame must itself pass liveness. Enrollment and comparison both use the same aligned detected face, Facenet512 representation (`normalization='base'`) and cosine distance after L2 normalization. The upstream default distance threshold is 0.30; the supported teacher range is 0.20–0.40. This range is not an empirically calibrated guarantee.

The worker retains one immutable 512-element reference in RAM bound to the exact connected session and attempt. Face disappearance/ambiguity never replaces it. A subsequent different face must produce repeated suitable comparisons before `identity_mismatch_suspected`; the default is three at thirty-second intervals. A passed geometric check cannot stand in for advanced enrollment. Matching only compares with the enrolled face; it does not verify legal/institutional identity. Liveness is also checked on identity-comparison frames when configured, even if its ordinary periodic sample is not due.

## Lifecycle, privacy and evidence

The optional process receives bounded JPEG messages derived from existing frames (at most 640×480). It has one pending input, one result slot, one in-flight request and a maximum accepted source frame size of 32 MB. There is no DeepFace webcam stream. Encoding, hashing, loading and inference happen off the controller/camera thread; the camera thread only gates and enqueues a bounded copy. Process pipes are drained by dedicated threads. Initialization has a 20-second deadline, individual requests five seconds, and results older than five seconds or from another session/generation/sequence are rejected. A worker crash becomes visible unavailable status. An independent cleanup thread can terminate a stuck owned process without waiting on the UI. A Windows parent process handle causes the optional worker to exit if its parent dies, without PID-reuse ambiguity.

Protection release remains first in terminal cleanup. The face worker cannot access input hooks, proctor PINs or protection commands. Optional checks do not auto-fail, terminate or pause the exam. Worker health is shown in the student interface and recorded as local optional-monitor status changes; existing teacher commands/timer/synchronization remain independent. Failure recovery is deliberate; no replacement reference is silently enrolled.

Embeddings never leave worker memory and never enter output JSON, server storage, logs or evidence. Worker exit erases its process memory. Advanced-only enrollment saves no reference image. Existing optional geometric reference storage and its established retention remain independent. **Advanced identity attempts cannot resume after a process restart with a lost reference.** A teacher-authorized replacement attempt is required; readiness/start recovery fails closed. This avoids enrolling a replacement person into an existing attempt. No new persistent biometric store was added.

Review events reuse the authoritative EventEngine, session journal, evidence queue and teacher review path. New IDs include a per-worker nonce to prevent collisions with prior-process events. Activated face events use the actual sampled source frame for the permitted snapshot, rather than a later camera frame. Details preserve model/version/resource revision, metric, threshold/distance, winning-class score, confirmation policy and observation time. There are no raw embeddings or full process inventories. Unknown observations interrupt evidence continuity without fabricating a pass. Existing IDs and snapshots remain intact. Events do not add automatic trust-score penalties; teachers review the uncertainty and students may contest it.

## Policy, consent and translations

Catalog schema **2** has 33 fields. Strict version-1 migration requires all 22 original keys, preserves their values and adds only disabled optional capabilities/default parameters. Stored old profiles and exam snapshots are not rewritten merely by reading; effective views are canonicalized explicitly. New exams freeze the full schema-2 policy. The three switches are independent Basic controls. All new fields are fixed before setup; live enabling/disabling is not supported.

| Key prefix `advanced.` | Default | Allowed |
|---|---|---|
| `remote_enabled` | false | boolean |
| `remote_interval_seconds` | 5 | 5–60 s |
| `remote_confirmations` | 3 | integer 2–10 |
| `liveness_enabled` | false | boolean |
| `liveness_interval_seconds` | 10 | 5–60 s |
| `liveness_confirmations` | 3 | integer 3–10 |
| `identity_enabled` | false | boolean |
| `identity_model` | Facenet512 | single approved choice; verified local resources required |
| `identity_interval_seconds` | 30 | 5–300 s |
| `identity_confirmations` | 3 | integer 3–10 |
| `facenet_cosine_threshold` | 0.30 | 0.20–0.40 |

Descriptors, helper text, new student status labels and canonical teacher/student event labels have EN/RU/KK translations. The server-driven catalog is the mapping authority, using the existing warm-neutral/green Configurations editor. Numeric confirmation counts are validated as integers on the server and Python boundary.

Consent v4 explicitly discloses each enabled capability. The student device consent **and** acknowledged policy-specific v4 consent are required before optional monitoring starts. Existing consent v3 cannot authorize it. Python workflow, live consent transport, server start authorization, viewer access and early snapshot upload compare the required version. A missing live-consent row blocks new-feature start authorization. Old exams without new features continue using v3. The consent UI states that these are contestable review signals and that embeddings remain local.

## Automated verification and benchmark

The optional Windows dependency resolver, isolated install, import, all five resource hash checks and real ONNX model loads passed. Reproducible generated-array timing:

```powershell
.venv-face/Scripts/python.exe scripts/benchmark_optional_face.py build/advanced-face build/advanced-face/benchmark-final.json
```

Measured on this Windows 10 / Intel family 6 model 141 host, Python 3.11.5: initialization 0.77 s; six combined direct MiniFASNet + Facenet512 calls 16.5–18.9 ms wall time, 62.5–125 ms process CPU time; peak working set 268.3 MiB. At ten-second sampling the measured model CPU work averages roughly 0.6–1.3% of one CPU core. These generated-array calls bypass face detection and exclude camera, IPC, encoding and live workload contention. They prove runtime feasibility, **not accuracy, total pipeline latency or a performance guarantee on another PC**. The benchmark contains no person images or vectors.

Focused coverage includes explicit signatures, installed-only/no-event, active RDP, unknown observations, deduplication/reappearance, face match/replacement after absence, immutable reference, ambiguous/low-quality faces, liveness score semantics, stale generations, no embedding output, disabled features, missing resources, slow/crashed workers, ordinary owned-process exit, Windows parent-handle death cleanup, corrupt/missing detector-resource rejection, protection-release ordering, old-policy migration, consent v4, saved profile/exam freezing and EN/RU/KK descriptors. The browser configuration test exercises all three switches, model selection, mismatch count persistence and full frozen policy equality.

Validation results: 73 targeted student/policy/live-workflow/API tests passed; 50 targeted teacher configuration/live tests passed; one configuration browser scenario passed with CRUD, guards, frozen settings, locales and responsive screenshots. Student and teacher source builds passed. Existing build warnings concern Vite configuration compatibility/chunk size; the server test warning concerns Starlette/httpx deprecation.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_advanced_monitoring.py tests/test_exam_policy.py tests/test_exam_policy_api.py tests/test_connected_stage3.py -q
.venv-server/Scripts/python.exe -m pytest tests/teacher_server/test_configuration.py tests/teacher_server/test_live.py --confcutdir=tests/teacher_server -q
# From teacher-web:
npx playwright test --config playwright.configuration.config.ts
# From desktop and teacher-web respectively:
npm run build
```
 Final read-only cleanup verification found zero remaining optional test workers and zero listeners on temporary test ports 8019/5179. Source builds only; no full suite, packaging, real webcam/microphone, native audit, shortcut suppression, protected exam, public tunnel or load test was run. Old protection audits do not match these changed sources/builds; the fingerprint includes the new optional modules.

## Separately gated physical plan (not executed)

With explicit fresh approval: choose a consenting adult and a prepared unprotected local test attempt, disclose v4, confirm one camera pipeline, establish quality and enrollment, then test original face, absence/reappearance and a separately consenting replacement. Independently test printed/photo-screen/video replay conditions and record both false positives and misses across lighting and glasses. Check teacher event details and original snapshots, stable IDs, timer responsiveness, missing/slow-worker status, normal submission and device/process cleanup. Use mock remote observations first; actual product coverage testing needs a controlled local environment. No claim of attack resistance or matching accuracy precedes that work. Protected validation needs its own newly matching audits and explicit authorization.
