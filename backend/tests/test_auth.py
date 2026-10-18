"""Вход администратора закрывает учёт и оставляет открытыми публичные уровни."""

from fastapi.testclient import TestClient

from app.auth import issue_token, read_token
from app.config import get_settings
from app.main import create_app


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
