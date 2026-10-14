"""No desktop conftest: run with --confcutdir=tests/teacher_server."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from proctoring_server.service import Service, iso
from proctoring_server.settings import Settings


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 13, 12, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings(tmp_path):
    return Settings(database=tmp_path / "teacher.sqlite3", public_url="http://127.0.0.1:8000",
                    teacher_origin="http://127.0.0.1:5174", allow_local_http=True)


@pytest.fixture
def service(settings, clock):
    return Service(settings, clock=clock)


@pytest.fixture
def app(service, settings, clock):
    pytest.importorskip("fastapi", reason="Server FastAPI dependency not installed")
    pytest.importorskip("python_multipart", reason="Server multipart dependency not installed")
    from proctoring_server.app import create_app
    application = create_app(settings, clock=clock)
    # Same SQLite database; calls use distinct connections as in production.
    return application


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


@pytest.fixture
def owner(service):
    invite = service.issue_account_token("invite", "teacher@example.com")
    return service.consume_account_token("invite", {"token": invite, "name": "Teacher One", "password": "test password 12345"})["teacher"]["id"]


@pytest.fixture
def other(service):
    invite = service.issue_account_token("invite", "other@example.com")
    return service.consume_account_token("invite", {"token": invite, "name": "Teacher Two", "password": "other password 12345"})["teacher"]["id"]


@pytest.fixture
def document():
    return {"title": "Arithmetic", "questions": [
        {"id": "single", "type": "single_choice", "prompt": "One plus one?", "options": [
            {"id": "two", "text": "2"}, {"id": "three", "text": "3"}], "correct_option_ids": ["two"]},
        {"id": "multi", "type": "multiple_choice", "prompt": "Even numbers?", "options": [
            {"id": "two", "text": "2"}, {"id": "three", "text": "3"}, {"id": "four", "text": "4"}], "correct_option_ids": ["two", "four"]}]}


@pytest.fixture
def library(service, owner, document):
    return service.save_library(owner, deepcopy(document))


@pytest.fixture
def exam_data(clock, library):
    return {"title": "Test exam", "exam_type": "native", "library_id": library["id"],
            "admission_start": iso(clock() - 60), "admission_close": iso(clock() + 3600),
            "duration_seconds": 600, "timezone": "Asia/Qyzylorda", "shuffle_questions": True,
            "shuffle_options": True, "audio_monitoring": False, "save_snapshots": False,
            "protection_mode": "unprotected"}


@pytest.fixture
def exam(service, owner, exam_data):
    return service.create_exam(owner, exam_data)


@pytest.fixture
def admission_data(exam):
    return {"exam_code": exam["code"], "full_name": "Test Student", "group": "Group A", "student_id": "Student001"}


@pytest.fixture
def admitted(service, admission_data):
    return service.admit(admission_data)
