"""Приём уровня и отпуска без приборов."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services.device_ingest import reset_device_ingest

client = TestClient(create_app())

STATION = "a2222222-2222-2222-2222-222222222201"
TANK = "b2222222-2222-2222-2222-222222222201"
DISPENSER = "d2222222-2222-2222-2222-222222222201"


@pytest.fixture(autouse=True)
def _clean_store():
    reset_device_ingest()
    yield
    reset_device_ingest()


def test_opening_dispense_and_shortage():
    opened = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "actual_remainder_liters": 10000,
            "recorded_at": "2026-10-04T10:00:00Z",
            "source_event_id": "lvl-open",
        },
    )
    assert opened.status_code == 200
    body = opened.json()
    assert body["balance_status"] == "ok"
    assert body["delta_liters"] == 0
    assert body["calculated_remainder_liters"] == 10000

    sale = client.post(
        "/api/v1/ingest/dispense",
        json={
            "station_id": STATION,
            "dispenser_id": DISPENSER,
            "tank_id": TANK,
            "volume_liters": 400,
            "started_at": "2026-10-04T11:00:00Z",
            "external_txn_id": "topaz-1",
        },
    )
    assert sale.json()["calculated_remainder_liters"] == 9600
    assert sale.json()["balance_status"] == "surplus"

    again = client.post(
        "/api/v1/ingest/dispense",
        json={
            "station_id": STATION,
            "dispenser_id": DISPENSER,
            "tank_id": TANK,
            "volume_liters": 400,
            "started_at": "2026-10-04T11:00:00Z",
            "external_txn_id": "topaz-1",
        },
    )
    assert again.json()["duplicate"] is True
    assert again.json()["calculated_remainder_liters"] == 9600

    measured = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "actual_remainder_liters": 9000,
            "recorded_at": "2026-10-04T12:00:00Z",
            "source_event_id": "lvl-2",
        },
    )
    assert measured.json()["balance_status"] == "shortage"
    assert measured.json()["delta_liters"] == -600


def test_volts_need_calibration_then_convert():
    raw = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "volts": 2.5,
            "recorded_at": "2026-10-04T10:00:00Z",
            "source_event_id": "volt-1",
        },
    )
    assert raw.status_code == 422

    cal = client.put(
        "/api/v1/ingest/calibration",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "capacity_liters": 10000,
            "low_volts": 1.2,
            "low_percent": 20,
            "high_volts": 3.8,
            "high_percent": 80,
        },
    )
    assert cal.status_code == 200
    assert cal.json()["calibrated"] is True

    reading = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "volts": 2.5,
            "recorded_at": "2026-10-04T10:05:00Z",
            "source_event_id": "volt-1",
        },
    )
    assert reading.status_code == 200
    assert reading.json()["actual_remainder_liters"] == pytest.approx(5000)

    state = client.get(f"/api/v1/ingest/tanks/{TANK}")
    assert state.status_code == 200
    assert state.json()["opening_liters"] == pytest.approx(5000)
    assert state.json()["last_volts"] == 2.5


def test_receipt_moves_the_book():
    client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "actual_remainder_liters": 10000,
            "recorded_at": "2026-10-04T08:00:00Z",
            "source_event_id": "open",
        },
    )
    receipt = client.post(
        "/api/v1/ingest/receipt",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "volume_liters": 5000,
            "recorded_at": "2026-10-04T09:00:00Z",
            "source_event_id": "rcv-1",
        },
    )
    assert receipt.json()["calculated_remainder_liters"] == 15000

    client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "actual_remainder_liters": 14800,
            "recorded_at": "2026-10-04T09:30:00Z",
            "source_event_id": "after-rcv",
        },
    )
    state = client.get(f"/api/v1/ingest/tanks/{TANK}").json()
    assert state["delta_liters"] == pytest.approx(-200)
    assert state["balance_status"] == "shortage"


def test_level_without_reading_is_rejected():
    response = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "recorded_at": "2026-10-04T10:00:00Z",
        },
    )
    assert response.status_code == 422


def test_token_required_when_configured(monkeypatch):
    monkeypatch.setenv("INGEST_TOKEN", "secret")
    get_settings.cache_clear()
    try:
        payload = {
            "station_id": STATION,
            "tank_id": TANK,
            "actual_remainder_liters": 1000,
            "recorded_at": "2026-10-04T10:00:00Z",
            "source_event_id": "tok-1",
        }
        denied = client.post("/api/v1/ingest/level", json=payload)
        assert denied.status_code == 401
        allowed = client.post(
            "/api/v1/ingest/level",
            json=payload,
            headers={"X-Device-Token": "secret"},
        )
        assert allowed.status_code == 200
    finally:
        get_settings.cache_clear()


def test_unknown_tank_status():
    assert client.get(f"/api/v1/ingest/tanks/{uuid4()}").status_code == 404


def test_site_tank_card_sets_volume_and_token():
    station = "a1111111-1111-1111-1111-111111111101"
    created = client.post(
        f"/api/v1/stations/{station}/devices",
        json={"code": "R-9", "capacity_liters": 10000},
    )
    assert created.status_code == 201
    body = created.json()
    token = body["ingest_token"]
    tank_id = body["id"]
    assert body["level_path"] == "/api/v1/ingest/level"

    duplicate = client.post(
        f"/api/v1/stations/{station}/devices",
        json={"code": "R-9", "capacity_liters": 8000},
    )
    assert duplicate.status_code == 409

    calibrated = client.put(
        "/api/v1/ingest/calibration",
        headers={"X-Device-Token": token},
        json={
            "capacity_liters": 1,
            "low_volts": 1.2,
            "low_percent": 20,
            "high_volts": 3.8,
            "high_percent": 80,
        },
    )
    assert calibrated.status_code == 200

    reading = client.post(
        "/api/v1/ingest/level",
        headers={"X-Device-Token": token},
        json={
            "volts": 2.5,
            "recorded_at": "2026-10-04T10:05:00Z",
            "source_event_id": "card-volt",
        },
    )
    assert reading.status_code == 200
    assert reading.json()["actual_remainder_liters"] == pytest.approx(5000)

    patched = client.patch(
        f"/api/v1/stations/{station}/devices/{tank_id}",
        json={"capacity_liters": 20000},
    )
    assert patched.status_code == 200

    again = client.post(
        "/api/v1/ingest/level",
        headers={"X-Device-Token": token},
        json={
            "volts": 2.5,
            "recorded_at": "2026-10-04T10:10:00Z",
            "source_event_id": "card-volt-2",
        },
    )
    assert again.status_code == 200
    assert again.json()["actual_remainder_liters"] == pytest.approx(10000)

    listed = client.get(f"/api/v1/stations/{station}/devices")
    assert listed.status_code == 200
    assert any(row["id"] == tank_id and row["capacity_liters"] == 20000 for row in listed.json())
