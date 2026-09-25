from pathlib import Path
import secrets
import os
import subprocess
import sys

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import app.auth as auth
import app.user_migrations as user_migrations
from app.web import app


@pytest.fixture
def auth_client(monkeypatch):
    previous_secret = app.secret_key
    app.secret_key = secrets.token_urlsafe(32)
    app.config["SESSION_COOKIE_SECURE"] = False
    monkeypatch.setattr(auth, "get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr(auth, "get_active_user_by_id", lambda user_id: {
        "id": user_id,
        "name": "izicode",
        "login": "izicode",
        "role": "MASTER",
    })
    auth.login_attempt_limiter.clear()
    yield app.test_client()
    auth.login_attempt_limiter.clear()
    app.secret_key = previous_secret


def test_login_creates_signed_session_without_returning_password_hash(auth_client, monkeypatch):
    password = secrets.token_urlsafe(24)
    password_hash = generate_password_hash(password, method="scrypt")
    monkeypatch.setattr(auth, "get_user_by_login", lambda login: {
        "id": 1,
        "name": "izicode",
        "login": login,
        "password_hash": password_hash,
        "active": True,
        "role": "MASTER",
    })

    response = auth_client.post(
        "/api/auth/login",
        json={"login": "IZICODE", "password": password},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "user": {"id": 1, "name": "izicode", "login": "izicode", "role": "MASTER"}
    }
    assert "password_hash" not in response.get_json()
    assert "HttpOnly" in response.headers["Set-Cookie"]

    session_response = auth_client.get("/api/auth/session")
    assert session_response.get_json()["authenticated"] is True
    assert "password_hash" not in session_response.get_json()["user"]

    logout_response = auth_client.post("/api/auth/logout", json={})
    assert logout_response.status_code == 204
    assert auth_client.get("/api/auth/session").get_json() == {"authenticated": False}


def test_login_rejects_invalid_or_inactive_credentials(auth_client, monkeypatch):
    password = secrets.token_urlsafe(24)
    password_hash = generate_password_hash(password, method="scrypt")
    monkeypatch.setattr(auth, "get_user_by_login", lambda login: {
        "id": 2,
        "name": "disabled",
        "login": login,
        "password_hash": password_hash,
        "active": False,
        "role": "USER",
    })

    response = auth_client.post(
        "/api/auth/login",
        json={"login": "disabled", "password": password},
    )
    assert response.status_code == 401
    assert "password_hash" not in response.get_data(as_text=True)

    invalid_login = auth_client.post(
        "/api/auth/login",
        json={"login": "invalid login", "password": "some-password"},
    )
    assert invalid_login.status_code == 400


def test_login_attempts_are_temporarily_blocked_then_expire(auth_client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(auth, "get_user_by_login", lambda login: None)
    payload = {"login": "izicode", "password": "invalid-password"}

    for _ in range(auth.LOGIN_FAILURE_LIMIT - 1):
        assert auth_client.post("/api/auth/login", json=payload).status_code == 401

    blocked = auth_client.post("/api/auth/login", json=payload)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == str(auth.LOGIN_BLOCK_SECONDS)
    assert blocked.get_json() == {
        "error": "Muitas tentativas. Aguarde antes de tentar novamente."
    }

    now[0] += auth.LOGIN_BLOCK_SECONDS + 1
    assert auth_client.post("/api/auth/login", json=payload).status_code == 401


def test_login_attempt_counter_is_scoped_to_ip_and_login(auth_client, monkeypatch):
    monkeypatch.setattr(auth, "get_user_by_login", lambda login: None)
    password = "invalid-password"

    same_ip_other_login = {"login": "other-user", "password": password}
    for _ in range(auth.LOGIN_FAILURE_LIMIT - 1):
        assert auth_client.post(
            "/api/auth/login",
            json={"login": "izicode", "password": password},
        ).status_code == 401
    assert auth_client.post("/api/auth/login", json=same_ip_other_login).status_code == 401
    assert auth_client.post(
        "/api/auth/login",
        json={"login": "izicode", "password": password},
    ).status_code == 429

    auth.login_attempt_limiter.clear()
    shared_login = {"login": "izicode", "password": password}
    first_ip = app.test_client()
    second_ip = app.test_client()
    for _ in range(auth.LOGIN_FAILURE_LIMIT - 1):
        assert first_ip.post(
            "/api/auth/login",
            json=shared_login,
            environ_base={"REMOTE_ADDR": "198.51.100.10"},
        ).status_code == 401
    assert second_ip.post(
        "/api/auth/login",
        json=shared_login,
        environ_base={"REMOTE_ADDR": "198.51.100.11"},
    ).status_code == 401
    assert first_ip.post(
        "/api/auth/login",
        json=shared_login,
        environ_base={"REMOTE_ADDR": "198.51.100.10"},
    ).status_code == 429


def test_login_does_not_return_or_log_password(auth_client, monkeypatch, caplog):
    password = secrets.token_urlsafe(24)
    monkeypatch.setattr(auth, "get_user_by_login", lambda login: None)

    response = auth_client.post(
        "/api/auth/login",
        json={"login": "izicode", "password": password},
    )

    assert response.status_code == 401
    assert password not in response.get_data(as_text=True)
    assert password not in caplog.text


def test_master_seed_hashes_password_and_uses_environment(monkeypatch):
    captured = {}
    password = secrets.token_urlsafe(24)

    def fake_seed(login, name, password_hash):
        captured.update(login=login, name=name, password_hash=password_hash)
        return {"id": 1, "login": login, "role": "MASTER"}

    monkeypatch.setattr(user_migrations, "seed_master_user", fake_seed)
    monkeypatch.setenv("MASTER_PASSWORD", password)
    monkeypatch.delenv("MASTER_LOGIN", raising=False)
    monkeypatch.delenv("MASTER_NAME", raising=False)

    result = user_migrations.create_master_from_environment()

    assert result == {"id": 1, "login": "izicode", "role": "MASTER"}
    assert captured["login"] == captured["name"] == "izicode"
    assert captured["password_hash"] != password
    assert check_password_hash(captured["password_hash"], password)
    assert password not in repr(result)


def test_user_migration_keeps_scanner_signals_global():
    migration = (
        Path(__file__).resolve().parent.parent
        / "migrations"
        / "001_user_foundation.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table if not exists users" in migration
    assert "create table if not exists user_coins" in migration
    assert "create table if not exists strategies" in migration
    assert "references users(id)" in migration
    assert "signals" not in migration
    assert "alter table signals" not in migration


def test_user_migrations_are_applied_once(monkeypatch):
    class FakeCursor:
        def __init__(self, connection):
            self.connection = connection
            self.result = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, statement, parameters=None):
            self.connection.statements.append(statement.strip())
            if "SELECT 1 FROM schema_migrations" in statement:
                self.result = (1,) if parameters[0] in self.connection.applied else None
            elif "INSERT INTO schema_migrations" in statement:
                self.connection.applied.add(parameters[0])

        def fetchone(self):
            return self.result

    class FakeConnection:
        def __init__(self):
            self.applied = set()
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor(self)

        def commit(self):
            pass

    connection = FakeConnection()
    monkeypatch.setattr(user_migrations, "_connect", lambda: connection)

    first_run = user_migrations.apply_migrations()
    second_run = user_migrations.apply_migrations()

    assert first_run == ["001_user_foundation.sql"]
    assert second_run == []
    assert sum("CREATE TABLE IF NOT EXISTS users" in sql for sql in connection.statements) == 1


def test_auth_requires_a_configured_session_secret(monkeypatch):
    previous_secret = app.secret_key
    monkeypatch.setattr(auth, "get_database_url", lambda: "postgresql://test")
    app.secret_key = None
    try:
        response = app.test_client().post(
            "/api/auth/login",
            json={"login": "izicode", "password": "some-password"},
        )
        assert response.status_code == 503
    finally:
        app.secret_key = previous_secret


def test_global_analysis_endpoints_require_authentication(monkeypatch):
    previous_secret = app.secret_key
    app.secret_key = secrets.token_urlsafe(32)
    monkeypatch.setattr(auth, "get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr(auth, "get_active_user_by_id", lambda user_id: {
        "id": user_id,
        "name": "izicode",
        "login": "izicode",
        "role": "MASTER",
    })
    try:
        client = app.test_client()
        for path in (
            "/",
            "/api/status",
            "/api/history",
            "/api/components",
            "/api/entries",
            "/api/evaluation",
            "/api/summary",
        ):
            response = client.get(path)
            assert response.status_code == 401, path

        with client.session_transaction() as client_session:
            client_session["user_id"] = 1
        first_user_response = client.get("/api/history")
        assert first_user_response.status_code == 200

        second_user = app.test_client()
        with second_user.session_transaction() as client_session:
            client_session["user_id"] = 2
        second_user_response = second_user.get("/api/history")
        assert second_user_response.status_code == 200
        assert second_user_response.get_json() == first_user_response.get_json()
    finally:
        app.secret_key = previous_secret


def test_production_requires_strong_secret_and_enables_secure_cookie():
    environment = os.environ.copy()
    environment.pop("AUTH_SECRET_KEY", None)
    environment["APP_ENV"] = "production"
    missing_secret = subprocess.run(
        [sys.executable, "-c", "import app.web"],
        cwd=Path(__file__).resolve().parent.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_secret.returncode != 0
    assert "AUTH_SECRET_KEY" in missing_secret.stderr

    environment["AUTH_SECRET_KEY"] = secrets.token_urlsafe(48)
    production_config = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.web import app; assert app.config['SESSION_COOKIE_SECURE']",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert production_config.returncode == 0, production_config.stderr
