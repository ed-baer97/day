"""API-тесты пересобранного кабинета администратора платформы."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token, reset_auth_state
from app.config import get_settings
from app.domain.access import ROLE_STATION
from app.main import create_app
from app.services.batch_book import reset_batches
from app.services.catalog import reset_catalog
from app.services.device_ingest import reset_device_ingest
from app.services.station_accounts import reset_station_accounts

SEEDED_STATION = "a1111111-1111-1111-1111-111111111101"


@pytest.fixture(autouse=True)
def _clean():
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_station_accounts()
    reset_batches()
    yield
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_station_accounts()
    reset_batches()


def _admin_headers(client: TestClient) -> dict[str, str]:
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "lpg-admin"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_station_columns_mode_and_hidden_overview(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())
    admin_h = _admin_headers(client)

    # 1. Стартовая станция имеет виртуальный режим 2 колонки
    initial = client.get("/api/v1/stations", headers=admin_h).json()
    aktau = next(row for row in initial if row["code"] == "AGZS-AKT-12")
    assert aktau["columns_mode"] == "virtual"
    assert aktau["columns_count"] == 2

    # 2. Создаём скрытую станцию с режимом edge и 4 колонками
    created = client.post(
        "/api/v1/stations",
        json={
            "code": "AGZS-HID",
            "name": "Скрытая АГЗС",
            "address": "Актау, промзона",
            "lat": 43.68,
            "lon": 51.22,
            "is_active": False,
            "columns_mode": "edge",
            "columns_count": 4,
        },
        headers=admin_h,
    )
    assert created.status_code == 201
    hidden = created.json()
    assert hidden["columns_mode"] == "edge"
    assert hidden["columns_count"] == 4

    # 3. Добавляем резервуар, калибруем и шлём замер — публичная витрина скрытую не видит,
    #    но /stations/overview показывает её полностью с калибровкой и остатком.
    tank = client.post(
        f"/api/v1/stations/{hidden['id']}/devices",
        json={"code": "R-HID-1", "capacity_liters": 10000},
        headers=admin_h,
    ).json()

    cal = client.put(
        "/api/v1/ingest/calibration",
        json={
            "station_id": hidden["id"],
            "tank_id": tank["id"],
            "capacity_liters": 10000,
            "low_volts": 0.8,
            "low_percent": 0,
            "high_volts": 4.2,
            "high_percent": 100,
        },
        headers=admin_h,
    )
    assert cal.status_code == 200
    assert cal.json()["cal_low_volts"] == 0.8
    assert cal.json()["cal_high_volts"] == 4.2

    lvl = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": hidden["id"],
            "tank_id": tank["id"],
            "actual_remainder_liters": 6400,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source_event_id": "hid-lvl-1",
        },
        headers=admin_h,
    )
    assert lvl.status_code == 200

    public_codes = {row["code"] for row in client.get("/api/v1/public/levels").json()}
    assert "AGZS-HID" not in public_codes

    overview = client.get("/api/v1/stations/overview", headers=admin_h)
    assert overview.status_code == 200
    hid_ov = next(row for row in overview.json() if row["id"] == hidden["id"])
    assert hid_ov["is_active"] is False
    assert len(hid_ov["tanks"]) == 1
    assert hid_ov["tanks"][0]["calibrated"] is True
    assert hid_ov["tanks"][0]["cal_low_volts"] == 0.8
    assert hid_ov["tanks"][0]["cal_high_volts"] == 4.2
    assert hid_ov["tanks"][0]["actual_remainder_liters"] == 6400

    # 4. Переключаем колонки на АГЗС через PATCH
    patched = client.patch(
        f"/api/v1/stations/{SEEDED_STATION}",
        json={"columns_mode": "edge", "columns_count": 3},
        headers=admin_h,
    )
    assert patched.status_code == 200
    assert patched.json()["columns_mode"] == "edge"
    assert patched.json()["columns_count"] == 3

    # 5. Доступ к /stations/overview закрыт для станционной роли и анонимов
    assert client.get("/api/v1/stations/overview").status_code == 401
    station_token = issue_token(
        "aktau12",
        "test-secret",
        role=ROLE_STATION,
        station_id=__import__("uuid").UUID(SEEDED_STATION),
    )
    assert (
        client.get(
            "/api/v1/stations/overview",
            headers={"Authorization": f"Bearer {station_token}"},
        ).status_code
        == 403
    )


def test_rotate_tank_token_invalidates_old_token(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    monkeypatch.setenv("INGEST_TOKEN", "fallback-secret")
    get_settings.cache_clear()
    client = TestClient(create_app())
    admin_h = _admin_headers(client)

    tank = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/devices",
        json={"code": "R-ROT", "capacity_liters": 10000},
        headers=admin_h,
    ).json()
    old_token = tank["ingest_token"]

    rotated = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/devices/{tank['id']}/rotate-token",
        headers=admin_h,
    )
    assert rotated.status_code == 200
    new_token = rotated.json()["ingest_token"]
    assert new_token != old_token

    now = datetime.now(timezone.utc).isoformat()
    old_resp = client.post(
        "/api/v1/ingest/level",
        json={"actual_remainder_liters": 5000, "recorded_at": now, "source_event_id": "rot-1"},
        headers={"X-Device-Token": old_token},
    )
    assert old_resp.status_code == 401

    new_resp = client.post(
        "/api/v1/ingest/level",
        json={"actual_remainder_liters": 5000, "recorded_at": now, "source_event_id": "rot-2"},
        headers={"X-Device-Token": new_token},
    )
    assert new_resp.status_code == 200


def test_unified_owners_crud_and_existing_password_flag(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())
    admin_h = _admin_headers(client)

    second = client.post(
        "/api/v1/stations",
        json={
            "code": "AGZS-TWO",
            "name": "Вторая АГЗС",
            "lat": 43.7,
            "lon": 51.2,
            "is_active": True,
        },
        headers=admin_h,
    ).json()

    # 1. Создание владельца на первой АГЗС
    first_owner = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/users",
        json={"username": "boss", "password": "secret-password-1"},
        headers=admin_h,
    )
    assert first_owner.status_code == 201
    assert first_owner.json()["password_applied"] is True

    # 2. Привязка существующего логина ко второй АГЗС не перезаписывает пароль
    second_attach = client.post(
        f"/api/v1/stations/{second['id']}/users",
        json={"username": "boss", "password": "ignored-password"},
        headers=admin_h,
    )
    assert second_attach.status_code == 201
    assert second_attach.json()["password_applied"] is False
    assert second_attach.json()["password"] == ""

    # 3. Старый пароль по-прежнему работает
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "boss", "password": "secret-password-1"},
        ).status_code
        == 200
    )

    # 4. Единый реестр /owners видит обе станции, может сбросить пароль и отвязать станцию
    listed = client.get("/api/v1/owners", headers=admin_h).json()
    assert len(listed) == 1
    assert set(listed[0]["station_ids"]) == {SEEDED_STATION, second["id"]}

    patched = client.patch(
        "/api/v1/owners/boss",
        json={"station_ids": [second["id"]], "password": "new-password-2"},
        headers=admin_h,
    )
    assert patched.status_code == 200
    assert patched.json()["station_ids"] == [second["id"]]
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "boss", "password": "new-password-2"},
        ).status_code
        == 200
    )

    # 5. Отвязка последней станции удаляет владельца
    detached = client.delete(f"/api/v1/stations/{second['id']}/users/boss", headers=admin_h)
    assert detached.status_code == 204
    assert client.get("/api/v1/owners", headers=admin_h).json() == []


def test_batch_creation_trail_and_status_updates(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())
    admin_h = _admin_headers(client)

    created = client.post(
        "/api/v1/batches",
        json={"trail_code": "LPG-2026-999", "product_grade": "ПБТ", "volume_liters": 18000},
        headers=admin_h,
    )
    assert created.status_code == 201
    batch_id = created.json()["id"]

    trail = client.get("/api/v1/batches/by-code/LPG-2026-999/trail", headers=admin_h)
    assert trail.status_code == 200
    assert len(trail.json()["events"]) == 1
    assert trail.json()["events"][0]["node_type"] == "batch"

    status_upd = client.patch(
        f"/api/v1/batches/{batch_id}/status",
        json={"status": "in_transit", "note": "Выехал с ГПЗ"},
        headers=admin_h,
    )
    assert status_upd.status_code == 200
    assert status_upd.json()["status"] == "in_transit"

    ev_added = client.post(
        f"/api/v1/batches/{batch_id}/events",
        json={
            "node_type": "tank",
            "title": "Слив в R-1",
            "volume_liters": 9000,
            "status": "delivered",
        },
        headers=admin_h,
    )
    assert ev_added.status_code == 201
    assert ev_added.json()["batch"]["status"] == "delivered"
    assert len(ev_added.json()["events"]) == 3
