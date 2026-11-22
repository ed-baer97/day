"""Комплексные тесты ролевой модели (Администратор / Владелец / Кассир) и кассовых смен."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import reset_auth_state
from app.config import get_settings
from app.domain.access import ROLE_ADMIN, ROLE_CASHIER, ROLE_OWNER
from app.domain.entities import ShiftColumnSummary, ShiftTankSnapshot
from app.domain.shifts import (
    ShiftDispenseSample,
    compute_shift_balance,
    summarize_shift_columns,
)
from app.main import create_app
from app.models.shift import StationShiftRecord
from app.models.station import Station, StationUser
from app.services import boot, postgres_account
from app.services.batch_book import reset_batches
from app.services.catalog import reset_catalog
from app.services.device_ingest import reset_device_ingest
from app.services.shelly_link import reset_shelly_links
from app.services.shift_book import reset_shifts
from app.services.station_accounts import reset_station_accounts

SEEDED_STATION = "a1111111-1111-1111-1111-111111111101"


@pytest.fixture(autouse=True)
def _clean():
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_shelly_links()
    reset_station_accounts()
    reset_shifts()
    reset_batches()
    yield
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_shelly_links()
    reset_station_accounts()
    reset_shifts()
    reset_batches()


def _login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_domain_shift_columns_and_balance():
    t0 = datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc)
    samples = [
        ShiftDispenseSample(pump_address=1, volume_liters=25.5, price_kzt_per_liter=75.0, occurred_at=t0),
        ShiftDispenseSample(
            pump_address=2,
            volume_liters=40.0,
            price_kzt_per_liter=75.0,
            occurred_at=t0 + timedelta(minutes=10),
        ),
        ShiftDispenseSample(
            pump_address=3,
            volume_liters=14.5,
            price_kzt_per_liter=80.0,
            occurred_at=t0 + timedelta(minutes=20),
        ),
    ]
    # Configured for 2 columns, but actual dispense happened on pump 3 -> includes column 3 cleanly
    columns, total_liters, total_ops, total_amount = summarize_shift_columns(samples, columns_count=2)
    assert [c.pump_address for c in columns] == [1, 2, 3]
    assert columns[0].volume_liters == pytest.approx(25.5)
    assert columns[1].volume_liters == pytest.approx(40.0)
    assert columns[2].volume_liters == pytest.approx(14.5)
    assert columns[2].amount_kzt == pytest.approx(1160.0)
    assert total_liters == pytest.approx(80.0)
    assert total_ops == 3
    assert total_amount == pytest.approx(25.5 * 75 + 40 * 75 + 14.5 * 80)

    # Zero columns and no dispenses -> empty list
    empty_cols, empty_vol, empty_ops, empty_amt = summarize_shift_columns([], columns_count=0)
    assert empty_cols == []
    assert empty_vol == 0.0
    assert empty_ops == 0
    assert empty_amt is None

    # Balance calculation with receipts
    tank_delta, discrepancy = compute_shift_balance(10000.0, 9600.0, 500.0, 890.0)
    assert tank_delta == pytest.approx(900.0)
    assert discrepancy == pytest.approx(-10.0)

    # Missing opening or closing tank reading returns (None, None)
    assert compute_shift_balance(None, 9600.0, 0.0, 100.0) == (None, None)
    assert compute_shift_balance(10000.0, None, 0.0, 100.0) == (None, None)


def test_full_three_role_rbac_isolation(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-roles")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())

    admin_session = _login(client, "admin", "lpg-admin")
    assert admin_session["role"] == ROLE_ADMIN
    admin_h = _auth_headers(admin_session["token"])

    # Admin creates 2 more stations (total 3 stations)
    st_b = client.post(
        "/api/v1/stations",
        json={
            "code": "AGZS-B",
            "name": "АГЗС Б",
            "lat": 43.7,
            "lon": 51.3,
            "is_active": True,
            "columns_mode": "edge",
            "columns_count": 2,
        },
        headers=admin_h,
    ).json()
    st_c = client.post(
        "/api/v1/stations",
        json={
            "code": "AGZS-C",
            "name": "АГЗС С",
            "lat": 43.8,
            "lon": 51.4,
            "is_active": True,
            "columns_mode": "edge",
            "columns_count": 2,
        },
        headers=admin_h,
    ).json()

    # Add tanks to stations A and B
    tank_a = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/devices",
        json={"code": "R-A1", "capacity_liters": 10000},
        headers=admin_h,
    ).json()
    client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": SEEDED_STATION,
            "tank_id": tank_a["id"],
            "actual_remainder_liters": 6200.0,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source_event_id": "rbac-lvl-a",
        },
        headers=admin_h,
    )
    client.post(
        f"/api/v1/stations/{st_b['id']}/devices",
        json={"code": "R-B1", "capacity_liters": 12000},
        headers=admin_h,
    )

    # Admin creates Owner A (attached to 2 stations) and Owner B (attached to 1 station)
    owner_a_res = client.post(
        "/api/v1/owners",
        json={
            "username": "owner_a",
            "password": "owner-a-pass",
            "station_ids": [SEEDED_STATION, st_b["id"]],
        },
        headers=admin_h,
    )
    assert owner_a_res.status_code == 201
    owner_b_res = client.post(
        "/api/v1/owners",
        json={
            "username": "owner_b",
            "password": "owner-b-pass",
            "station_ids": [st_c["id"]],
        },
        headers=admin_h,
    )
    assert owner_b_res.status_code == 201

    # Admin sees all 3 stations & overview, but CANNOT create cashiers or open shifts
    assert len(client.get("/api/v1/stations", headers=admin_h).json()) == 3
    assert len(client.get("/api/v1/stations/overview", headers=admin_h).json()) == 3
    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/cashiers",
            json={"username": "c_by_admin", "password": "cashier-pass-1"},
            headers=admin_h,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/shifts/open",
            headers=admin_h,
        ).status_code
        == 403
    )

    # Owner A logs in
    owner_a_login = _login(client, "owner_a", "owner-a-pass")
    assert owner_a_login["role"] == ROLE_OWNER
    assert set(owner_a_login["station_ids"]) == {SEEDED_STATION, st_b["id"]}
    owner_a_h = _auth_headers(owner_a_login["token"])

    # Owner A sees only their 2 stations, can inspect detail/tanks/state/dispenses, NOT foreign station or admin routes
    owner_stations = client.get("/api/v1/stations", headers=owner_a_h).json()
    assert {row["id"] for row in owner_stations} == {SEEDED_STATION, st_b["id"]}
    assert client.get(f"/api/v1/stations/{SEEDED_STATION}", headers=owner_a_h).status_code == 200
    assert client.get(f"/api/v1/stations/{st_b['id']}", headers=owner_a_h).status_code == 200
    assert (
        client.get(
            f"/api/v1/stations/{SEEDED_STATION}/devices/{tank_a['id']}/state",
            headers=owner_a_h,
        ).status_code
        == 200
    )
    owner_devs = client.get(f"/api/v1/stations/{SEEDED_STATION}/devices", headers=owner_a_h).json()
    assert owner_devs[0]["ingest_token"] is None
    assert client.get(f"/api/v1/stations/{SEEDED_STATION}/dispenses", headers=owner_a_h).status_code == 200

    assert client.get(f"/api/v1/stations/{st_c['id']}", headers=owner_a_h).status_code == 403
    assert client.get("/api/v1/owners", headers=owner_a_h).status_code == 403
    assert client.get("/api/v1/stations/overview", headers=owner_a_h).status_code == 403
    assert client.get("/api/v1/trucks", headers=owner_a_h).status_code == 403
    assert client.get("/api/v1/map/overview", headers=owner_a_h).status_code == 403
    assert client.get("/api/v1/batches", headers=owner_a_h).status_code == 403
    assert client.get("/api/v1/events", headers=owner_a_h).status_code == 403

    # Owner A creates cashiers on both of their stations, cannot create on Owner B's station
    c1 = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/cashiers",
        json={"username": "cashier_a1", "password": "cashier-pass-1"},
        headers=owner_a_h,
    )
    assert c1.status_code == 201
    assert c1.json()["kind"] == "cashier"
    assert c1.json()["station_id"] == SEEDED_STATION

    c2 = client.post(
        f"/api/v1/stations/{st_b['id']}/cashiers",
        json={"username": "cashier_b1", "password": "cashier-pass-2"},
        headers=owner_a_h,
    )
    assert c2.status_code == 201

    assert (
        client.post(
            f"/api/v1/stations/{st_c['id']}/cashiers",
            json={"username": "cashier_c_bad", "password": "cashier-pass-3"},
            headers=owner_a_h,
        ).status_code
        == 403
    )

    # Owner B creates a cashier on station C; Owner A cannot see Owner B's cashiers in /cashiers
    owner_b_login = _login(client, "owner_b", "owner-b-pass")
    owner_b_h = _auth_headers(owner_b_login["token"])
    assert (
        client.post(
            f"/api/v1/stations/{st_c['id']}/cashiers",
            json={"username": "cashier_c1", "password": "cashier-pass-c"},
            headers=owner_b_h,
        ).status_code
        == 201
    )

    owner_a_cashiers = client.get("/api/v1/cashiers", headers=owner_a_h).json()
    assert {row["username"] for row in owner_a_cashiers} == {"cashier_a1", "cashier_b1"}
    assert len(client.get("/api/v1/cashiers", headers=admin_h).json()) == 3

    # Owner A updates cashier password and moves cashier_b1 to station A, then back, cannot move to st_c
    patched_c = client.patch(
        f"/api/v1/stations/{st_b['id']}/cashiers/cashier_b1",
        json={"password": "cashier-pass-22", "station_id": SEEDED_STATION},
        headers=owner_a_h,
    )
    assert patched_c.status_code == 200
    assert patched_c.json()["station_id"] == SEEDED_STATION
    assert (
        client.patch(
            f"/api/v1/stations/{SEEDED_STATION}/cashiers/cashier_b1",
            json={"station_id": st_c["id"]},
            headers=owner_a_h,
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/stations/{SEEDED_STATION}/cashiers/cashier_b1",
            headers=owner_a_h,
        ).status_code
        == 204
    )

    # Owner A cannot open shift
    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/shifts/open",
            headers=owner_a_h,
        ).status_code
        == 403
    )

    # Global username uniqueness: cashier cannot take admin or owner username; owner cannot take cashier username
    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/cashiers",
            json={"username": "admin", "password": "cashier-pass-x"},
            headers=owner_a_h,
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/cashiers",
            json={"username": "owner_a", "password": "cashier-pass-x"},
            headers=owner_a_h,
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/owners",
            json={"username": "cashier_a1", "password": "owner-pass-x", "station_ids": [SEEDED_STATION]},
            headers=admin_h,
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/users",
            json={"username": "cashier_a1", "password": "owner-pass-x"},
            headers=admin_h,
        ).status_code
        == 409
    )

    # Cashier logs in and is strictly isolated to SEEDED_STATION
    cashier_login = _login(client, "cashier_a1", "cashier-pass-1")
    assert cashier_login["role"] == ROLE_CASHIER
    assert cashier_login["station_id"] == SEEDED_STATION
    assert cashier_login["station_ids"] == [SEEDED_STATION]
    cashier_h = _auth_headers(cashier_login["token"])

    assert {row["id"] for row in client.get("/api/v1/stations", headers=cashier_h).json()} == {
        SEEDED_STATION
    }
    assert client.get(f"/api/v1/stations/{SEEDED_STATION}/tanks", headers=cashier_h).status_code == 200
    c_devs = client.get(f"/api/v1/stations/{SEEDED_STATION}/devices", headers=cashier_h).json()
    assert c_devs[0]["ingest_token"] is None
    assert (
        client.get(
            f"/api/v1/stations/{SEEDED_STATION}/devices/{tank_a['id']}/state",
            headers=cashier_h,
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/stations/{SEEDED_STATION}/dispenses", headers=cashier_h).status_code == 200

    # Cashier is denied on foreign station, staff management, and admin endpoints
    assert client.get(f"/api/v1/stations/{st_b['id']}/tanks", headers=cashier_h).status_code == 403
    assert client.get("/api/v1/cashiers", headers=cashier_h).status_code == 403
    assert client.get(f"/api/v1/stations/{SEEDED_STATION}/cashiers", headers=cashier_h).status_code == 403
    assert client.get("/api/v1/owners", headers=cashier_h).status_code == 403
    assert client.get("/api/v1/stations/overview", headers=cashier_h).status_code == 403
    assert client.get("/api/v1/trucks", headers=cashier_h).status_code == 403
    assert client.get("/api/v1/map/overview", headers=cashier_h).status_code == 403


def test_cashier_shift_lifecycle_report_and_persistence(tmp_path, monkeypatch):
    state_file = tmp_path / "roles_shifts_state.json"
    monkeypatch.setenv("STATE_PATH", str(state_file))
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-shifts")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())

    admin_h = _auth_headers(_login(client, "admin", "lpg-admin")["token"])

    # Create second station for foreign owner check
    other_station = client.post(
        "/api/v1/stations",
        json={"code": "AGZS-OTHER", "name": "Чужая АГЗС", "lat": 43.9, "lon": 51.5, "is_active": True},
        headers=admin_h,
    ).json()

    # Tank on SEEDED_STATION starts at 8000 L
    tank = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/devices",
        json={"code": "R-SHIFT", "capacity_liters": 10000},
        headers=admin_h,
    ).json()
    t0 = datetime.now(timezone.utc)
    assert (
        client.post(
            "/api/v1/ingest/level",
            json={
                "station_id": SEEDED_STATION,
                "tank_id": tank["id"],
                "actual_remainder_liters": 8000.0,
                "recorded_at": t0.isoformat(),
                "source_event_id": "shift-lvl-open",
            },
            headers=admin_h,
        ).status_code
        == 200
    )

    # Create owners & cashier
    client.post(
        "/api/v1/owners",
        json={"username": "own_shift", "password": "owner-shift-pass", "station_ids": [SEEDED_STATION]},
        headers=admin_h,
    )
    client.post(
        "/api/v1/owners",
        json={"username": "own_other", "password": "owner-other-pass", "station_ids": [other_station["id"]]},
        headers=admin_h,
    )
    owner_h = _auth_headers(_login(client, "own_shift", "owner-shift-pass")["token"])
    other_owner_h = _auth_headers(_login(client, "own_other", "owner-other-pass")["token"])

    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/cashiers",
            json={"username": "cashier_s", "password": "cashier-shift-pass"},
            headers=owner_h,
        ).status_code
        == 201
    )
    cashier_h = _auth_headers(_login(client, "cashier_s", "cashier-shift-pass")["token"])

    # No shift initially
    cur_empty = client.get(f"/api/v1/stations/{SEEDED_STATION}/shifts/current", headers=cashier_h)
    assert cur_empty.status_code == 200
    assert cur_empty.json() is None

    # Cashier opens shift
    opened = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/shifts/open",
        json={"note": "Утренняя смена"},
        headers=cashier_h,
    )
    assert opened.status_code == 201
    shift_id = opened.json()["id"]
    assert opened.json()["status"] == "open"
    assert opened.json()["opened_by"] == "cashier_s"
    assert opened.json()["opening_tank_liters"] == pytest.approx(8000.0)

    # Concurrent open returns 409
    assert (
        client.post(f"/api/v1/stations/{SEEDED_STATION}/shifts/open", headers=cashier_h).status_code
        == 409
    )

    # Ingest 2 dispenses (40 L col 1, 60 L col 2 @ 75 KZT/L), 1 receipt (+500 L), and new tank level (8390 L)
    t1 = datetime.now(timezone.utc)
    assert (
        client.post(
            "/api/v1/ingest/dispense",
            json={
                "station_id": SEEDED_STATION,
                "tank_id": tank["id"],
                "dispenser_id": str(uuid4()),
                "volume_liters": 40.0,
                "started_at": t1.isoformat(),
                "finished_at": t1.isoformat(),
                "external_txn_id": "sh-disp-1",
                "raw_payload": json.dumps({"pump_address": 1, "mode": "dose", "price_kzt_per_liter": 75}),
            },
            headers=admin_h,
        ).status_code
        == 200
    )
    t2 = datetime.now(timezone.utc)
    assert (
        client.post(
            "/api/v1/ingest/dispense",
            json={
                "station_id": SEEDED_STATION,
                "tank_id": tank["id"],
                "dispenser_id": str(uuid4()),
                "volume_liters": 60.0,
                "started_at": t2.isoformat(),
                "finished_at": t2.isoformat(),
                "external_txn_id": "sh-disp-2",
                "raw_payload": json.dumps({"pump_address": 2, "mode": "full_tank", "price_kzt_per_liter": 75}),
            },
            headers=admin_h,
        ).status_code
        == 200
    )
    t3 = datetime.now(timezone.utc)
    assert (
        client.post(
            "/api/v1/ingest/receipt",
            json={
                "station_id": SEEDED_STATION,
                "tank_id": tank["id"],
                "volume_liters": 500.0,
                "recorded_at": t3.isoformat(),
                "source_event_id": "sh-rec-1",
            },
            headers=admin_h,
        ).status_code
        == 200
    )
    t4 = datetime.now(timezone.utc)
    assert (
        client.post(
            "/api/v1/ingest/level",
            json={
                "station_id": SEEDED_STATION,
                "tank_id": tank["id"],
                "actual_remainder_liters": 8390.0,
                "recorded_at": t4.isoformat(),
                "source_event_id": "shift-lvl-close",
            },
            headers=admin_h,
        ).status_code
        == 200
    )

    # Check live hydrated open shift report
    live_rep = client.get(f"/api/v1/stations/{SEEDED_STATION}/shifts/current", headers=cashier_h)
    assert live_rep.status_code == 200
    live_body = live_rep.json()
    assert live_body["dispensed_liters"] == pytest.approx(100.0)
    assert live_body["dispense_count"] == 2
    assert live_body["total_amount_kzt"] == pytest.approx(7500.0)
    assert live_body["receipts_liters"] == pytest.approx(500.0)
    assert live_body["closing_tank_liters"] == pytest.approx(8390.0)
    assert live_body["tank_delta_liters"] == pytest.approx(110.0)
    assert live_body["discrepancy_liters"] == pytest.approx(-10.0)
    assert len(live_body["dispenses"]) == 2
    cols = {col["code"]: col for col in live_body["columns"]}
    assert cols["ТРК-1"]["volume_liters"] == pytest.approx(40.0)
    assert cols["ТРК-2"]["volume_liters"] == pytest.approx(60.0)

    # Cashier closes shift -> frozen shift report returned
    closed = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/shifts/{shift_id}/close",
        json={"note": "Смена сдана без замечаний"},
        headers=cashier_h,
    )
    assert closed.status_code == 200
    closed_body = closed.json()
    assert closed_body["status"] == "closed"
    assert closed_body["closed_by"] == "cashier_s"
    assert closed_body["note"] == "Смена сдана без замечаний"
    assert closed_body["dispensed_liters"] == pytest.approx(100.0)
    assert closed_body["dispense_count"] == 2
    assert closed_body["total_amount_kzt"] == pytest.approx(7500.0)
    assert closed_body["receipts_liters"] == pytest.approx(500.0)
    assert closed_body["closing_tank_liters"] == pytest.approx(8390.0)
    assert closed_body["tank_delta_liters"] == pytest.approx(110.0)
    assert closed_body["discrepancy_liters"] == pytest.approx(-10.0)
    assert len(closed_body["dispenses"]) == 2

    # Current shift is now None; double close returns 409
    assert client.get(f"/api/v1/stations/{SEEDED_STATION}/shifts/current", headers=cashier_h).json() is None
    assert (
        client.post(
            f"/api/v1/stations/{SEEDED_STATION}/shifts/{shift_id}/close",
            headers=cashier_h,
        ).status_code
        == 409
    )

    # Owner and Admin can read shift list and detail; foreign owner gets 403
    assert len(client.get(f"/api/v1/stations/{SEEDED_STATION}/shifts", headers=owner_h).json()) == 1
    assert (
        client.get(f"/api/v1/stations/{SEEDED_STATION}/shifts/{shift_id}", headers=admin_h).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/stations/{SEEDED_STATION}/shifts/{shift_id}", headers=other_owner_h).status_code
        == 403
    )

    # Verify memory state persistence (cashier account + closed shift survive restart)
    assert state_file.is_file()
    reset_station_accounts()
    reset_shifts()
    reset_catalog()
    reset_device_ingest()
    boot.restore_memory_state()

    revived_login = _login(client, "cashier_s", "cashier-shift-pass")
    assert revived_login["role"] == ROLE_CASHIER
    revived_h = _auth_headers(revived_login["token"])
    revived_report = client.get(
        f"/api/v1/stations/{SEEDED_STATION}/shifts/{shift_id}",
        headers=revived_h,
    )
    assert revived_report.status_code == 200
    assert revived_report.json()["dispensed_liters"] == pytest.approx(100.0)
    assert revived_report.json()["note"] == "Смена сдана без замечаний"


class _FakeScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeRoleShiftDb:
    def __init__(self) -> None:
        self.stations: dict[UUID, Station] = {}
        self.users: list[StationUser] = []
        self.shifts: dict[UUID, StationShiftRecord] = {}
        self.committed = 0

    def get(self, model, key: UUID):
        if model is Station:
            return self.stations.get(key)
        if model is StationShiftRecord:
            return self.shifts.get(key)
        return None

    def add(self, obj) -> None:
        if isinstance(obj, Station):
            self.stations[obj.id] = obj
        elif isinstance(obj, StationUser):
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            self.users.append(obj)
        elif isinstance(obj, StationShiftRecord):
            self.shifts[obj.id] = obj

    def delete(self, obj) -> None:
        if isinstance(obj, StationUser):
            self.users = [u for u in self.users if u.id != obj.id]

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        pass

    def refresh(self, _obj) -> None:
        pass

    def _filter_users(self, stmt) -> list[StationUser]:
        params = stmt.compile().params
        sql = str(stmt)
        rows = list(self.users)
        for key, value in params.items():
            if key.startswith("station_id") and isinstance(value, (list, tuple, set)):
                allowed = set(value)
                rows = [r for r in rows if r.station_id in allowed]
            elif key.startswith("station_id") and isinstance(value, UUID):
                rows = [r for r in rows if r.station_id == value]
            elif key.startswith("username"):
                rows = [r for r in rows if r.username == value]
            elif key.startswith("kind"):
                rows = [r for r in rows if r.kind == value]
        if "ORDER BY" in sql:
            rows.sort(key=lambda r: r.username)
        return rows

    def _filter_shifts(self, stmt) -> list[StationShiftRecord]:
        params = stmt.compile().params
        rows = list(self.shifts.values())
        for key, value in params.items():
            if key.startswith("id") and isinstance(value, UUID):
                rows = [r for r in rows if r.id == value]
            elif key.startswith("station_id") and isinstance(value, UUID):
                rows = [r for r in rows if r.station_id == value]
            elif key.startswith("status"):
                rows = [r for r in rows if r.status == value]
        rows.sort(key=lambda r: r.opened_at, reverse=True)
        return rows

    def scalar(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        params = list(stmt.compile().params.values())
        if entity is Station:
            return self.stations.get(params[0]) if params else None
        if entity is StationUser:
            rows = self._filter_users(stmt)
            return rows[0] if rows else None
        if entity is StationShiftRecord:
            rows = self._filter_shifts(stmt)
            return rows[0] if rows else None
        return None

    def scalars(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is StationUser:
            return _FakeScalarRows(self._filter_users(stmt))
        if entity is StationShiftRecord:
            return _FakeScalarRows(self._filter_shifts(stmt))
        return _FakeScalarRows([])


class _FakeRoleShiftSession:
    def __init__(self, db: _FakeRoleShiftDb) -> None:
        self.db = db

    def __enter__(self) -> _FakeRoleShiftDb:
        return self.db

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return False


def test_postgres_cashier_and_shift_adapter_parity(monkeypatch):
    from app.domain.errors import ConflictError

    db = _FakeRoleShiftDb()
    st1 = Station(
        id=uuid4(),
        code="PG-1",
        name="PG Station 1",
        address=None,
        lat=43.6,
        lon=51.2,
        is_active=True,
        columns_mode="edge",
        columns_count=2,
    )
    st2 = Station(
        id=uuid4(),
        code="PG-2",
        name="PG Station 2",
        address=None,
        lat=43.7,
        lon=51.3,
        is_active=True,
        columns_mode="edge",
        columns_count=2,
    )
    db.stations[st1.id] = st1
    db.stations[st2.id] = st2
    monkeypatch.setattr(postgres_account, "session", lambda: _FakeRoleShiftSession(db))

    # Cashier CRUD in Postgres adapter
    cashier = postgres_account.create_station_cashier(st1.id, "pg_cashier", "cashier-pg-1")
    assert cashier.kind == "cashier"
    assert cashier.station_id == st1.id
    assert len(postgres_account.list_station_cashiers(st1.id)) == 1
    assert len(postgres_account.list_cashiers_for_stations([st1.id])) == 1
    assert postgres_account.list_cashiers_for_stations([st2.id]) == []

    with pytest.raises(ConflictError):
        postgres_account.create_owner_account("pg_cashier", "owner-pg-1", [st1.id])

    updated = postgres_account.update_station_cashier(
        st1.id,
        "pg_cashier",
        password="cashier-pg-2",
        new_station_id=st2.id,
    )
    assert updated.station_id == st2.id
    auth_cashier = postgres_account.authenticate_station_user("pg_cashier", "cashier-pg-2")
    assert auth_cashier is not None
    assert auth_cashier.kind == "cashier"

    # Shift open & close in Postgres adapter
    t_open = datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc)
    tank_id = uuid4()
    opened = postgres_account.open_shift(
        st1.id,
        opened_by="pg_cashier",
        opened_at=t_open,
        opening_tank_liters=5000.0,
        opening_tanks=[
            ShiftTankSnapshot(
                tank_id=tank_id,
                code="R-1",
                capacity_liters=10000.0,
                remainder_liters=5000.0,
                fill_percent=50.0,
                measured_at=t_open,
            )
        ],
        note="Старт",
    )
    assert opened.status == "open"
    with pytest.raises(ConflictError):
        postgres_account.open_shift(
            st1.id,
            opened_by="pg_cashier",
            opened_at=t_open,
            opening_tank_liters=5000.0,
            opening_tanks=[],
        )

    closed = postgres_account.close_shift(
        st1.id,
        opened.id,
        closed_by="pg_cashier",
        closed_at=t_open + timedelta(hours=8),
        closing_tank_liters=4800.0,
        closing_tanks=[
            ShiftTankSnapshot(
                tank_id=tank_id,
                code="R-1",
                capacity_liters=10000.0,
                remainder_liters=4800.0,
                fill_percent=48.0,
                measured_at=t_open + timedelta(hours=8),
            )
        ],
        receipts_liters=0.0,
        dispensed_liters=200.0,
        dispense_count=4,
        total_amount_kzt=15000.0,
        columns=[
            ShiftColumnSummary(
                pump_address=1,
                code="ТРК-1",
                name="Колонка 1",
                volume_liters=200.0,
                ops_count=4,
                amount_kzt=15000.0,
            )
        ],
        tank_delta_liters=200.0,
        discrepancy_liters=0.0,
        note="Ок",
    )
    assert closed.status == "closed"
    assert closed.columns[0].volume_liters == 200.0
    assert len(postgres_account.list_shifts(st1.id)) == 1

    postgres_account.delete_station_cashier(st2.id, "pg_cashier")
    assert postgres_account.list_station_cashiers(st2.id) == []

    # Snapshot import preserves cashier kind and imports shifts
    snap_db = _FakeRoleShiftDb()
    monkeypatch.setattr(postgres_account, "session", lambda: _FakeRoleShiftSession(snap_db))
    snap_sid = uuid4()
    snap_shift_id = uuid4()
    postgres_account.import_memory_snapshot(
        {
            "catalog": {
                "stations": [
                    {
                        "id": str(snap_sid),
                        "code": "SNAP-ST",
                        "name": "Snap Station",
                        "lat": 43.6,
                        "lon": 51.2,
                        "is_active": True,
                    }
                ],
                "trucks": [],
            },
            "devices": {"devices": [], "books": []},
            "owners": [
                {
                    "id": str(uuid4()),
                    "station_id": str(snap_sid),
                    "username": "snap_cashier",
                    "password_hash": "hash",
                    "kind": "cashier",
                    "station_ids": [str(snap_sid)],
                }
            ],
            "shifts": [
                {
                    "id": str(snap_shift_id),
                    "station_id": str(snap_sid),
                    "status": "closed",
                    "opened_by": "snap_cashier",
                    "closed_by": "snap_cashier",
                    "opened_at": t_open.isoformat(),
                    "closed_at": (t_open + timedelta(hours=8)).isoformat(),
                    "opening_tank_liters": 4000.0,
                    "closing_tank_liters": 3900.0,
                    "opening_tanks": [],
                    "closing_tanks": [],
                    "receipts_liters": 0.0,
                    "dispensed_liters": 100.0,
                    "dispense_count": 2,
                    "total_amount_kzt": 7500.0,
                    "columns": [
                        {
                            "pump_address": 1,
                            "code": "ТРК-1",
                            "name": "Колонка 1",
                            "volume_liters": 100.0,
                            "ops_count": 2,
                            "amount_kzt": 7500.0,
                        }
                    ],
                    "tank_delta_liters": 100.0,
                    "discrepancy_liters": 0.0,
                }
            ],
            "batches": [],
        }
    )
    assert snap_db.users[0].kind == "cashier"
    assert snap_shift_id in snap_db.shifts
    assert snap_db.shifts[snap_shift_id].dispensed_liters == 100.0
