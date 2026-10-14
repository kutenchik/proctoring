from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from proctoring_server.security import digest, hash_password, verify_password
from proctoring_server.service import Problem
from proctoring_server.settings import Settings

ORIGIN = {"Origin": "http://127.0.0.1:5174"}
PASSWORD = "test password 12345"


def login(client):
    response = client.post("/api/v1/auth/login", json={"email": "teacher@example.com", "password": PASSWORD}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    return response


def test_secure_defaults_and_loopback_exception(tmp_path):
    assert Settings(database=tmp_path / "a.db").secure_cookie
    assert not Settings(public_url="http://127.0.0.1:8000", teacher_origin="http://127.0.0.1:5174", allow_local_http=True).secure_cookie
    for url in ("http://localhost", "http://example.com", "http://192.168.1.4", "http://localhost.evil", "file:///test"):
        with pytest.raises(ValueError):
            Settings(public_url=url, allow_local_http=True)
    with pytest.raises(ValueError):
        Settings(public_url="http://localhost")


def test_password_hash_salted_and_invalid_parameters():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second and PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert not verify_password("wrong", first)
    assert not verify_password(PASSWORD, first.replace("32768", "999999999"))


def test_invitation_is_hashed_single_use_and_persistent(service):
    raw = service.issue_account_token("invite", "teacher@example.com")
    with service.database.connect() as connection:
        stored = dict(connection.execute("SELECT * FROM account_tokens").fetchone())
    assert raw not in str(stored)
    result = service.consume_account_token("invite", {"token": raw, "name": "Teacher", "password": PASSWORD})
    assert result["teacher"]["email"] == "teacher@example.com"
    with pytest.raises(Problem, match="already used"):
        service.consume_account_token("invite", {"token": raw, "name": "Teacher", "password": PASSWORD})


def test_expired_and_replaced_invites_rejected(service, clock):
    first = service.issue_account_token("invite", "teacher@example.com")
    second = service.issue_account_token("invite", "teacher@example.com")
    with pytest.raises(Problem):
        service.consume_account_token("invite", {"token": first, "name": "Teacher", "password": PASSWORD})
    clock.advance(3600)
    with pytest.raises(Problem):
        service.consume_account_token("invite", {"token": second, "name": "Teacher", "password": PASSWORD})


def test_concurrent_invite_consumption_exactly_once(service):
    raw = service.issue_account_token("invite", "teacher@example.com")
    def accept(_):
        try:
            service.consume_account_token("invite", {"token": raw, "name": "Teacher", "password": PASSWORD})
            return "ok"
        except Problem as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(accept, range(2))) == ["invalid_token", "ok"]


def test_no_registration_and_origin_required(client, owner):
    assert client.post("/api/v1/auth/register", json={}).status_code == 404
    assert client.post("/api/v1/auth/login", json={"email": "teacher@example.com", "password": PASSWORD}).status_code == 403
    assert client.post("/api/v1/auth/login", headers={"Origin": "https://evil.example"}, json={"email": "teacher@example.com", "password": PASSWORD}).status_code == 403


def test_cookie_csrf_logout_and_expiry(client, owner, clock):
    response = login(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    csrf = response.json()["csrf_token"]
    assert client.get("/api/v1/auth/me").json()["csrf_token"] == csrf
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={**ORIGIN, "X-CSRF-Token": "invalid"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={**ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client)
    clock.advance(43200)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_reset_revokes_all_sessions_and_token_cannot_repeat(service, owner):
    first, _ = service.login({"email": "teacher@example.com", "password": PASSWORD}, "one")
    second, _ = service.login({"email": "teacher@example.com", "password": PASSWORD}, "two")
    reset = service.issue_account_token("reset", "teacher@example.com")
    service.consume_account_token("reset", {"token": reset, "password": "new password 67890"})
    for raw in (first, second):
        with pytest.raises(Problem):
            service.authenticate(raw)
    with pytest.raises(Problem):
        service.consume_account_token("reset", {"token": reset, "password": PASSWORD})
    with pytest.raises(Problem):
        service.login({"email": "teacher@example.com", "password": PASSWORD}, "three")
    assert service.login({"email": "teacher@example.com", "password": "new password 67890"}, "four")[1]["teacher"]["id"] == owner


def test_login_throttle_persists_and_expires(service, owner, clock):
    for _ in range(10):
        with pytest.raises(Problem) as failure:
            service.login({"email": "teacher@example.com", "password": "incorrect"}, "one")
        assert failure.value.code == "invalid_credentials"
    with pytest.raises(Problem) as failure:
        service.login({"email": "teacher@example.com", "password": PASSWORD}, "other")
    assert failure.value.code == "login_throttled"
    clock.advance(901)
    assert service.login({"email": "teacher@example.com", "password": PASSWORD}, "one")[0]


def test_password_whitespace_preserved(service):
    raw = service.issue_account_token("invite", "space@example.com")
    password = "  valid password with spaces  "
    service.consume_account_token("invite", {"token": raw, "name": "Teacher", "password": password})
    assert service.login({"email": "space@example.com", "password": password}, "one")[0]
    with pytest.raises(Problem):
        service.login({"email": "space@example.com", "password": password.strip()}, "one")


def test_health_and_security_headers(client):
    response = client.get("/api/v1/health")
    assert response.json()["api_version"] == 1
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_body_limit_before_parsing(client):
    response = client.post("/api/v1/auth/login", content=b"x" * (3 * 1024 * 1024 + 1), headers={**ORIGIN, "Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "body_too_large"


@pytest.mark.parametrize("kind", ["invite", "reset"])
@pytest.mark.parametrize("state", ["invalid", "expired", "used"])
def test_invalid_account_links_do_not_hash_password(service, owner, clock, monkeypatch, kind, state):
    email = "new@example.com" if kind == "invite" else "teacher@example.com"
    raw = service.issue_account_token(kind, email)
    payload = {"token": raw, "name": "Teacher", "password": PASSWORD}
    if state == "expired":
        clock.advance(service.settings.token_seconds)
    elif state == "used":
        service.consume_account_token(kind, payload)
    else:
        payload["token"] = "not-an-issued-token"

    def forbidden_hash(_):
        raise AssertionError("Invalid account token performed expensive password hashing")

    monkeypatch.setattr("proctoring_server.service.hash_password", forbidden_hash)
    with pytest.raises(Problem) as failure:
        service.consume_account_token(kind, payload)
    assert failure.value.code == "invalid_token"


@pytest.mark.parametrize("kind", ["invite", "reset"])
def test_token_expiring_during_hash_is_rechecked(service, owner, clock, monkeypatch, kind):
    email = "new@example.com" if kind == "invite" else "teacher@example.com"
    raw = service.issue_account_token(kind, email)
    password_hash = hash_password(PASSWORD)

    def slow_hash(_):
        # Also prove no write lock is held while the hash runs.
        with service.database.connect(write=True) as connection:
            connection.execute("SELECT 1")
        clock.advance(service.settings.token_seconds)
        return password_hash

    monkeypatch.setattr("proctoring_server.service.hash_password", slow_hash)
    with pytest.raises(Problem) as failure:
        service.consume_account_token(kind, {"token": raw, "name": "Teacher", "password": PASSWORD})
    assert failure.value.code == "invalid_token"
    with service.database.connect() as connection:
        entry = connection.execute("SELECT consumed_at FROM account_tokens WHERE token_hash=?", (digest(raw),)).fetchone()
    assert entry["consumed_at"] is None


def test_concurrent_valid_preflights_still_consume_once(service, monkeypatch):
    raw = service.issue_account_token("invite", "teacher@example.com")
    barrier = Barrier(2)
    password_hash = hash_password(PASSWORD)

    def simultaneous_hash(_):
        barrier.wait(timeout=5)
        return password_hash

    monkeypatch.setattr("proctoring_server.service.hash_password", simultaneous_hash)

    def consume(_):
        try:
            service.consume_account_token("invite", {"token": raw, "name": "Teacher", "password": PASSWORD})
            return "ok"
        except Problem as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(consume, range(2))) == ["invalid_token", "ok"]
