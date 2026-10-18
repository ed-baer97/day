"""Публичная заполненность не отдаёт ключи и сверку."""

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.catalog import reset_catalog
from app.services.device_ingest import reset_device_ingest

client = TestClient(create_app())
STATION = "a1111111-1111-1111-1111-111111111101"


def setup_function():
    reset_catalog()
    reset_device_ingest()


def test_public_level_is_fill_only():
    created = client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": "R-1", "capacity_liters": 10000},
    )
    assert created.status_code == 201
    tank_id = created.json()["id"]

    posted = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": tank_id,
            "actual_remainder_liters": 1500,
            "recorded_at": "2026-10-18T08:50:00Z",
            "source_event_id": "public-15",
        },
    )
    assert posted.status_code == 200

    listed = client.get("/api/v1/public/levels")
    assert listed.status_code == 200
    body = listed.text
    assert "ingest_token" not in body
    assert "balance_status" not in body
    assert "delta" not in body

    station = next(row for row in listed.json() if row["code"] == "AGZS-AKT-12")
    tank = station["tanks"][0]
    assert tank["code"] == "R-1"
    assert tank["fill_percent"] == 15
    assert tank["remainder_liters"] == 1500
    assert tank["capacity_liters"] == 10000
    assert tank["measured_at"] is not None


def test_tank_without_reading_stays_empty():
    client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": "R-2", "capacity_liters": 8000},
    )
    station = next(row for row in client.get("/api/v1/public/levels").json() if row["code"] == "AGZS-AKT-12")
    tank = station["tanks"][0]
    assert tank["fill_percent"] is None
    assert tank["remainder_liters"] is None
    assert tank["measured_at"] is None
