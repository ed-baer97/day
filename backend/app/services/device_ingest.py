"""Хранилище резервуаров и книги остатка в памяти процесса."""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.domain.calibration import LevelCalibration
from app.domain.entities import TankBook, TankDevice, parse_dispense_meta
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.tank_book import (
    apply_dispense_volume,
    apply_level_reading,
    apply_receipt_volume,
    build_ingest_ack,
    build_tank_ingest_state,
    recompute_tank_book,
)
from app.schemas.ingest import (
    CalibrationIn,
    DispenseBatchAck,
    DispenseIngest,
    IngestAck,
    LevelBatchAck,
    LevelIngest,
    ReceiptIngest,
    TankIngestState,
)
from app.schemas.station import DispenseReadingOut, TankOut
from app.services.account_helpers import (
    ack_to_schema,
    batch_counts,
    build_dispense_out,
    build_tank_out,
    calibration_from_dict,
    calibration_to_dict,
    dispense_event_key,
    extract_book_fields,
    level_event_key,
    parse_iso_utc,
    receipt_event_key,
    require_calibration_points,
    require_non_empty,
    require_station_and_tank,
    state_to_schema,
)
from app.services.board_cache import invalidate_public_board_cache
from app.services.memory_state import persist, register_store

_MAX_SEEN = 10_000
_MAX_STATION_DISPENSES = 2_000

_lock = threading.Lock()
_books: dict[tuple[UUID, UUID], TankBook] = {}
_seen: set[str] = set()
_devices_by_token: dict[str, TankDevice] = {}
_devices_by_tank: dict[UUID, TankDevice] = {}
_devices_by_station: dict[UUID, list[UUID]] = {}
_dispenses_by_station: dict[UUID, list[DispenseReadingOut]] = {}


def reset_device_ingest() -> None:
    with _lock:
        _books.clear()
        _seen.clear()
        _devices_by_token.clear()
        _devices_by_tank.clear()
        _devices_by_station.clear()
        _dispenses_by_station.clear()
    invalidate_public_board_cache()


def _remember_seen(key: str) -> None:
    if len(_seen) >= _MAX_SEEN:
        _seen.clear()
    _seen.add(key)


def get_tank_device(station_id: UUID, tank_id: UUID) -> TankDevice:
    with _lock:
        device = _devices_by_tank.get(tank_id)
        if device is None or device.station_id != station_id:
            raise NotFoundError("резервуар не найден")
        return device


def has_calibration(station_id: UUID, tank_id: UUID) -> bool:
    with _lock:
        book = _books.get((station_id, tank_id))
        return book is not None and book.calibration is not None


def tank_by_token(token: str | None) -> TankDevice | None:
    if not token:
        return None
    with _lock:
        return _devices_by_token.get(token)


def list_tank_devices(station_id: UUID) -> list[TankDevice]:
    with _lock:
        ids = _devices_by_station.get(station_id, [])
        return [_devices_by_tank[tank_id] for tank_id in ids if tank_id in _devices_by_tank]


def list_station_tanks_out(station_id: UUID) -> list[TankOut]:
    """Возвращает все резервуары станции с фактическим и расчётным остатком за 1 обращение (без N+1)."""
    with _lock:
        ids = _devices_by_station.get(station_id, [])
        result: list[TankOut] = []
        for tank_id in ids:
            device = _devices_by_tank.get(tank_id)
            if device is None:
                continue
            book = _books.get((station_id, tank_id))
            result.append(
                build_tank_out(
                    tank_id=device.tank_id,
                    code=device.code,
                    capacity_liters=device.capacity_liters,
                    actual_remainder_liters=None if book is None else book.actual_remainder_liters,
                    calculated_remainder_liters=None if book is None else book.calculated_remainder_liters,
                    last_measured_at=None if book is None else book.last_measured_at,
                )
            )
        return result


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
    cleaned = require_non_empty(code, "код резервуара")
    with _lock:
        for tank_id in _devices_by_station.get(station_id, []):
            if _devices_by_tank[tank_id].code == cleaned:
                raise ConflictError("резервуар с таким кодом уже есть")
        device = TankDevice(
            station_id=station_id,
            tank_id=uuid4(),
            code=cleaned,
            capacity_liters=capacity_liters,
            token=secrets.token_urlsafe(24),
        )
        _devices_by_token[device.token] = device
        _devices_by_tank[device.tank_id] = device
        _devices_by_station.setdefault(station_id, []).append(device.tank_id)
    persist()
    invalidate_public_board_cache()
    return device


def delete_tank_device(station_id: UUID, tank_id: UUID) -> None:
    with _lock:
        device = _devices_by_tank.get(tank_id)
        if device is None or device.station_id != station_id:
            raise NotFoundError("резервуар не найден")
        _devices_by_token.pop(device.token, None)
        _devices_by_tank.pop(tank_id, None)
        if station_id in _devices_by_station:
            _devices_by_station[station_id] = [
                tid for tid in _devices_by_station[station_id] if tid != tank_id
            ]
        _books.pop((station_id, tank_id), None)
    persist()
    invalidate_public_board_cache()


def delete_station_devices(station_id: UUID) -> list[UUID]:
    with _lock:
        tank_ids = list(_devices_by_station.pop(station_id, []))
        for tank_id in tank_ids:
            device = _devices_by_tank.pop(tank_id, None)
            if device is not None:
                _devices_by_token.pop(device.token, None)
            _books.pop((station_id, tank_id), None)
    persist()
    invalidate_public_board_cache()
    return tank_ids


def update_tank_device(
    station_id: UUID,
    tank_id: UUID,
    *,
    code: str | None = None,
    capacity_liters: float | None = None,
) -> TankDevice:
    with _lock:
        device = _devices_by_tank.get(tank_id)
        if device is None or device.station_id != station_id:
            raise NotFoundError("резервуар не найден")
        if code is not None:
            cleaned = require_non_empty(code, "код резервуара")
            for other_id in _devices_by_station.get(station_id, []):
                other = _devices_by_tank[other_id]
                if other.tank_id != tank_id and other.code == cleaned:
                    raise ConflictError("резервуар с таким кодом уже есть")
            device.code = cleaned
        if capacity_liters is not None:
            device.capacity_liters = capacity_liters
            book = _books.get((station_id, tank_id))
            if book is not None and book.calibration is not None:
                current = book.calibration
                book.calibration = LevelCalibration(
                    capacity_liters=capacity_liters,
                    low_volts=current.low_volts,
                    low_percent=current.low_percent,
                    high_volts=current.high_volts,
                    high_percent=current.high_percent,
                )
    persist()
    return device


def _book(station_id: UUID, tank_id: UUID) -> TankBook:
    key = (station_id, tank_id)
    book = _books.get(key)
    if book is None:
        book = TankBook(station_id=station_id, tank_id=tank_id)
        _books[key] = book
    return book


def tank_state(tank_id: UUID) -> TankIngestState:
    with _lock:
        for book in _books.values():
            if book.tank_id == tank_id:
                return state_to_schema(
                    build_tank_ingest_state(
                        book,
                        station_id=book.station_id,
                        tank_id=book.tank_id,
                        calibrated=book.calibration is not None,
                    )
                )
    raise NotFoundError("резервуар ещё не присылал данные")


def tank_remainder(tank_id: UUID) -> tuple[float | None, datetime | None]:
    with _lock:
        for book in _books.values():
            if book.tank_id == tank_id:
                return book.actual_remainder_liters, book.last_measured_at
        return None, None


def set_calibration(body: CalibrationIn) -> TankIngestState:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id, "укажите резервуар")
    require_calibration_points(body.low_volts, body.high_volts)
    with _lock:
        device = _devices_by_tank.get(tank_id)
        capacity = device.capacity_liters if device is not None else body.capacity_liters
        if capacity is None:
            raise ValidationError("укажите объём резервуара на карточке")
        book = _book(station_id, tank_id)
        book.calibration = LevelCalibration(
            capacity_liters=capacity,
            low_volts=body.low_volts,
            low_percent=body.low_percent,
            high_volts=body.high_volts,
            high_percent=body.high_percent,
        )
    persist()
    invalidate_public_board_cache()
    return tank_state(tank_id)


def accept_level(body: LevelIngest) -> IngestAck:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id)
    key = level_event_key(tank_id, body.recorded_at, body.source_event_id)
    with _lock:
        book = _book(station_id, tank_id)
        if key in _seen:
            return ack_to_schema(
                build_ingest_ack(
                    book,
                    message="duplicate",
                    duplicate=True,
                    entity_id=book.level_ids.get(key),
                )
            )
        heard_at = datetime.now(timezone.utc)
        device = _devices_by_tank.get(tank_id)
        capacity = None if device is None else device.capacity_liters
        changed, _, _ = apply_level_reading(
            book,
            body,
            book.calibration,
            capacity_liters=capacity,
            heard_at=heard_at,
        )
        if not changed:
            ack = ack_to_schema(build_ingest_ack(book, message="level unchanged"))
        else:
            entity_id = uuid4()
            _remember_seen(key)
            if len(book.level_ids) >= 2000:
                book.level_ids.clear()
            book.level_ids[key] = entity_id
            ack = ack_to_schema(build_ingest_ack(book, message="level accepted", entity_id=entity_id))
            invalidate_public_board_cache()
    persist()
    return ack


def accept_dispense(body: DispenseIngest) -> IngestAck:
    key = dispense_event_key(body.dispenser_id, body.started_at, body.external_txn_id)
    with _lock:
        if key in _seen:
            if body.tank_id is None:
                return IngestAck(accepted=True, message="duplicate", duplicate=True)
            return ack_to_schema(
                build_ingest_ack(_book(body.station_id, body.tank_id), message="duplicate", duplicate=True)
            )
        _remember_seen(key)
        entity_id = uuid4()
        if body.tank_id is None:
            ack = IngestAck(accepted=True, message="dispense accepted", entity_id=entity_id)
        else:
            book = _book(body.station_id, body.tank_id)
            apply_dispense_volume(book, body.volume_liters)
            ack = ack_to_schema(build_ingest_ack(book, message="dispense accepted", entity_id=entity_id))
        station_rows = _dispenses_by_station.setdefault(body.station_id, [])
        station_rows.append(
            build_dispense_out(
                record_id=entity_id,
                station_id=body.station_id,
                tank_id=body.tank_id,
                dispenser_id=body.dispenser_id,
                volume_liters=body.volume_liters,
                started_at=body.started_at,
                finished_at=body.finished_at,
                external_txn_id=key,
                raw_payload=body.raw_payload,
            )
        )
        if len(station_rows) > _MAX_STATION_DISPENSES:
            del station_rows[: len(station_rows) - _MAX_STATION_DISPENSES]
    persist()
    return ack


def list_dispense_records(
    station_id: UUID,
    *,
    since: datetime | None = None,
    limit: int = 500,
) -> list[DispenseReadingOut]:
    since_utc = (
        None
        if since is None
        else (since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc))
    )
    with _lock:
        rows = list(_dispenses_by_station.get(station_id, ()))

    def _stamp(raw: str) -> datetime:
        parsed = parse_iso_utc(raw)
        assert parsed is not None
        return parsed

    if since_utc is not None:
        rows = [row for row in rows if _stamp(row.started_at) >= since_utc]
    rows.sort(key=lambda row: _stamp(row.started_at), reverse=True)
    return rows[: max(1, limit)]


def accept_dispenses_batch(items: list[DispenseIngest]) -> DispenseBatchAck:
    results = [accept_dispense(item) for item in items]
    accepted, duplicates, total_volume = batch_counts(results, [item.volume_liters for item in items])
    return DispenseBatchAck(
        accepted_count=accepted,
        duplicates_count=duplicates,
        total_volume_liters=round(total_volume, 3),
        results=results,
    )


def accept_levels_batch(items: list[LevelIngest]) -> LevelBatchAck:
    results = [accept_level(item) for item in items]
    accepted, duplicates, _ = batch_counts(results)
    return LevelBatchAck(
        accepted_count=accepted,
        duplicates_count=duplicates,
        results=results,
    )


def accept_receipt(body: ReceiptIngest) -> IngestAck:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id)
    key = receipt_event_key(tank_id, body.recorded_at, body.source_event_id)
    with _lock:
        book = _book(station_id, tank_id)
        if key in _seen:
            return ack_to_schema(build_ingest_ack(book, message="duplicate", duplicate=True))
        _remember_seen(key)
        apply_receipt_volume(book, body.volume_liters)
        ack = ack_to_schema(build_ingest_ack(book, message="receipt accepted", entity_id=uuid4()))
    persist()
    return ack


def snapshot() -> dict:
    with _lock:
        return {
            "devices": [
                {
                    "station_id": str(device.station_id),
                    "tank_id": str(device.tank_id),
                    "code": device.code,
                    "capacity_liters": device.capacity_liters,
                    "token": device.token,
                }
                for device in _devices_by_tank.values()
            ],
            "books": [
                {
                    "station_id": str(book.station_id),
                    "tank_id": str(book.tank_id),
                    "opening_liters": book.opening_liters,
                    "receipts_liters": book.receipts_liters,
                    "dispense_liters": book.dispense_liters,
                    "pending_dispense_liters": book.pending_dispense_liters,
                    "pending_receipt_liters": book.pending_receipt_liters,
                    "actual_remainder_liters": book.actual_remainder_liters,
                    "calibration": calibration_to_dict(book.calibration),
                    "last_volts": book.last_volts,
                    "last_measured_at": None
                    if book.last_measured_at is None
                    else book.last_measured_at.isoformat(),
                    "level_ids": {key: str(value) for key, value in book.level_ids.items()},
                }
                for book in _books.values()
            ],
            "seen": sorted(_seen),
            "dispenses": [
                item.model_dump(mode="json")
                for rows in _dispenses_by_station.values()
                for item in rows
            ],
        }


def restore_snapshot(data: dict) -> None:
    if not isinstance(data, dict) or not any(
        key in data for key in ("devices", "books", "seen", "dispenses")
    ):
        return
    with _lock:
        if "dispenses" in data and isinstance(data["dispenses"], list):
            _dispenses_by_station.clear()
            for row in data["dispenses"]:
                item = DispenseReadingOut.model_validate(row)
                _dispenses_by_station.setdefault(item.station_id, []).append(item)
        if "devices" in data:
            _devices_by_token.clear()
            _devices_by_tank.clear()
            _devices_by_station.clear()
            for row in data["devices"]:
                device = TankDevice(
                    station_id=UUID(row["station_id"]),
                    tank_id=UUID(row["tank_id"]),
                    code=row["code"],
                    capacity_liters=float(row["capacity_liters"]),
                    token=row["token"],
                )
                _devices_by_token[device.token] = device
                _devices_by_tank[device.tank_id] = device
                _devices_by_station.setdefault(device.station_id, []).append(device.tank_id)
        if "seen" in data:
            _seen.clear()
            _seen.update(str(item) for item in data["seen"])
        if "books" not in data:
            return
        _books.clear()
        for row in data["books"]:
            station_id = UUID(row["station_id"])
            tank_id = UUID(row["tank_id"])
            fields = extract_book_fields(row)
            cal = calibration_from_dict(row.get("calibration"))
            book = TankBook(
                station_id=station_id,
                tank_id=tank_id,
                opening_liters=fields["opening_liters"],  # type: ignore[arg-type]
                receipts_liters=float(fields["receipts_liters"]),  # type: ignore[arg-type]
                dispense_liters=float(fields["dispense_liters"]),  # type: ignore[arg-type]
                pending_dispense_liters=float(fields["pending_dispense_liters"]),  # type: ignore[arg-type]
                pending_receipt_liters=float(fields["pending_receipt_liters"]),  # type: ignore[arg-type]
                actual_remainder_liters=fields["actual_remainder_liters"],  # type: ignore[arg-type]
                last_volts=fields["last_volts"],  # type: ignore[arg-type]
                last_measured_at=fields["last_measured_at"],  # type: ignore[arg-type]
                calibration=cal,
            )
            for key, value in (row.get("level_ids") or {}).items():
                book.level_ids[str(key)] = UUID(str(value))
            recompute_tank_book(book)
            _books[(station_id, tank_id)] = book


register_store("devices", snapshot, restore_snapshot)

__all__ = [
    "TankBook",
    "TankDevice",
    "accept_dispense",
    "accept_dispenses_batch",
    "accept_level",
    "accept_levels_batch",
    "accept_receipt",
    "delete_station_devices",
    "delete_tank_device",
    "get_tank_device",
    "has_calibration",
    "list_dispense_records",
    "list_station_tanks_out",
    "list_tank_devices",
    "parse_dispense_meta",
    "register_tank",
    "reset_device_ingest",
    "restore_snapshot",
    "set_calibration",
    "snapshot",
    "tank_by_token",
    "tank_remainder",
    "tank_state",
    "update_tank_device",
]
