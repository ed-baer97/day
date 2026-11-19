"""API-тесты пересобранного кабинета администратора платформы."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token, reset_auth_state
from app.config import get_settings
from app.domain.access import ROLE_STATION
from app.main import create_app
from app.models.batch import Batch, BatchStatus, BatchTrailEvent, TrailNodeType
from app.services import account, postgres_account
from app.services.batch_book import reset_batches
from app.services.catalog import reset_catalog
from app.services.device_ingest import reset_device_ingest
from app.services.shelly_link import reset_shelly_links
from app.services.station_accounts import reset_station_accounts

SEEDED_STATION = "a1111111-1111-1111-1111-111111111101"


@pytest.fixture(autouse=True)
def _clean():
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_shelly_links()
    reset_station_accounts()
    reset_batches()
    yield
    reset_auth_state()
    reset_catalog()
    reset_device_ingest()
    reset_shelly_links()
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


def test_owner_devices_hide_token_url_and_shelly_while_admin_sees_them(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "lpg-admin")
    get_settings.cache_clear()
    client = TestClient(create_app())
    admin_h = _admin_headers(client)

    created = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/devices",
        json={"code": "R-1", "capacity_liters": 10000},
        headers=admin_h,
    )
    assert created.status_code == 201
    device = created.json()

    from app.schemas.station import ShellyLinkOut

    monkeypatch.setattr(
        "app.routers.deps.shelly_view",
        lambda _tank_id: ShellyLinkOut(host="10.0.0.50", online=True, sensor_ready=True, applied=True),
    )

    owner_created = client.post(
        f"/api/v1/stations/{SEEDED_STATION}/users",
        json={"username": "owner1", "password": "owner-password-1"},
        headers=admin_h,
    )
    assert owner_created.status_code == 201
    owner_token = client.post(
        "/api/v1/auth/login",
        json={"username": "owner1", "password": "owner-password-1"},
    ).json()["token"]

    owner_resp = client.get(
        f"/api/v1/stations/{SEEDED_STATION}/devices",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_resp.status_code == 200
    assert len(owner_resp.json()) == 1
    assert owner_resp.json()[0]["code"] == "R-1"
    assert owner_resp.json()[0]["ingest_token"] is None
    assert owner_resp.json()[0]["ingest_url"] is None
    assert owner_resp.json()[0]["shelly"] is None

    admin_resp = client.get(f"/api/v1/stations/{SEEDED_STATION}/devices", headers=admin_h)
    assert admin_resp.status_code == 200
    assert admin_resp.json()[0]["ingest_token"] == device["ingest_token"]
    assert admin_resp.json()[0]["shelly"]["host"] == "10.0.0.50"


def test_account_routes_batches_to_postgres_when_enabled(monkeypatch):
    monkeypatch.setattr("app.services.account_mode.use_postgres", lambda: True)
    calls: list[str] = []
    batch_id = uuid4()
    sample = {
        "id": batch_id,
        "trail_code": "PG-1",
        "supplier_id": None,
        "factory_id": None,
        "product_grade": "ПБТ",
        "density_kg_per_liter": None,
        "volume_liters": 12000.0,
        "mass_kg": None,
        "status": "formed",
        "formed_at": datetime.now(timezone.utc),
        "notes": None,
        "created_at": datetime.now(timezone.utc),
        "events": [],
    }

    monkeypatch.setattr(postgres_account, "list_batches", lambda: calls.append("list") or [sample])
    monkeypatch.setattr(postgres_account, "create_batch", lambda **_kw: calls.append("create") or sample)
    monkeypatch.setattr(postgres_account, "get_batch_by_code", lambda code: calls.append(f"code:{code}") or sample)
    monkeypatch.setattr(postgres_account, "get_batch_by_id", lambda bid: calls.append(f"id:{bid}") or sample)
    monkeypatch.setattr(postgres_account, "add_batch_event", lambda bid, **_kw: calls.append(f"ev:{bid}") or sample)
    monkeypatch.setattr(postgres_account, "update_batch_status", lambda bid, st, _n=None: calls.append(f"st:{st}") or sample)

    assert account.list_batches() == [sample]
    assert account.create_batch(
        trail_code="PG-1",
        supplier_id=None,
        factory_id=None,
        product_grade="ПБТ",
        density_kg_per_liter=None,
        volume_liters=12000.0,
        mass_kg=None,
        notes=None,
    ) == sample
    assert account.get_batch_by_code("PG-1") == sample
    assert account.get_batch_by_id(batch_id) == sample
    assert account.add_batch_event(batch_id, node_type="route", title="В пути") == sample
    assert account.update_batch_status(batch_id, "in_transit", "note") == sample
    assert calls == ["list", "create", "code:PG-1", f"id:{batch_id}", f"ev:{batch_id}", "st:in_transit"]


class _ScalarList:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeBatchDb:
    def __init__(self) -> None:
        self.batches: dict[UUID, Batch] = {}
        self.events: list[BatchTrailEvent] = []
        self.added: list[object] = []
        self.flushed = 0
        self.committed = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, Batch):
            obj.trail_events = []
            self.batches[obj.id] = obj
        elif isinstance(obj, BatchTrailEvent):
            self.events.append(obj)
            if obj.batch_id in self.batches:
                self.batches[obj.batch_id].trail_events = [
                    ev for ev in self.events if ev.batch_id == obj.batch_id
                ]

    def flush(self) -> None:
        self.flushed += 1

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        pass

    def refresh(self, _obj: object) -> None:
        pass

    def _hydrate(self, row: Batch | None) -> Batch | None:
        if row is not None:
            row.trail_events = [ev for ev in self.events if ev.batch_id == row.id]
        return row

    def scalar(self, stmt):
        col = stmt.column_descriptions[0]
        params = list(stmt.compile().params.values())
        key = params[0] if params else None
        if col.get("entity") is None and col.get("name") == "id":
            for b in self.batches.values():
                if b.trail_code.lower() == str(key).lower():
                    return b.id
            return None
        if isinstance(key, UUID):
            return self._hydrate(self.batches.get(key))
        for b in self.batches.values():
            if b.trail_code.lower() == str(key).lower():
                return self._hydrate(b)
        return None

    def scalars(self, _stmt):
        rows = sorted(self.batches.values(), key=lambda b: b.created_at, reverse=True)
        return _ScalarList(rows)


class _FakeBatchSession:
    def __init__(self, db: _FakeBatchDb) -> None:
        self.db = db

    def __enter__(self) -> _FakeBatchDb:
        return self.db

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return False


def test_postgres_batch_crud_and_snapshot_import(monkeypatch):
    from app.domain.errors import ConflictError

    db = _FakeBatchDb()
    monkeypatch.setattr(postgres_account, "session", lambda: _FakeBatchSession(db))

    created = postgres_account.create_batch(
        trail_code="LPG-PG-100",
        supplier_id=None,
        factory_id=None,
        product_grade="ПБТ",
        density_kg_per_liter=0.54,
        volume_liters=18000.0,
        mass_kg=9720.0,
        notes="Партия с ГПЗ",
    )
    batch_id = created["id"]
    assert created["trail_code"] == "LPG-PG-100"
    assert created["status"] == "formed"
    assert len(postgres_account.list_batches()) == 1

    with pytest.raises(ConflictError):
        postgres_account.create_batch(
            trail_code="lpg-pg-100",
            supplier_id=None,
            factory_id=None,
            product_grade=None,
            density_kg_per_liter=None,
            volume_liters=5000.0,
            mass_kg=None,
            notes=None,
        )

    fetched_code = postgres_account.get_batch_by_code("lpg-pg-100")
    assert fetched_code is not None and len(fetched_code["events"]) == 1
    fetched_id = postgres_account.get_batch_by_id(batch_id)
    assert fetched_id is not None and fetched_id["events"][0]["node_type"] == "batch"

    updated = postgres_account.update_batch_status(batch_id, "in_transit", "Выехал")
    assert updated["status"] == "in_transit"

    after_event = postgres_account.add_batch_event(
        batch_id,
        node_type="tank",
        title="Слив в R-1",
        volume_liters=9000.0,
        status="delivered",
    )
    assert after_event["status"] == "delivered"
    assert len(after_event["events"]) == 3
    assert [ev["node_type"] for ev in after_event["events"]] == ["batch", "route", "tank"]

    snap_db = _FakeBatchDb()
    monkeypatch.setattr(postgres_account, "session", lambda: _FakeBatchSession(snap_db))
    snap_batch_id = uuid4()
    postgres_account.import_memory_snapshot(
        {
            "catalog": {"stations": [], "trucks": []},
            "devices": {"devices": [], "books": []},
            "owners": [],
            "batches": [
                {
                    "id": str(snap_batch_id),
                    "trail_code": "SNAP-001",
                    "product_grade": "ПБТ",
                    "volume_liters": 15000,
                    "status": "in_transit",
                    "formed_at": "2026-11-18T08:00:00Z",
                    "created_at": "2026-11-18T08:00:00Z",
                    "events": [
                        {
                            "id": str(uuid4()),
                            "node_type": "batch",
                            "occurred_at": "2026-11-18T08:00:00Z",
                            "title": "Партия зарегистрирована",
                        },
                        {
                            "id": str(uuid4()),
                            "node_type": "route",
                            "occurred_at": "2026-11-18T09:00:00Z",
                            "title": "Выезд на АГЗС",
                        },
                    ],
                }
            ],
        }
    )
    assert snap_db.committed == 1
    assert snap_batch_id in snap_db.batches
    assert snap_db.batches[snap_batch_id].trail_code == "SNAP-001"
    assert snap_db.batches[snap_batch_id].status == BatchStatus.in_transit
    imported_events = [ev for ev in snap_db.events if ev.batch_id == snap_batch_id]
    assert len(imported_events) == 2
    assert [ev.node_type for ev in imported_events] == [TrailNodeType.batch, TrailNodeType.route]

    # Доимпорт партий пропускает уже существующие id и trail_code
    extra_id = uuid4()
    imported_count = postgres_account.import_batches_snapshot(
        [
            {
                "id": str(snap_batch_id),
                "trail_code": "DUP-ID",
                "volume_liters": 1000,
                "status": "formed",
                "events": [],
            },
            {
                "id": str(uuid4()),
                "trail_code": "snap-001",
                "volume_liters": 2000,
                "status": "formed",
                "events": [],
            },
            {
                "id": str(extra_id),
                "trail_code": "SNAP-002",
                "volume_liters": 8500,
                "status": "delivered",
                "events": [],
            },
        ]
    )
    assert imported_count == 1
    assert extra_id in snap_db.batches
    assert snap_db.batches[extra_id].trail_code == "SNAP-002"


def test_boot_backfills_batches_when_stations_already_exist(tmp_path, monkeypatch):
    import json
    from app.services import boot

    snap_file = tmp_path / "state.json"
    snap_batches = [
        {
            "id": str(uuid4()),
            "trail_code": "BACKFILL-001",
            "volume_liters": 12000,
            "status": "formed",
            "events": [],
        }
    ]
    snap_file.write_text(json.dumps({"batches": snap_batches}), encoding="utf-8")

    monkeypatch.setenv("ACCOUNT_STORE", "postgres")
    monkeypatch.setenv("STATE_PATH", str(snap_file))
    get_settings.cache_clear()

    from app.models.station import Station

    class _CheckDb:
        def __init__(self, has_station: bool, has_batch: bool) -> None:
            self.has_station = has_station
            self.has_batch = has_batch

        def scalar(self, stmt):
            col = stmt.column_descriptions[0]
            expr = str(col.get("expr", ""))
            if "stations.id" in expr or col.get("entity") is Station:
                return uuid4() if self.has_station else None
            return uuid4() if self.has_batch else None

    class _CheckSession:
        def __init__(self, has_station: bool, has_batch: bool) -> None:
            self.db = _CheckDb(has_station, has_batch)

        def __enter__(self):
            return self.db

        def __exit__(self, *_args):
            return False

    backfilled: list[list] = []
    full_imported: list[dict] = []
    monkeypatch.setattr(
        postgres_account,
        "import_batches_snapshot",
        lambda rows: backfilled.append(rows) or len(rows),
    )
    monkeypatch.setattr(
        postgres_account,
        "import_memory_snapshot",
        lambda data: full_imported.append(data),
    )

    # Станции есть, партий нет -> доимпортируются только партии из state.json
    monkeypatch.setattr("app.database.SessionLocal", lambda: _CheckSession(True, False))
    boot.import_state_if_empty()
    assert len(backfilled) == 1
    assert backfilled[0] == snap_batches
    assert full_imported == []

    # И станции, и партии уже есть -> ничего не переносится
    backfilled.clear()
    monkeypatch.setattr("app.database.SessionLocal", lambda: _CheckSession(True, True))
    boot.import_state_if_empty()
    assert backfilled == []
    assert full_imported == []

