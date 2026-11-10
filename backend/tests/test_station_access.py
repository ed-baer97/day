"""Пользователь станции не читает чужой токен."""

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token, reset_auth_state
from app.config import get_settings
from app.domain.access import ROLE_ADMIN, ROLE_STATION
from app.main import create_app
from app.services.catalog import create_station, reset_catalog
from app.services.device_ingest import reset_device_ingest
from app.services.station_accounts import reset_station_accounts

STATION = "a1111111-1111-1111-1111-111111111101"
OTHER = "a1111111-1111-1111-1111-111111111199"


@pytest.fixture(autouse=True)
def _clean():
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_station_accounts()
    yield
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_station_accounts()


def test_station_token_sees_own_devices_only(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())

    admin = client.post("/api/v1/auth/login", json={"username": "admin", "password": "lpg-admin"}).json()["token"]
    admin_h = {"Authorization": f"Bearer {admin}"}
    created = client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": "R-1", "capacity_liters": 10000},
        headers=admin_h,
    )
    assert created.status_code == 201
    token_value = created.json()["ingest_token"]
    assert token_value

    station_token = issue_token(
        "aktau12",
        "test-secret",
        role=ROLE_STATION,
        station_id=__import__("uuid").UUID(STATION),
    )
    own = client.get(f"/api/v1/stations/{STATION}/devices", headers={"Authorization": f"Bearer {station_token}"})
    assert own.status_code == 200
    assert own.json()[0]["ingest_token"] == token_value

    foreign = client.get(
        f"/api/v1/stations/{OTHER}/devices",
        headers={"Authorization": f"Bearer {station_token}"},
    )
    assert foreign.status_code in (403, 404)

    listed = client.get("/api/v1/stations", headers={"Authorization": f"Bearer {station_token}"})
    assert listed.status_code == 200
    assert {row["id"] for row in listed.json()} == {STATION}


def test_station_cannot_change_catalog(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())
    station_token = issue_token("aktau12", "test-secret", role=ROLE_STATION, station_id=__import__("uuid").UUID(STATION))
    headers = {"Authorization": f"Bearer {station_token}"}

    created = client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": "R-9", "capacity_liters": 1000},
        headers=headers,
    )
    assert created.status_code == 403
    assert client.get("/api/v1/trucks", headers=headers).status_code == 403
    assert client.get("/api/v1/map/overview", headers=headers).status_code == 403
    patched = client.patch(
        f"/api/v1/stations/{STATION}",
        json={"name": "чужое имя"},
        headers=headers,
    )
    assert patched.status_code == 403
    assert client.get("/api/v1/public/levels").status_code == 200
    assert client.get("/api/v1/stations").status_code == 401


def test_owner_login_sees_only_own_station(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())
    admin = client.post("/api/v1/auth/login", json={"username": "admin", "password": "lpg-admin"}).json()
    assert admin["role"] == "admin"
    assert admin["station_id"] is None
    admin_h = {"Authorization": f"Bearer {admin['token']}"}

    created = client.post(
        f"/api/v1/stations/{STATION}/users",
        json={"username": "rekowner", "password": "owner-pass"},
        headers=admin_h,
    )
    assert created.status_code == 201
    listed = client.get(f"/api/v1/stations/{STATION}/users", headers=admin_h)
    assert listed.status_code == 200
    assert listed.json()[0]["username"] == "rekowner"

    owner = client.post("/api/v1/auth/login", json={"username": "rekowner", "password": "owner-pass"})
    assert owner.status_code == 200
    body = owner.json()
    assert body["role"] == "owner"
    assert body["station_id"] == STATION
    assert body["station_ids"] == [STATION]
    owner_h = {"Authorization": f"Bearer {body['token']}"}

    stations = client.get("/api/v1/stations", headers=owner_h)
    assert stations.status_code == 200
    assert {row["id"] for row in stations.json()} == {STATION}
    assert client.get("/api/v1/trucks", headers=owner_h).status_code == 403
    assert client.get("/api/v1/map/overview", headers=owner_h).status_code == 403
    assert client.post(
        f"/api/v1/stations/{STATION}/users",
        json={"username": "second", "password": "owner-pass"},
        headers=owner_h,
    ).status_code == 403


def test_owner_can_be_attached_to_multiple_stations(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()

    second_station = create_station(
        code="AGZS-SECOND",
        name="Вторая АГЗС",
        address=None,
        lat=43.7,
        lon=51.2,
        is_active=True,
    )

    client = TestClient(create_app())
    admin = client.post("/api/v1/auth/login", json={"username": "admin", "password": "lpg-admin"}).json()
    admin_h = {"Authorization": f"Bearer {admin['token']}"}
    assert client.post(
        f"/api/v1/stations/{STATION}/users",
        json={"username": "multi", "password": "owner-pass"},
        headers=admin_h,
    ).status_code == 201
    attached = client.post(
        f"/api/v1/stations/{second_station.id}/users",
        json={"username": "multi", "password": "owner-pass"},
        headers=admin_h,
    )
    assert attached.status_code == 201
    assert attached.json()["kind"] == "owner"

    owner = client.post("/api/v1/auth/login", json={"username": "multi", "password": "owner-pass"}).json()
    assert owner["role"] == "owner"
    assert set(owner["station_ids"]) == {STATION, str(second_station.id)}
    owner_h = {"Authorization": f"Bearer {owner['token']}"}
    assert {row["id"] for row in client.get("/api/v1/stations", headers=owner_h).json()} == {
        STATION,
        str(second_station.id),
    }


def test_login_response_includes_role(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    get_settings.cache_clear()
    client = TestClient(create_app())
    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "lpg-admin"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["role"] == ROLE_ADMIN
    assert body["station_id"] is None
