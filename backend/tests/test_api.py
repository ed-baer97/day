"""API smoke tests with in-memory demo data."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_map_overview():
    r = client.get("/api/v1/map/overview")
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) >= 3
    kinds = {p["kind"] for p in body["points"]}
    assert "station" in kinds and "truck" in kinds and "factory" in kinds


def test_batch_trail():
    r = client.get("/api/v1/batches/by-code/LPG-2026-00041/trail")
    assert r.status_code == 200
    body = r.json()
    assert body["batch"]["trail_code"] == "LPG-2026-00041"
    assert len(body["events"]) >= 1


def test_reconcile_creates_shortage_event():
    from datetime import datetime, timezone

    payload = {
        "station_id": "a1111111-1111-1111-1111-111111111101",
        "tank_id": "b1111111-1111-1111-1111-111111111101",
        "period_start": datetime.now(timezone.utc).isoformat(),
        "period_end": datetime.now(timezone.utc).isoformat(),
        "previous_remainder_liters": 10000,
        "receipts_liters": 0,
        "dispense_liters": 0,
        "actual_remainder_liters": 9700,
    }
    r = client.post("/api/v1/balance/reconcile", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "shortage"


def test_ingest_dispense_idempotent():
    payload = {
        "station_id": "a1111111-1111-1111-1111-111111111101",
        "dispenser_id": "d1111111-1111-1111-1111-111111111201",
        "volume_liters": 40.5,
        "started_at": "2026-09-26T12:00:00Z",
        "external_txn_id": "txn-demo-1",
    }
    a = client.post("/api/v1/ingest/dispense", json=payload)
    b = client.post("/api/v1/ingest/dispense", json=payload)
    assert a.json()["accepted"] is True
    assert b.json()["duplicate"] is True
