"""Тесты безопасности /api/v1/ingest/*: fail-closed приём, изоляция токенов, запрет AUTH_DISABLED-обхода."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import reset_auth_state
from app.config import get_settings
from app.domain.edge_release import generate_ed25519_keypair
from app.main import create_app
from app.services.catalog import create_station, create_truck, reset_catalog
from app.services.device_ingest import reset_device_ingest
from app.services.edge_fleet import reset_edge_fleet


def _setup_secure_client(monkeypatch, *, auth_disabled: str = "false") -> tuple[TestClient, dict[str, str]]:
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_edge_fleet()

    monkeypatch.setenv("AUTH_DISABLED", auth_disabled)
    monkeypatch.setenv("ALLOW_ANONYMOUS_INGEST", "false")
    monkeypatch.setenv("INGEST_TOKEN", "")
    monkeypatch.setenv("GPS_INGEST_TOKEN", "gps-secret-1")
    monkeypatch.setenv("AUTH_SECRET", "ingest-sec-test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()

    client = TestClient(create_app())
    token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "lpg-admin"}).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_empty_ingest_token_is_closed_and_auth_disabled_cannot_bypass(monkeypatch):
    client, admin_h = _setup_secure_client(monkeypatch, auth_disabled="true")
    now = datetime.now(timezone.utc).isoformat()
    sid = "a1111111-1111-1111-1111-111111111101"
    tank = client.post(
        f"/api/v1/stations/{sid}/devices",
        json={"code": "R-SEC", "capacity_liters": 10000},
        headers=admin_h,
    ).json()

    # Без токена -> 401 даже при пустом INGEST_TOKEN
    assert (
        client.post(
            "/api/v1/ingest/level",
            json={"station_id": sid, "tank_id": tank["id"], "actual_remainder_liters": 5000, "recorded_at": now},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/ingest/dispense",
            json={"station_id": sid, "dispenser_id": str(uuid4()), "tank_id": tank["id"], "volume_liters": 10, "started_at": now},
        ).status_code
        == 401
    )
    assert (
        client.get(f"/api/v1/ingest/tanks/{tank['id']}").status_code == 401
    )

    # При AUTH_DISABLED=true поддельный Authorization НЕ открывает ingest
    forged_h = {"Authorization": "Bearer forged-not-a-valid-token"}
    assert (
        client.post(
            "/api/v1/ingest/level",
            headers=forged_h,
            json={"station_id": sid, "tank_id": tank["id"], "actual_remainder_liters": 5000, "recorded_at": now},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/ingest/gps",
            headers=forged_h,
            json={"truck_id": str(uuid4()), "lat": 43.6, "lon": 51.2, "recorded_at": now},
        ).status_code
        == 401
    )
    assert (
        client.get("/api/v1/ingest/edge/release", headers=forged_h).status_code == 401
    )


def test_tank_token_is_least_privilege_and_binds_edge_station_scope(monkeypatch):
    client, admin_h = _setup_secure_client(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    sid1 = "a1111111-1111-1111-1111-111111111101"
    st2 = create_station(code="AGZS-FOREIGN", name="Чужая АГЗС", address=None, lat=43.7, lon=51.2, is_active=True)

    tank1 = client.post(
        f"/api/v1/stations/{sid1}/devices",
        json={"code": "R-1", "capacity_liters": 10000},
        headers=admin_h,
    ).json()
    tank2 = client.post(
        f"/api/v1/stations/{st2.id}/devices",
        json={"code": "R-2", "capacity_liters": 10000},
        headers=admin_h,
    ).json()
    tok1_h = {"X-Device-Token": tank1["ingest_token"]}

    truck = create_truck(plate_number="SEC 01", capacity_liters=15000, carrier_name=None, status="in_transit", lat=None, lon=None)

    # 1. Токен резервуара не может калибровать, проводить приёмку, читать чужой резервуар или слать GPS газовоза
    assert (
        client.put(
            "/api/v1/ingest/calibration",
            headers=tok1_h,
            json={"low_volts": 1.0, "low_percent": 10, "high_volts": 4.0, "high_percent": 90},
        ).status_code
        in (401, 403)
    )
    assert (
        client.post(
            "/api/v1/ingest/receipt",
            headers=tok1_h,
            json={"station_id": sid1, "tank_id": tank1["id"], "volume_liters": 500, "recorded_at": now},
        ).status_code
        in (401, 403)
    )
    assert client.get(f"/api/v1/ingest/tanks/{tank2['id']}", headers=tok1_h).status_code == 403
    assert (
        client.post(
            "/api/v1/ingest/gps",
            headers=tok1_h,
            json={"truck_id": str(truck.id), "lat": 43.6, "lon": 51.2, "recorded_at": now},
        ).status_code
        == 403
    )

    # 2. GPS с отдельным GPS_INGEST_TOKEN принимается
    gps_ok = client.post(
        "/api/v1/ingest/gps",
        headers={"X-Device-Token": "gps-secret-1"},
        json={"truck_id": str(truck.id), "lat": 43.65, "lon": 51.15, "recorded_at": now, "source_event_id": "g-1"},
    )
    assert gps_ok.status_code == 200

    # 3. Токен резервуара 1 не может отметить heartbeat/релиз под чужим кодом станции или чужим station_id
    priv_hex, _pub_hex = generate_ed25519_keypair()
    monkeypatch.setenv("EDGE_RELEASE_PRIVATE_KEY", priv_hex)
    get_settings.cache_clear()
    client.put(
        "/api/v1/ingest/edge/release",
        headers=admin_h,
        json={"version": "0.8.0", "artifact_url": "/releases/a.whl", "sha256": "a" * 64, "channel": "ring0"},
        params={"canary_stations": ["AGZS-FOREIGN"]},
    )

    assert (
        client.get(
            "/api/v1/ingest/edge/release?station_code=AGZS-FOREIGN&current_version=0.1.0",
            headers=tok1_h,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/ingest/edge/heartbeat",
            headers=tok1_h,
            json={"station_code": "AGZS-FOREIGN", "current_version": "0.1.0"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/ingest/edge/heartbeat",
            headers=tok1_h,
            json={"station_code": "AGZS-AKT-12", "station_id": str(st2.id), "current_version": "0.1.0"},
        ).status_code
        == 403
    )

    # 4. При честном запросе без подмены токен автоматически привязывается к своей станции AGZS-AKT-12 (ring2, а не чужой ring0!)
    rel_own = client.get("/api/v1/ingest/edge/release?current_version=0.1.0", headers=tok1_h)
    assert rel_own.status_code == 200
    assert rel_own.json()["published"] is False  # в ring2 для AGZS-AKT-12 релиз ещё не выкачен

    hb_own = client.post(
        "/api/v1/ingest/edge/heartbeat",
        headers=tok1_h,
        json={"station_code": "AGZS-AKT-12", "current_version": "0.1.0", "outbox_pending": 2},
    )
    assert hb_own.status_code == 200
    fleet = client.get("/api/v1/ingest/edge/fleet", headers=admin_h).json()
    assert len(fleet["nodes"]) == 1
    assert fleet["nodes"][0]["station_code"] == "AGZS-AKT-12"
    assert fleet["nodes"][0]["station_id"] == sid1

    # 5. Налив по токену 1 в чужой station_id/tank_id отклонён с 403, а в свой принят
    assert (
        client.post(
            "/api/v1/ingest/dispense",
            headers=tok1_h,
            json={
                "station_id": str(st2.id),
                "dispenser_id": str(uuid4()),
                "tank_id": tank2["id"],
                "volume_liters": 20.0,
                "started_at": now,
                "external_txn_id": "forged-d-1",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/ingest/level",
            headers=tok1_h,
            json={"actual_remainder_liters": 4000.0, "recorded_at": now, "source_event_id": "ok-lvl-1"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/ingest/dispense",
            headers=tok1_h,
            json={
                "station_id": sid1,
                "dispenser_id": str(uuid4()),
                "volume_liters": 20.0,
                "started_at": now,
                "external_txn_id": "ok-disp-1",
            },
        ).status_code
        == 200
    )
