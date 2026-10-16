# Teacher configuration and saved profiles

Implemented for localhost source workflows. This document describes the current implementation, not a new physical acceptance result. Previous native protection audits are not valid for this changed source/build. Obtain separate approval and a matching current-build audit before any protected physical validation.

## Catalog and supported controls

`src/proctoring/exam_policy.py` is the explicit authoritative allowlist. Its frozen `Field` descriptors define stable keys, Python mappings, type, bounds/step, unit, group/subgroup, Basic/Advanced placement, labels/descriptions in English/Russian/Kazakh, dependencies, input component and before-exam/live editability. The server sends this catalog; `teacher-web/src/Configuration.tsx` renders it without copying defaults into React. Booleans use checkboxes; numeric controls carry min/max/step and units. Existing exam-type and protection enums retain their established controls.

Default values come from the allowlisted values of `config/default.example.toml`, not its comments or the operator's private TOML. The five new behavioral enable flags default to true, preserving the original behavior. The TOML files themselves are unchanged. A new TOML key never becomes teacher-editable automatically. To add a field, explicitly register its mapping, translated metadata, bounds, dependency and runtime mode, implement its actual engine support, version/migrate saved documents as necessary, and extend focused tests. No new React component is needed for supported types. Other component types need explicit renderer and validator support.

Translation tests require EN/RU/KK labels and descriptions on every registered field. The UI falls back to English, then a neutral unavailable label; it does not display raw keys as labels. HTTP validation errors currently use readable English; field descriptions, actions, status labels and native browser range validation are localized. There is no generic JSON editor.

The top-level Configurations page owns profile management. A dedicated editor provides Basic/Advanced monitoring tabs, searchable advanced fields, dependency handling, reset icons for changed values and restore-all-defaults. Create Exam contains only a saved-profile selector and a compact four-setting summary alongside its existing title, source, schedule, duration, shuffle and protection controls. No unsaved profile draft or full override editor is exposed there. Registration (name, ID, group), camera, consent and host safety requirements are visibly fixed because connected admission/readiness require them. Arbitrary gaze calibration quality gates and device tuning are not offered as teacher controls.

## Profiles and immutable exam snapshots

The built-in `default` profile is immutable. Custom profiles belong to one authenticated teacher and are stored in SQLite. Create, save-as and duplicate create independent documents. Rename/edit uses Save profile, guarded by the profile's optimistic edit version; concurrent stale saves return 409. Delete only removes the owned profile. An exam contains a complete copy of its selected effective values, never a mutable reference to the profile. Editing a configuration shows unsaved changes and requires an explicit save; leaving the editor or closing/reloading the tab warns about discarding the draft. Create Exam selects only saved profiles. Deleting or changing a profile cannot change existing exams.

Each canonical policy is `{schema_version: 1, values: {...all registered fields...}}`. `profile.version` is a separate optimistic edit counter. Strict validation rejects unknown keys, missing fields, unsupported schema versions, non-finite numbers, booleans-as-numbers and out-of-range values. Older profile documents require an explicit migration; no silent filling or reinterpretation is performed. Future bounds/default changes must be accompanied by a deliberate compatibility decision/version migration. Saved complete values are never replaced by new defaults. The built-in Default represents the currently shipped supported defaults.

Migration `006_configuration_profiles.sql` adds owner-indexed `configuration_profiles` and command-linked `monitoring_policy_changes`. It does not rewrite old exam policies. Tests apply migrations only to fresh temporary databases; historical project databases and evidence were not migrated or modified during this work.

## API

All paths below are relative to `/api/v1`. Existing authentication, teacher ownership, origin and CSRF checks apply; mutations require CSRF. Foreign profiles/attempts return not-found rather than exposing their content.

| Method / path | Contract |
| --- | --- |
| GET `/configuration/catalog` | Version, descriptors, translated groups and current Default |
| GET `/configuration/profiles` | Default plus only the caller's profiles |
| GET `/configuration/profiles/{id}` | Owned profile or Default |
| POST `/configuration/profiles` | Exact `{name, policy}`; creates independent version 1 document |
| PUT `/configuration/profiles/{id}` | Exact `{name, policy, version}`; rename/update, increments version |
| DELETE `/configuration/profiles/{id}` | Owned custom profile only |
| POST `/exams` | Existing request plus optional `monitoring_policy`; complete validated policy is frozen |
| GET `/attempts/{id}/monitoring-policy` | Last acknowledged effective policy/revision and full old/new change history |
| POST `/attempts/{id}/commands` | Existing command endpoint; `type: monitoring_policy` with reason, patch, base_revision, revision |

Live command shape:

```json
{"request_id":"unique-request-id","type":"monitoring_policy","payload":{"reason":"Crowded classroom","base_revision":0,"revision":1,"patch":{"events.second_person.enabled":false}}}
```

Use the existing UUID request-id format (32 hexadecimal characters) in actual requests. Old/new canonical policy, revision, requesting teacher, timestamp, reason and command ID are committed with the command. Existing live command audit events retain sent/delivered/applied/rejected/unconfirmed transitions. Profile mutations also produce audit entries.

## Precedence and real enforcement

1. Load and validate the host TOML normally. Models, camera identifiers, paths, credentials, transport, storage and native protection guarantees stay host-owned.
2. Creating an exam freezes its question set and complete teacher policy. `audio_monitoring` and `save_snapshots` are derived from the canonical policy, keeping the existing consent/admission contract consistent.
3. Admission carries this versioned snapshot. Python validates it again and verifies that legacy audio/snapshot flags match. A narrow dataclass overlay changes only registered values; it never replaces the local configuration wholesale.
4. Apply before consent/device setup/start. Update event thresholds and disabled rules, vision/calibration references, geometric consistency settings, and construct the audio monitor with the admitted audio policy. Construction does not start capture. A disabled microphone rejects explicit start/calibrate requests as well as being excluded from controller monitoring.
5. The event engine filters disabled categories while shared YOLO/person/face processing continues. Disabling second-person does not disable phone, raised-phone or geometric processing. The gaze category controls down/left/right event rules together. Vision confidence/head angle changes are applied before workers initialize.
6. Snapshot policy gates future event images; existing images/events are retained. Audio measures energy, never verified speech. Its fallback energy threshold can be superseded by the existing local microphone check/manual sensitivity; adaptive calibration enables that check, not automatic capture or OS volume changes.
7. After an acknowledged live change the encrypted durable journal retains effective policy and revision with the command result. A resumed workflow restores that policy before setup. The original admitted snapshot remains unchanged for provenance.

Old exams without `monitoring_policy` follow the previous local-default plus frozen audio/snapshot behavior. They are explicitly labeled legacy and cannot receive new live monitoring-policy commands. No silent conversion of old exams or active attempts occurs. Exam creation remains the freeze boundary: editing an already-created exam's original settings was not introduced. To change pre-exam configuration, create another exam. Existing audited time-extension/repeat flows retain their own contracts.

## Active attempt rules

Live support is limited to five behavioral enable flags, their five durations, event clearing duration, disabling microphone monitoring, and disabling future snapshots. All other catalog fields are pre-exam only. Neither capture option can be enabled live. Native protection mode/recovery, readiness, camera/model paths, registration/exam identity, deadlines and historical evidence are outside the patch allowlist.

An owned, currently connected, consented, running/paused attempt is required. Revisions advance exactly by one, relative to the last acknowledged revision. Another policy command is blocked while the prior one is pending or its execution is unconfirmed. Commands are bound to attempt/session/connection and have the existing 10-second TTL. Offline requests are rejected, not queued; expired/old-generation delivery is rejected by Python. Request IDs retain existing idempotency/conflict behavior.

Every applied revision closes current event episodes with `policy_changed`, including unaffected categories, and discards incomplete candidates. This deliberate boundary prevents a single episode from mixing policies. Existing event IDs, prior records and images remain; new enabled observations create new episodes under the new thresholds. Audio episodes also close and adopt the new clearing duration. Turning audio off stops its monitor and detaches it from the controller.

Python first performs the mutation, writes lifecycle/audit data and persists its command result/effective revision, then sends an applied acknowledgement containing revision and canonical-policy hash. The server verifies both against the issued change. An accepted POST or delivered command never advances effective state. If persistence/transport fails after mutation, execution is unconfirmed rather than a fabricated success or rejection.

The attempt panel separates read-only effective settings from live adjustments, shows the last acknowledged revision, and lists reason/status/time/teacher and changed old/new values. **Refresh actual revision** retrieves the authoritative acknowledgement/history; this panel does not auto-refresh a teacher's draft. Existing live command history also receives status updates. While a result is unconfirmed the last confirmed policy is displayed alongside the unconfirmed status; the server cannot assert what the disconnected runtime currently uses. Automatic reconciliation/unblocking of an unconfirmed policy is deferred. Inspect the durable student result rather than force another revision. There is no batch/all-student adjustment: each attempt has its own policy/revision.

## Compatibility and limits

- Camera/reference/gaze calibration and protected-mode gates are not bypassed by turning off a behavioral warning.
- Optional geometric consistency remains a heuristic, not verified biometric identification.
- No raw audio recording, new surveillance channel, renewed-consent UI, arbitrary system tuning, protected-mode live toggle, profile sharing/import/export, or server-side old-profile migration is introduced.
- Saved profiles cover monitoring policy, not title, question source, schedule, duration or workstation protection selection. Those retain their existing independent controls and frozen contracts.
- Fresh source and matching server/student versions are required for the new schema. Old exams remain usable; older binaries are not claimed to enforce new policies.
- Native fingerprint inputs now include the policy/engine/connected enforcement sources and supported default-policy file. Old native audit reports remain historical evidence and must not authorize this changed build. No native audit, shortcut fixture or physical exam was run here.

## Focused verification

Run from repository root in PowerShell unless a subdirectory is indicated:

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
$env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -m pytest tests/test_exam_policy.py tests/test_exam_policy_api.py tests/test_connected_client.py tests/test_connected_workflow.py tests/test_connected_stage3.py -q --tb=short
.venv-server/Scripts/python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_configuration.py tests/teacher_server/test_live.py -q --tb=short
# teacher-web:
npx playwright test --config playwright.configuration.config.ts
npm run build
# desktop (build only, do not start):
npm run build
```

Results: the initial focused Python run passed 80 tests; the final policy-only rerun passed 23 (including one additional non-native fingerprint coverage test, 81 distinct Python tests overall). The isolated server run passed 48 tests, with all three configuration tests passing again after the same-timestamp revision check; one browser scenario passed in EN/RU/KK with responsive checks; teacher and desktop TypeScript/source builds passed. The full HTTP test creates a profile/exam, admits a mock-device Python workflow, verifies second-person filtering with phone detection still active, sends a real loopback live command and verifies the server's acknowledged effective revision. Other focused tests cover ranges/types/versions, ownership, restart persistence, immutable snapshots, capture disabling, consent, stale/expired commands, episode identity and legacy behavior. No full regression suite was run.

The browser scenario uses ports 5179/8019 and an isolated test database because an unrelated service already occupied 5174; that service was left alone. The mobile screenshot was inspected. Test servers/workers are torn down by their fixtures. Existing Vite configuration/chunk warnings and a Starlette TestClient deprecation remain non-fatal. An initial server command omitted `--confcutdir` and loaded the desktop conftest (numpy absent from the deliberately lean server environment); the documented isolated command passes. An initial catalog implementation also imported desktop settings and was corrected to read only allowlisted TOML values, keeping the server independent of CV/Qt.

## Deferred manual localhost checklist (requires separate authorization)

1. Use a fresh isolated database/output directory; retain historical evidence unchanged. Select Default, create a classroom profile, disable second-person and microphone, keep phone/gaze/snapshots enabled, and save it. Verify EN/RU/KK labels and the effective summary.
2. Reload/restart the local server, reuse the saved profile in Create Exam, create an exam, then edit the profile and verify the existing exam snapshot is unchanged. The normal creation UI no longer offers per-exam overrides; the backend contract remains compatible. Verify a different teacher cannot see the private profile.
3. Start with an explicitly authorized unprotected student session. Complete normal consent and applicable camera/reference/calibration gates. Confirm the microphone is not started by this policy. Verify actual event behavior and unchanged shared phone/gaze processing.
4. During the consented active attempt, apply a reasoned event change. Observe pending then refresh to acknowledged revision. Verify old evidence remains and new episodes use the new policy. Disable future snapshots/audio where initially enabled; confirm no live re-enable is allowed.
5. Verify a disconnected student is rejected for new changes and an old revision cannot be applied. Inspect unconfirmed state without automatically retrying or overwriting history.
6. Submit normally, verify sync/report history and device/process cleanup. Any future protected test first requires explicit approval, a fresh matching native recovery audit and the established protected fixture sequence. Do not reuse the old audit.

## Complete field inventory

The following tables enumerate every leaf in the shipped example plus every optional field accepted by the typed loader (including the optional connected section). No secret values are reproduced. Categories: **Before** = teacher-editable before creation; **Live** = before creation and the explicitly described active-attempt operation; **Host** = host/developer-only; **Secret** = secret/internal; **Safety** = safety-critical and immutable to teacher policy. A host operator may still configure Safety fields under the existing audited contracts. A teacher's protected/unprotected requirement is a separate frozen request and cannot change the host's native opt-in.

Inventory contains **115 TOML leaf fields**. Optional fields absent from the example are still listed.

### audio

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `audio.adaptive_calibration` | Before | `audio.adaptive_calibration`; freeze at creation; apply before setup |
| `audio.calibration_background_seconds` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.calibration_max_seconds` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.calibration_speech_seconds` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.enabled` | Live | `audio.enabled`; disable only while active |
| `audio.energy_threshold` | Before | `audio.energy_threshold`; freeze at creation; apply before setup |
| `audio.gain_smoothing_seconds` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.max_energy_threshold` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.max_gain` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.min_energy_threshold` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.sample_rate` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.speech_target_rms` | Host | Local device/calibration tuning; not in approved teacher subset |
| `audio.voice_duration_threshold` | Before | `audio.voice_duration_threshold`; freeze at creation; apply before setup |

### connected

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `connected.allow_loopback_http` | Host | Server/transport trust and local connection settings |
| `connected.enabled` | Host | Server/transport trust and local connection settings |
| `connected.server_url` | Host | Server/transport trust and local connection settings |
| `connected.timeout_seconds` | Host | Server/transport trust and local connection settings |

### events

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `events.clearing_seconds` | Live | `clearing_seconds`; versioned event adjustment |
| `events.face_absent` | Live | `events.face_absent.seconds`; versioned event adjustment |
| `events.gaze_deviation` | Live | `events.gaze_deviation.seconds`; versioned event adjustment |
| `events.phone_raised` | Live | `events.phone_raised.seconds`; versioned event adjustment |
| `events.phone_visible` | Live | `events.phone_visible.seconds`; versioned event adjustment |
| `events.second_person` | Live | `events.second_person.seconds`; versioned event adjustment |

### exam

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `exam.allowed_domains` | Safety | Derived from frozen external source in connected mode; no arbitrary teacher allowlist |
| `exam.duration_seconds` | Before | Existing exam duration; active changes only through audited add-time command |
| `exam.external_url` | Before | Existing validated external exam source; frozen at creation |
| `exam.identity.impersonation_threshold` | Before | `identity.impersonation_threshold`; freeze at creation; apply before setup |
| `exam.identity.periodic_check_interval_seconds` | Before | `identity.periodic_check_interval_seconds`; freeze at creation; apply before setup |
| `exam.identity.selfie_verification_enabled` | Before | `identity.selfie_verification_enabled`; freeze at creation; apply before setup |
| `exam.quiz_path` | Host | Local path; teacher selects an owned question library instead |
| `exam.registration.enabled` | Safety | Connected admission fixes registration and group as required |
| `exam.registration.require_group` | Safety | Connected admission fixes registration and group as required |

### monitoring

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `monitoring.recovery_seconds` | Safety | Monitoring outage/freshness gate |
| `monitoring.stale_seconds` | Safety | Monitoring outage/freshness gate |
| `monitoring.synthetic_interval_ms` | Host | Local synthetic/runtime setting |

### protection

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `protection.enabled` | Safety | Existing host recovery/security contract; no teacher override |
| `protection.foreground_poll_ms` | Safety | Existing host recovery/security contract; no teacher override |
| `protection.heartbeat_timeout_seconds` | Safety | Existing host recovery/security contract; no teacher override |
| `protection.startup_timeout_seconds` | Safety | Existing host recovery/security contract; no teacher override |
| `protection.validation_max_age_hours` | Safety | Existing host recovery/security contract; no teacher override |
| `protection.validation_report` | Safety | Existing host recovery/security contract; no teacher override |

### remote

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `remote.enabled` | Host | Operator-controlled optional remote delivery |
| `remote.max_queue_size` | Host | Operator-controlled optional remote delivery |
| `remote.telegram_bot_token` | Secret | Operator credential/destination; never teacher policy |
| `remote.telegram_chat_id` | Secret | Operator credential/destination; never teacher policy |
| `remote.telegram_enabled` | Host | Operator-controlled optional remote delivery |
| `remote.upload_timeout_seconds` | Host | Operator-controlled optional remote delivery |
| `remote.webhook_token` | Secret | Operator credential/destination; never teacher policy |
| `remote.webhook_url` | Secret | Operator credential/destination; never teacher policy |

### reporting

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `reporting.generate_pdf_report` | Host | Local report generation/output/delivery |
| `reporting.report_filename` | Host | Local report generation/output/delivery |
| `reporting.send_pdf_to_telegram` | Host | Local report generation/output/delivery |

### security

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `security.blocking_enabled` | Safety | Existing host recovery/security contract; no teacher override |
| `security.proctor_pin` | Secret | Operator credential/destination; never teacher policy |
| `security.system_checks.block_multimonitor` | Safety | Existing host recovery/security contract; no teacher override |
| `security.system_checks.clipboard_guard_enabled` | Safety | Existing host recovery/security contract; no teacher override |
| `security.system_checks.vm_check_enabled` | Safety | Existing host recovery/security contract; no teacher override |

### storage

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `storage.sessions_dir` | Host | Local evidence location |
| `storage.snapshots_enabled` | Live | `snapshots_enabled`; disable only while active |

### ui

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `ui.language` | Host | Local student interface preference; teacher UI language is independent |

### vision

| TOML field | Classification | Enforcement / rationale |
| --- | --- | --- |
| `vision.accessories.earphone_detection_enabled` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.accessories.min_ear_yaw_trigger` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.alignment.guide` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.max_center_drift` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.max_pitch_degrees` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.max_roll_degrees` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.max_sample_gap_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.max_scale_change` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.max_yaw_degrees` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.min_eye_width_pixels` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.min_face_height_pixels` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.min_face_width_pixels` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.min_quality` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.min_stable_samples` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.alignment.stable_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_center_radius_fraction` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_collection_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_debug` | Host | Diagnostics only |
| `vision.calibration_eye_noise_floor` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_max_collection_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_max_samples` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_max_spread` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_min_separation` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_min_signal_noise` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_offscreen_radius_fraction` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_pixel_uncertainty_multiplier` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_preparation_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.calibration_samples` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.camera_backend` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.camera_index` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.capture_fps` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.capture_height` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.capture_width` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.cpu_threads` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.face_fps` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.face_min_area` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.face_model` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.frame_stale_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.head_down_max_roll_degrees` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.head_down_max_yaw_degrees` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.head_down_pitch_degrees` | Before | `vision.head_down_pitch_degrees`; freeze at creation; apply before setup |
| `vision.heartbeat_stale_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.nms_iou` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.person_confidence` | Before | `vision.person_confidence`; freeze at creation; apply before setup |
| `vision.person_min_area` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.person_min_height` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.phone_confidence` | Before | `vision.phone_confidence`; freeze at creation; apply before setup |
| `vision.phone_min_area` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.prefer_gpu` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.raised_face_margin` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.raised_person_top_fraction` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.result_stale_seconds` | Safety | Calibrated validity/readiness/freshness gate; teacher tuning deferred |
| `vision.yolo_fps` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.yolo_input_size` | Host | Device/model/performance or unexposed vision heuristic |
| `vision.yolo_model` | Host | Device/model/performance or unexposed vision heuristic |

### Catalog-only event enable flags

The five `events.<category>.enabled` values are versioned policy fields, not newly accepted arbitrary TOML keys. They map to `AppConfig.event_rules`; absent rules mean enabled for compatibility. Each is Before + Live.

### Approved field labels and limits

| Stable key | English | Russian | Kazakh | Default | Range / unit | Active support |
| --- | --- | --- | --- | --- | --- | --- |
| `events.phone_visible.enabled` | Phone visible | Телефон в кадре | Телефон көрінеді | true | boolean | both |
| `events.phone_raised.enabled` | Phone raised near face | Телефон возле лица | Бетке жақын телефон | true | boolean | both |
| `events.second_person.enabled` | Second person | Второй человек | Екінші адам | true | boolean | both |
| `events.gaze_deviation.enabled` | Gaze deviation | Отклонение взгляда | Көзқарастың ауытқуы | true | boolean | both |
| `events.face_absent.enabled` | Face absent | Лицо отсутствует | Бет көрінбейді | true | boolean | both |
| `events.phone_visible.seconds` | Phone visible duration | Телефон в кадре: длительность | Телефон көрінеді: ұзақтығы | 0.5 | 0.1–60; step 0.1 seconds | both |
| `events.phone_raised.seconds` | Phone raised near face duration | Телефон возле лица: длительность | Бетке жақын телефон: ұзақтығы | 0.5 | 0.1–60; step 0.1 seconds | both |
| `events.second_person.seconds` | Second person duration | Второй человек: длительность | Екінші адам: ұзақтығы | 1.0 | 0.1–60; step 0.1 seconds | both |
| `events.gaze_deviation.seconds` | Gaze deviation duration | Отклонение взгляда: длительность | Көзқарастың ауытқуы: ұзақтығы | 3.0 | 0.1–60; step 0.1 seconds | both |
| `events.face_absent.seconds` | Face absent duration | Лицо отсутствует: длительность | Бет көрінбейді: ұзақтығы | 3.0 | 0.1–60; step 0.1 seconds | both |
| `clearing_seconds` | Event clearing duration | Время завершения события | Оқиғаны аяқтау уақыты | 0.75 | 0.1–30; step 0.1 seconds | both |
| `audio.enabled` | Microphone energy monitoring | Мониторинг энергии микрофона | Микрофон энергиясын бақылау | true | boolean | disable |
| `snapshots_enabled` | Event camera snapshots | Снимки событий с камеры | Камера оқиғаларының суреттері | true | boolean | disable |
| `audio.voice_duration_threshold` | Audio activity duration | Длительность звуковой активности | Дыбыс белсенділігінің ұзақтығы | 2.0 | 0.1–30; step 0.1 seconds | never |
| `audio.energy_threshold` | Energy threshold (not verified speech) | Порог энергии (не распознавание речи) | Энергия шегі (сөйлеуді тану емес) | 0.15 | 0.001–1; step 0.001  | never |
| `audio.adaptive_calibration` | Adaptive microphone calibration | Адаптивная калибровка микрофона | Микрофонды бейімдеп калибрлеу | true | boolean | never |
| `vision.phone_confidence` | Phone confidence threshold | Порог уверенности: телефон | Телефон сенімділігінің шегі | 0.35 | 0.05–0.95; step 0.01  | never |
| `vision.person_confidence` | Person confidence threshold | Порог уверенности: человек | Адам сенімділігінің шегі | 0.5 | 0.05–0.95; step 0.01  | never |
| `vision.head_down_pitch_degrees` | Downward head angle | Угол наклона головы вниз | Бастың төмен еңкею бұрышы | 14.0 | 5–60; step 1 degrees | never |
| `identity.selfie_verification_enabled` | Geometric consistency (not biometric identification) | Геометрическое сходство (не биометрическая идентификация) | Геометриялық сәйкестік (биометриялық сәйкестендіру емес) | true | boolean | never |
| `identity.impersonation_threshold` | Geometric difference threshold | Порог геометрического различия | Геометриялық айырмашылық шегі | 0.4 | 0.05–2; step 0.01  | never |
| `identity.periodic_check_interval_seconds` | Geometric check interval | Интервал геометрической проверки | Геометриялық тексеру аралығы | 30.0 | 5–300; step 1 seconds | never |

`both` permits a validated versioned live adjustment; `disable` permits only false; `never` is pre-exam only. Dependencies and Python mappings are served in the same catalog.

| Group | English | Russian | Kazakh |
| --- | --- | --- | --- |
| events | Event categories | Категории событий | Оқиға санаттары |
| timing | Detection timing | Время обнаружения | Анықтау уақыты |
| audio | Audio energy | Энергия звука | Дыбыс энергиясы |
| vision | Vision | Зрение | Көру |
| identity | Geometric consistency | Геометрическое сходство | Геометриялық сәйкестік |
| evidence | Evidence | Материалы | Материалдар |


## UI/UX restructuring: separate Configurations workspace

This refinement changes teacher-web presentation and routing only. No backend migration, Python event-engine change, live-command protocol change, native protection change, or new UI dependency was needed. UI UX Pro Max was searched for in the installed skills/plugin directories and was unavailable; it was not used. The existing cream surfaces, moss accents, Inter/Nunito fonts, cards, buttons and navigation were retained.

### Information architecture

- **Exams | Question Library | Configurations** are peer navigation items, with the current section highlighted on both the overview and editor routes.
- `#/configurations` shows Default and owned custom profiles as compact cards. Summaries derive from actual saved values, not invented descriptions. Cards provide View/Edit and Duplicate; deletion is secondary and requires confirmation. An empty custom-profile state offers creation.
- `#/configuration/{id}` edits one saved configuration. Default is visibly read-only, with no empty name input or disabled management-button collection; Duplicate leads to a new editable draft.
- `#/configuration/new` starts from Default. `?from={id}` starts an independent draft from a saved profile. No server object is created until Save.
- Create Exam selects a saved profile. Only second-person, microphone, phone and snapshots are summarized. Manage configurations opens the overview. The existing API receives the full canonical selected policy, never a mutable profile reference. Backend per-exam overrides remain supported for compatibility but are not shown in the normal form.

### Editor interactions and accessibility

Basic uses compact toggle rows; Advanced aligns numeric inputs and units in grouped rows. Informational icons expand the authoritative localized field description with native keyboard-accessible disclosure controls. Changed values alone show a small, named reset button; Restore defaults remains in the editor footer. The numeric bounds, advisory increment steps, defaults, dependencies and Python mappings still come from the catalog.

The editor validates every draft value, including hidden-tab/dependency values, against catalog type/finite/range rules before save. It highlights invalid numeric values and focuses a visible invalid input. It deliberately uses full-policy validation rather than blocking submission on browser `stepMismatch`: the existing canonical clearing default is 0.75 while its catalog increment is 0.1, and the backend accepts finite in-range values, not just step multiples. Catalog increments remain on the inputs; no backend bounds/defaults were changed.

Custom names are edited in the clearly labeled name field and saved with the profile. Save-as uses a named modal flow with required name, cancel/Escape handling and focus restoration. Duplicate starts from the saved profile; unsaved edits require confirmation before leaving. Internal hash navigation, browser back navigation and sign-out invoke the same draft guard; tab close/reload uses the browser's before-unload warning. Browsers control the wording of the latter. There is no draft autosave.

Successful saves show localized feedback. Optimistic-version conflicts preserve the draft and explain how to reload or save a separate copy. Feedback updates when the teacher switches EN/RU/KK. The existing API client supplies authentication/CSRF, and a shared profile adapter is used across overview/editor/selector. Backend ownership checks are unchanged.

Live adjustments remain in the existing attempt panel, with reason, revisions, actual acknowledgement and historical evidence behavior unchanged. The shared catalog renderer receives the same strict live field subset; saved-profile actions never send live commands.

### Focused verification for this UI refinement

- `teacher-web: npm run build` — passed.
- `teacher-web: npx tsx --test tests/core.test.ts` — **9 passed**, including configuration routes/navigation localization and existing API/CSRF client contracts.
- `teacher-web: npx playwright test --config playwright.configuration.config.ts` — **1 comprehensive browser workflow passed** on the existing isolated 5179/8019 setup. Covers navigation, immutable Default, creation/duplicate/save-as/rename/delete, reset by keyboard, dependencies/ranges, unsaved navigation/reload warnings, optimistic conflict retention, EN/RU/KK feedback, saved selection, actual exam snapshot equality and unchanged past exams after profile edits.
- `.venv-server/Scripts/python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_configuration.py -q --tb=short` with `PYTHONPATH=src` — **3 passed**, including ownership, restart persistence, frozen snapshots and live revision/acknowledgement boundaries. The existing Starlette TestClient deprecation warning remains.

Actual rendered screenshots were inspected at 1440-pixel desktop, 1280-pixel desktop, 1024-pixel laptop and 390-pixel narrow widths. Inspection led to aligned numeric columns, tighter rows and locale-reactive notifications. Long Russian/Kazakh text wraps; the mobile test checks horizontal overflow. Screenshots retained in `docs/teacher-config-ui/`:

- [Overview, desktop](teacher-config-ui/overview-desktop.png)
- [Basic editor, desktop](teacher-config-ui/editor-basic.png)
- [Advanced editor, laptop](teacher-config-ui/editor-laptop.png)
- [Create Exam, desktop](teacher-config-ui/create-exam.png)
- [Russian editor, laptop](teacher-config-ui/editor-ru-laptop.png)
- [Kazakh editor, narrow](teacher-config-ui/editor-kk-mobile.png)

Known limits: deletion/discard use accessible native browser confirmations; native numeric formatting and reload-warning language follow browser settings. Advanced has more fields and therefore still scrolls, but it is isolated from exam creation. A profile selected in an already-open Create Exam form is the saved snapshot loaded at selection time; later edits in another tab do not silently replace it. Reload Create Exam to pick up newer saved values. No real exam, device capture, native audit, tunnel, load test or package build was performed. Historical protection audits remain historical and are not revalidated by these UI tests.
