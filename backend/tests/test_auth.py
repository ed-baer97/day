"""Вход администратора закрывает учёт и оставляет открытыми публичные уровни."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import (
    check_login_rate_limit,
    issue_token,
    read_token,
    record_login_failure,
    reset_auth_state,
    revoke_token,
)
from app.config import get_settings
from app.main import create_app
from app.services.shelly_link import normalize_host


@pytest.fixture(autouse=True)
def _clean_auth():
    reset_auth_state()
    yield
    reset_auth_state()


def test_login_opens_internal_routes(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    get_settings.cache_clear()
    client = TestClient(create_app())

    assert client.get("/api/v1/stations").status_code == 401
    assert client.get("/api/v1/public/levels").status_code == 200
    assert client.get("/health").status_code == 200

    wrong = client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    assert wrong.status_code == 401

    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "lpg-admin"})
    assert ok.status_code == 200
    token = ok.json()["token"]
    assert ok.json()["username"] == "admin"

    opened = client.get("/api/v1/stations", headers={"Authorization": f"Bearer {token}"})
    assert opened.status_code == 200

    stale = client.get("/api/v1/map/overview", headers={"Authorization": "Bearer not-a-token"})
    assert stale.status_code == 401


def test_expired_token_is_rejected():
    assert read_token(issue_token("admin", "test-secret", ttl_seconds=-5), "test-secret") is None
    assert read_token(issue_token("admin", "test-secret", ttl_seconds=60), "other-secret") is None


def test_revoked_token_is_rejected():
    token = issue_token("admin", "test-secret", ttl_seconds=60)
    assert read_token(token, "test-secret") == "admin"
    revoke_token(token)
    assert read_token(token, "test-secret") is None


def test_rate_limit_blocks_brute_force():
    for _ in range(5):
        check_login_rate_limit("127.0.0.1:admin")
        record_login_failure("127.0.0.1:admin")
    with pytest.raises(HTTPException) as exc:
        check_login_rate_limit("127.0.0.1:admin")
    assert exc.value.status_code == 429


def test_ssrf_hosts_rejected():
    for forbidden in ("localhost", "127.0.0.1", "169.254.169.254", "0.0.0.0", "db:5432"):
        with pytest.raises(HTTPException) as exc:
            normalize_host(forbidden)
        assert exc.value.status_code == 422
    assert normalize_host("192.168.0.104") == "192.168.0.104"
