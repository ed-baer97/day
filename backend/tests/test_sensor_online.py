"""Витрина помечает молчащий датчик."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services.catalog import reset_catalog
from app.services.device_ingest import reset_device_ingest, tank_remainder

client = TestClient(create_app())
STATION = "a1111111-1111-1111-1111-111111111101"


def setup_function():
    reset_catalog()
    reset_device_ingest()
    get_settings.cache_clear()


def test_fresh_reading_is_online(monkeypatch):
    monkeypatch.setenv("SENSOR_STALE_SECONDS", "60")
    get_settings.cache_clear()
    created = client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": "R-1", "capacity_liters": 10000},
    )
    tank_id = created.json()["id"]
    now = datetime.now(timezone.utc).isoformat()
    client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": tank_id,
            "actual_remainder_liters": 5000,
            "recorded_at": now,
            "source_event_id": "online-1",
        },
    )
    tank = client.get("/api/v1/public/levels").json()[0]["tanks"][0]
    assert tank["online"] is True
    assert tank["fill_percent"] == 50


def test_stale_reading_is_offline(monkeypatch):
    monkeypatch.setenv("SENSOR_STALE_SECONDS", "60")
    get_settings.cache_clear()
    created = client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": "R-1", "capacity_liters": 10000},
    )
    tank_id = created.json()["id"]
    now = datetime.now(timezone.utc).isoformat()
    client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": tank_id,
            "actual_remainder_liters": 5000,
            "recorded_at": now,
            "source_event_id": "stale-1",
        },
    )
    # Молчание датчика: последний приём на сервере был давно.
    from uuid import UUID

    from app.services import device_ingest

    tank_uuid = UUID(tank_id)
    with device_ingest._lock:
        for book in device_ingest._books.values():
            if book.tank_id == tank_uuid:
                book.last_measured_at = datetime.now(timezone.utc) - timedelta(minutes=5)
                break
    remainder, measured = tank_remainder(tank_uuid)
    assert remainder == 5000
    assert measured is not None
    tank = client.get("/api/v1/public/levels").json()[0]["tanks"][0]
    assert tank["online"] is False
    assert tank["fill_percent"] == 50
