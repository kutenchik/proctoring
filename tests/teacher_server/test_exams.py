from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest

from proctoring_server.service import Problem, iso


def test_owner_isolation_all_resources(service, owner, other, library, exam, admitted):
    assert service.libraries(other) == {"items": []}
    assert service.exams(other) == {"items": []}
    actions = [lambda: service.library(other, library["id"]), lambda: service.exam(other, exam["id"]),
               lambda: service.attempts(other, exam["id"]), lambda: service.extend(other, admitted["attempt_id"], {"reason": "test"}),
               lambda: service.allow_repeat(other, admitted["attempt_id"], {"reason": "test"})]
    for action in actions:
        with pytest.raises(Problem) as failure:
            action()
        assert failure.value.status == 404


def test_cannot_create_exam_from_other_teacher_library(service, other, exam_data):
    with pytest.raises(Problem) as failure:
        service.create_exam(other, exam_data)
    assert failure.value.status == 404


def test_snapshot_stable_after_library_changes_and_shuffling(service, owner, document, library, exam, admitted):
    changed = deepcopy(document)
    changed["questions"][0]["prompt"] = "Changed after publication"
    with service.database.connect(write=True) as connection:
        connection.execute("UPDATE libraries SET document=? WHERE id=?", (json.dumps(changed), library["id"]))
    assert service.exam(owner, exam["id"])["quiz"] == document
    state = service.student_attempt(admitted["credential"])
    assert state["quiz"] == admitted["quiz"]
    assert service.start(admitted["credential"])["quiz"] == admitted["quiz"]
    original_ids = {q["id"]: set(q["correct_option_ids"]) for q in document["questions"]}
    assert {q["id"]: set(q["correct_option_ids"]) for q in state["quiz"]["questions"]} == original_ids
    assert state["exam"]["policy"] == exam["policy"]


@pytest.mark.parametrize("field,value,code", [
    ("timezone", "Not/AZone", "invalid_timezone"),
    ("admission_start", "2026-10-13T12:00:00", "invalid_time"),
    ("duration_seconds", True, "invalid_duration"),
    ("duration_seconds", 0, "invalid_duration"),
    ("shuffle_options", "yes", "invalid_policy"),
    ("protection_mode", "automatic", "invalid_policy"),
])
def test_exam_validation(service, owner, exam_data, field, value, code):
    exam_data[field] = value
    with pytest.raises(Problem) as failure:
        service.create_exam(owner, exam_data)
    assert failure.value.code == code


def test_window_offset_and_boundaries(service, owner, exam_data, clock):
    exam_data["admission_start"] = "2026-10-13T17:00:00+05:00"
    exam_data["admission_close"] = "2026-10-13T17:01:00+05:00"
    exam = service.create_exam(owner, exam_data)
    assert exam["admission_start"] == "2026-10-13T12:00:00+00:00"
    assert exam["phase"] == "active"
    identity = {"exam_code": exam["code"], "full_name": "Student", "student_id": "one", "group": "A"}
    clock.advance(-0.001)
    with pytest.raises(Problem, match="not open"):
        service.admit(identity)
    clock.advance(0.001)
    admitted = service.admit(identity)
    clock.advance(60)
    state = service.exam(owner, exam["id"])
    assert state["phase"] == "active"
    assert state["admission_open"] is False
    with pytest.raises(Problem, match="not open"):
        service.admit({**identity, "student_id": "two"})
    assert service.start(admitted["credential"])["status"] == "started"


def test_inverted_window_rejected(service, owner, exam_data):
    exam_data["admission_close"] = exam_data["admission_start"]
    with pytest.raises(Problem) as failure:
        service.create_exam(owner, exam_data)
    assert failure.value.code == "invalid_window"


def test_preparation_boundary_and_extension_audit(service, owner, admitted, clock):
    clock.advance(300)
    with pytest.raises(Problem) as failure:
        service.start(admitted["credential"])
    assert failure.value.code == "preparation_expired"
    with pytest.raises(Problem):
        service.extend(owner, admitted["attempt_id"], {"reason": "  "})
    clock.advance(60)
    extended = service.extend(owner, admitted["attempt_id"], {"reason": "Camera setup needed more time"})
    assert extended["preparation_deadline"] == iso(clock() + 300)
    with service.database.connect() as connection:
        audit = connection.execute("SELECT * FROM audit_log WHERE action='preparation_extended'").fetchone()
    assert audit["reason"] == "Camera setup needed more time"
    assert json.loads(audit["details"])["seconds"] == 300
    clock.advance(299.9)
    assert service.start(admitted["credential"])["status"] == "started"
    with pytest.raises(Problem):
        service.extend(owner, admitted["attempt_id"], {"reason": "Already started"})


def test_start_idempotent_after_deadline_but_not_after_finish(service, admitted, clock):
    first = service.start(admitted["credential"])
    clock.advance(1000)
    second = service.start(admitted["credential"])
    assert first["started_at"] == second["started_at"]
    service.finish(admitted["credential"], {"score": 2, "total": 2, "end_reason": "submitted"})
    with pytest.raises(Problem) as failure:
        service.start(admitted["credential"])
    assert failure.value.code == "attempt_finished"


def test_duplicate_admission_race_exactly_one_and_hashed_credential(service, admission_data, owner, exam):
    def admit(_):
        try:
            return service.admit(admission_data)
        except Problem as error:
            return error.code
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(admit, range(4)))
    assert results.count("attempt_exists") == 3
    successful = next(value for value in results if isinstance(value, dict))
    teacher_view = service.attempts(owner, exam["id"])
    assert len(teacher_view["items"]) == 1
    assert "credential" not in json.dumps(teacher_view)
    with service.database.connect() as connection:
        row = dict(connection.execute("SELECT * FROM attempts").fetchone())
    assert successful["credential"] not in str(row)
    assert service.exam(owner, exam["id"])["participant_count"] == 1


def test_id_exact_case_and_trimmed_boundaries(service, admission_data):
    service.admit(admission_data)
    with pytest.raises(Problem):
        service.admit({**admission_data, "student_id": " " + admission_data["student_id"] + " "})
    assert service.admit({**admission_data, "student_id": admission_data["student_id"].lower()})["credential"]


def test_repeat_requires_reason_terminal_and_consumes_once(service, owner, admitted, admission_data, clock, exam):
    with pytest.raises(Problem) as failure:
        service.allow_repeat(owner, admitted["attempt_id"], {"reason": "Need another"})
    assert failure.value.code == "attempt_live"
    clock.advance(300)
    with pytest.raises(Problem):
        service.allow_repeat(owner, admitted["attempt_id"], {"reason": ""})
    service.allow_repeat(owner, admitted["attempt_id"], {"reason": "Setup expired"})
    with pytest.raises(Problem):
        service.allow_repeat(owner, admitted["attempt_id"], {"reason": "Duplicate grant"})
    repeated = service.admit(admission_data)
    assert repeated["attempt_id"] != admitted["attempt_id"]
    with pytest.raises(Problem) as failure:
        service.student_attempt(admitted["credential"])
    assert failure.value.code == "attempt_superseded"
    with pytest.raises(Problem):
        service.admit(admission_data)
    attempts = service.attempts(owner, exam["id"])["items"]
    assert {row["sequence"] for row in attempts} == {1, 2}
    with service.database.connect() as connection:
        row = connection.execute("SELECT * FROM repeat_grants").fetchone()
    assert row["new_attempt_id"] == repeated["attempt_id"]
    assert row["consumed_at"] is not None


def test_repeat_race_consumes_only_one_grant(service, owner, admitted, admission_data, clock):
    clock.advance(300)
    service.allow_repeat(owner, admitted["attempt_id"], {"reason": "Preparation issue"})
    def admit(_):
        try:
            return service.admit(admission_data)["attempt_id"]
        except Problem as error:
            return error.code
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(admit, range(3)))
    assert results.count("attempt_exists") == 2


def test_student_id_is_not_attempt_credential(service, admitted, admission_data):
    with pytest.raises(Problem) as failure:
        service.student_attempt(admission_data["student_id"])
    assert failure.value.status == 401
    with pytest.raises(Problem):
        service.start("not-a-token")


def test_client_reported_finish_idempotent_and_labelled(service, owner, admitted, exam):
    with pytest.raises(Problem):
        service.finish(admitted["credential"], {"score": 2, "total": 2, "end_reason": "submitted"})
    service.start(admitted["credential"])
    assert service.finish(admitted["credential"], {"score": 1, "total": 2, "end_reason": "submitted"})["status"] == "finished"
    service.finish(admitted["credential"], {"score": 2, "total": 2, "end_reason": "changed"})
    attempt = service.attempts(owner, exam["id"])["items"][0]
    assert (attempt["score"], attempt["total"], attempt["end_reason"], attempt["result_source"]) == (1, 2, "submitted", "client_reported")


def test_external_exam_policy_and_url_validation(service, owner, exam_data):
    exam_data.update(exam_type="external", external_url="https://lms.example.edu/exam?id=1")
    created = service.create_exam(owner, exam_data)
    assert created["quiz"] is None and created["external_url"] == exam_data["external_url"]
    for bad in ("javascript:alert(1)", "http://lms.example.edu", "https://user:pass@lms.example.edu"):
        with pytest.raises(Problem):
            service.create_exam(owner, {**exam_data, "external_url": bad})


def test_migrations_idempotent(service):
    service.database.migrate()
    service.database.migrate()
    with service.database.connect() as connection:
        assert [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3, 4, 5]


def test_shuffle_applied_once_preserves_correct_ids(service, exam, admission_data, document, monkeypatch):
    class ReverseOrder:
        def shuffle(self, values):
            values.reverse()
    monkeypatch.setattr("proctoring_server.service.secrets.SystemRandom", ReverseOrder)
    admitted = service.admit(admission_data)
    expected = deepcopy(document)
    expected["questions"].reverse()
    for question in expected["questions"]:
        question["options"].reverse()
    assert admitted["quiz"] == expected
    assert service.student_attempt(admitted["credential"])["quiz"] == expected
    assert service.start(admitted["credential"])["quiz"] == expected


def test_repeat_does_not_override_closed_admission_window(service, owner, admitted, admission_data, clock):
    clock.advance(3600)
    service.allow_repeat(owner, admitted["attempt_id"], {"reason": "Preparation expired"})
    with pytest.raises(Problem) as failure:
        service.admit(admission_data)
    assert failure.value.code == "admission_closed"


def test_running_attempt_cannot_repeat_after_preparation_deadline(service, owner, admitted, clock):
    service.start(admitted["credential"])
    clock.advance(300)
    with pytest.raises(Problem) as failure:
        service.allow_repeat(owner, admitted["attempt_id"], {"reason": "Try again"})
    assert failure.value.code == "attempt_live"


def test_extend_and_start_race_preserves_authorized_state(service, owner, admitted):
    def action(kind):
        try:
            return service.start(admitted["credential"]) if kind == "start" else service.extend(owner, admitted["attempt_id"], {"reason": "Setup"})
        except Problem as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(action, ["start", "extend"]))
    assert isinstance(results[0], dict) and results[0]["status"] == "started"
    assert isinstance(results[1], dict) or results[1] == "attempt_started"
    assert service.student_attempt(admitted["credential"])["status"] == "started"


def test_expired_credential_cannot_reconnect(service, admitted, clock):
    clock.advance(300 + 30 * 86400)
    with pytest.raises(Problem) as failure:
        service.student_attempt(admitted["credential"])
    assert failure.value.code == "invalid_credential"


@pytest.mark.parametrize("field", ["group", "student_id"])
def test_identity_limits_match_desktop_before_creating_attempt(service, admission_data, field):
    with pytest.raises(Problem) as failure:
        service.admit({**admission_data, field: "x" * 129})
    assert failure.value.code == "invalid_input"
    assert service.admit({**admission_data, field: "x" * 128})["credential"]


def test_external_finish_rejects_fabricated_local_score(service, owner, exam_data):
    exam_data.update(exam_type="external", external_url="https://lms.example.edu/exam")
    exam = service.create_exam(owner, exam_data)
    admission = service.admit({"exam_code": exam["code"], "full_name": "Student", "group": "A", "student_id": "id"})
    service.start(admission["credential"])
    with pytest.raises(Problem) as failure:
        service.finish(admission["credential"], {"score": 100, "total": 100, "end_reason": "submitted"})
    assert failure.value.code == "invalid_result"
    assert service.finish(admission["credential"], {"score": None, "total": None, "end_reason": "proctor_ended"})["status"] == "finished"


def test_phase_reflects_recorded_attempts_not_just_admission_window(service, owner, exam_data, clock):
    exam_data["admission_close"] = iso(clock() + 60)
    exam = service.create_exam(owner, exam_data)
    admission = service.admit({"exam_code": exam["code"], "full_name": "Student", "group": "A", "student_id": "id"})
    clock.advance(60)
    assert service.exam(owner, exam["id"])["phase"] == "active"
    assert service.exam(owner, exam["id"])["admission_open"] is False
    service.start(admission["credential"])
    clock.advance(3600)
    # This is a recorded started state, not proof the client is still online.
    state = service.exam(owner, exam["id"])
    assert state["phase"] == "active"
    assert state["phase_basis"] == "server_admission_and_recorded_attempts"
    service.finish(admission["credential"], {"score": 1, "total": 2, "end_reason": "submitted"})
    assert service.exam(owner, exam["id"])["phase"] == "completed"


def test_phase_completed_when_closed_and_preparation_expired(service, owner, exam_data, clock):
    exam_data["admission_close"] = iso(clock() + 60)
    exam = service.create_exam(owner, exam_data)
    service.admit({"exam_code": exam["code"], "full_name": "Student", "group": "A", "student_id": "id"})
    clock.advance(300)
    assert service.exam(owner, exam["id"])["phase"] == "completed"


@pytest.mark.parametrize("url", ["https://exa mple.edu/test", "https://example.edu\\@evil.edu", "https://127.1/test", "https://example.edu:/test"])
def test_external_url_uses_same_guard_as_desktop(service, owner, exam_data, url):
    with pytest.raises(Problem) as failure:
        service.create_exam(owner, {**exam_data, "exam_type": "external", "external_url": url})
    assert failure.value.code == "invalid_url"


def test_external_url_canonicalized_before_admission(service, owner, exam_data):
    result = service.create_exam(owner, {**exam_data, "exam_type": "external", "external_url": "https://LMS.Example.edu./test"})
    assert result["external_url"] == "https://lms.example.edu/test"
