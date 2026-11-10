"""Порт учёта, доменная ошибка калибровки и пакетная транзакция PostgreSQL."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.domain.errors import CalibrationRequired
from app.domain.tank_book import CALIBRATION_REQUIRED, apply_level_reading
from app.main import create_app
from app.schemas.ingest import DispenseIngest, IngestAck, LevelIngest
from app.services import account, postgres_account
from app.services.catalog import create_truck, get_truck, reset_catalog
from app.services.device_ingest import TankBook, reset_device_ingest

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def _clean():
    reset_catalog()
    reset_device_ingest()
    yield
    reset_catalog()
    reset_device_ingest()


def test_backend_follows_account_store(monkeypatch):
    monkeypatch.setattr("app.services.account_mode.use_postgres", lambda: False)
    assert account.backend().__name__ == "app.services.memory_account"
    monkeypatch.setattr("app.services.account_mode.use_postgres", lambda: True)
    assert account.backend().__name__ == "app.services.postgres_account"


def test_volts_without_calibration_is_domain_error():
    book = TankBook(station_id=uuid4(), tank_id=uuid4())
    now = datetime.now(timezone.utc)
    with pytest.raises(CalibrationRequired) as caught:
        apply_level_reading(
            book,
            LevelIngest(
                station_id=book.station_id,
                tank_id=book.tank_id,
                volts=2.5,
                recorded_at=now,
            ),
            calibration=None,
            heard_at=now,
        )
    assert caught.value.detail == CALIBRATION_REQUIRED


def test_port_turns_calibration_error_into_http_422():
    def boom():
        raise CalibrationRequired(CALIBRATION_REQUIRED)

    with pytest.raises(HTTPException) as caught:
        account._levels(boom)
    assert caught.value.status_code == 422
    assert caught.value.detail == CALIBRATION_REQUIRED


def test_gps_writes_truck_and_ignores_duplicate():
    truck = create_truck(
        plate_number="GPS 001",
        capacity_liters=18000,
        carrier_name=None,
        status="in_transit",
        lat=None,
        lon=None,
    )
    first = client.post(
        "/api/v1/ingest/gps",
        json={
            "truck_id": str(truck.id),
            "lat": 43.65,
            "lon": 51.15,
            "recorded_at": "2026-11-11T08:00:00Z",
            "source_event_id": "gps-1",
        },
    )
    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    saved = get_truck(truck.id)
    assert saved.lat == pytest.approx(43.65)
    assert saved.lon == pytest.approx(51.15)

    second = client.post(
        "/api/v1/ingest/gps",
        json={
            "truck_id": str(truck.id),
            "lat": 43.70,
            "lon": 51.20,
            "recorded_at": "2026-11-11T08:05:00Z",
            "source_event_id": "gps-1",
        },
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    saved = get_truck(truck.id)
    assert saved.lat == pytest.approx(43.65)
    assert saved.lon == pytest.approx(51.15)


def test_gps_unknown_truck_is_404():
    missing = client.post(
        "/api/v1/ingest/gps",
        json={
            "truck_id": str(uuid4()),
            "lat": 43.65,
            "lon": 51.15,
            "recorded_at": "2026-11-11T08:00:00Z",
            "source_event_id": "gps-missing",
        },
    )
    assert missing.status_code == 404


class _Db:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


class _Session:
    def __init__(self, db: _Db) -> None:
        self.db = db

    def __enter__(self) -> _Db:
        return self.db

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.db.rollback()
        self.db.close()
        return False


def _item(txn: str, volume: float = 10.0) -> DispenseIngest:
    return DispenseIngest(
        station_id=uuid4(),
        dispenser_id=uuid4(),
        tank_id=uuid4(),
        volume_liters=volume,
        started_at=datetime.now(timezone.utc),
        external_txn_id=txn,
    )


def test_postgres_batch_commits_once_and_skips_duplicate_volume(monkeypatch):
    events: list[str] = []
    db = _Db(events)
    monkeypatch.setattr(postgres_account, "session", lambda: _Session(db))

    def apply(_db, body: DispenseIngest) -> IngestAck:
        assert _db is db
        if body.external_txn_id == "dup":
            return IngestAck(accepted=True, message="duplicate", duplicate=True)
        return IngestAck(accepted=True, message="dispense accepted")

    monkeypatch.setattr(postgres_account, "_accept_dispense", apply)
    ack = postgres_account.accept_dispenses_batch([_item("a", 40), _item("dup", 15), _item("b", 5)])
    assert events == ["commit", "close"]
    assert ack.accepted_count == 2
    assert ack.duplicates_count == 1
    assert ack.total_volume_liters == 45


def test_postgres_batch_rolls_back_when_an_item_fails(monkeypatch):
    events: list[str] = []
    db = _Db(events)
    monkeypatch.setattr(postgres_account, "session", lambda: _Session(db))

    def apply(_db, body: DispenseIngest) -> IngestAck:
        if body.external_txn_id == "bad":
            raise HTTPException(status_code=404, detail="резервуар не найден")
        return IngestAck(accepted=True, message="dispense accepted")

    monkeypatch.setattr(postgres_account, "_accept_dispense", apply)
    with pytest.raises(HTTPException) as caught:
        postgres_account.accept_dispenses_batch([_item("ok"), _item("bad")])
    assert caught.value.status_code == 404
    assert "commit" not in events
    assert events[0] == "rollback"


def test_postgres_level_batch_rolls_back(monkeypatch):
    events: list[str] = []
    db = _Db(events)
    monkeypatch.setattr(postgres_account, "session", lambda: _Session(db))

    def apply(_db, body: LevelIngest) -> IngestAck:
        if body.source_event_id == "bad":
            raise CalibrationRequired(CALIBRATION_REQUIRED)
        return IngestAck(accepted=True, message="level accepted")

    monkeypatch.setattr(postgres_account, "_accept_level", apply)
    now = datetime.now(timezone.utc)
    items = [
        LevelIngest(station_id=uuid4(), tank_id=uuid4(), actual_remainder_liters=1, recorded_at=now, source_event_id="ok"),
        LevelIngest(station_id=uuid4(), tank_id=uuid4(), actual_remainder_liters=1, recorded_at=now, source_event_id="bad"),
    ]
    with pytest.raises(CalibrationRequired):
        postgres_account.accept_levels_batch(items)
    assert "commit" not in events
    assert events[0] == "rollback"
