from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash

from .auth_utils import normalize_login
from .db import get_active_user_by_id, get_database_url, get_user_by_login


auth_api = Blueprint("auth_api", __name__, url_prefix="/api/auth")

LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
LOGIN_BLOCK_SECONDS = 5 * 60
LOGIN_TRACKER_MAX_ENTRIES = 10_000


class LoginAttemptLimiter:
    """Bounded, process-local throttle keyed by client IP and normalized login."""

    def __init__(self) -> None:
        self._attempts: OrderedDict[tuple[str, str], tuple[int, float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()

    def retry_after(self, key: tuple[str, str], now: float) -> int:
        with self._lock:
            self._expire(now)
            record = self._attempts.get(key)
            if record is None:
                return 0
            failures, window_started, blocked_until = record
            if blocked_until > now:
                self._attempts.move_to_end(key)
                return max(1, int(blocked_until - now + 0.999))
            if failures >= LOGIN_FAILURE_LIMIT and now - window_started < LOGIN_FAILURE_WINDOW_SECONDS:
                return self._block(key, failures, window_started, now)
            return 0

    def record_failure(self, key: tuple[str, str], now: float) -> int:
        with self._lock:
            self._expire(now)
            record = self._attempts.get(key)
            if record is None or now - record[1] >= LOGIN_FAILURE_WINDOW_SECONDS:
                failures, window_started = 0, now
            else:
                failures, window_started = record[0], record[1]
            failures += 1
            if failures >= LOGIN_FAILURE_LIMIT:
                return self._block(key, failures, window_started, now)
            self._attempts[key] = (failures, window_started, 0.0)
            self._attempts.move_to_end(key)
            self._trim()
            return 0

    def record_success(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _block(self, key: tuple[str, str], failures: int, window_started: float, now: float) -> int:
        blocked_until = now + LOGIN_BLOCK_SECONDS
        self._attempts[key] = (failures, window_started, blocked_until)
        self._attempts.move_to_end(key)
        self._trim()
        return LOGIN_BLOCK_SECONDS

    def _expire(self, now: float) -> None:
        expired = [
            key for key, (_, window_started, blocked_until) in self._attempts.items()
            if (blocked_until and blocked_until <= now)
            or (not blocked_until and now - window_started >= LOGIN_FAILURE_WINDOW_SECONDS)
        ]
        for key in expired:
            self._attempts.pop(key, None)

    def _trim(self) -> None:
        while len(self._attempts) > LOGIN_TRACKER_MAX_ENTRIES:
            self._attempts.popitem(last=False)


login_attempt_limiter = LoginAttemptLimiter()


def _auth_not_configured():
    return jsonify({"error": "Autenticação indisponível. Verifique a configuração do serviço."}), 503


def authentication_ready() -> bool:
    return bool(current_app.secret_key and get_database_url())


def _session_user():
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    user = get_active_user_by_id(user_id)
    if user is None:
        session.clear()
    return user


def _client_ip() -> str:
    remote_address = request.remote_addr or "unknown"
    try:
        remote_ip = ipaddress.ip_address(remote_address)
    except ValueError:
        return remote_address

    if remote_ip.is_loopback:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        forwarded_addresses = [address.strip() for address in forwarded_for.split(",")]
        for address in reversed(forwarded_addresses):
            try:
                return str(ipaddress.ip_address(address))
            except ValueError:
                continue
    return str(remote_ip)


def _login_attempt_key(normalized_login: str) -> tuple[str, str]:
    return (_client_ip(), normalized_login)


def _login_rate_limited(retry_after: int):
    response = jsonify({"error": "Muitas tentativas. Aguarde antes de tentar novamente."})
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def authenticated_user(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        if not authentication_ready():
            return _auth_not_configured()
        if _session_user() is None:
            return jsonify({"error": "Autenticação necessária."}), 401
        return view(*args, **kwargs)

    return wrapped


@auth_api.post("/login")
def login():
    if not authentication_ready():
        return _auth_not_configured()

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Envie login e senha em JSON."}), 400

    login_value = payload.get("login")
    password = payload.get("password")
    if not isinstance(login_value, str) or not isinstance(password, str):
        return jsonify({"error": "Login ou senha inválidos."}), 400
    if len(password) > 1024:
        return jsonify({"error": "Login ou senha inválidos."}), 400

    try:
        normalized_login = normalize_login(login_value)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not password:
        return jsonify({"error": "Login ou senha inválidos."}), 400

    attempt_key = _login_attempt_key(normalized_login)
    retry_after = login_attempt_limiter.retry_after(attempt_key, time.monotonic())
    if retry_after:
        return _login_rate_limited(retry_after)

    user = get_user_by_login(normalized_login)
    if (
        user is None
        or not user.get("active")
        or not check_password_hash(user["password_hash"], password)
    ):
        retry_after = login_attempt_limiter.record_failure(attempt_key, time.monotonic())
        if retry_after:
            return _login_rate_limited(retry_after)
        return jsonify({"error": "Login ou senha inválidos."}), 401

    login_attempt_limiter.record_success(attempt_key)
    session.clear()
    session.permanent = True
    session["user_id"] = int(user["id"])
    session["name"] = user["name"]
    session["login"] = user["login"]
    session["role"] = user["role"]
    return jsonify({
        "user": {
            "id": user["id"],
            "name": user["name"],
            "login": user["login"],
            "role": user["role"],
        }
    }), 200


@auth_api.get("/session")
def session_status():
    if not authentication_ready():
        return _auth_not_configured()
    user = _session_user()
    if user is None:
        return jsonify({"authenticated": False}), 200
    return jsonify({
        "authenticated": True,
        "user": user,
    }), 200


@auth_api.post("/logout")
def logout():
    if not authentication_ready():
        return _auth_not_configured()
    session.clear()
    return "", 204
