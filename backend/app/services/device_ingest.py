"""Приём Shelly (уровень) и ТРК / АСКА-02 (отпуск).

Книга резервуара: старт + приёмки − отпуски (см. app.domain.tank_book).
Состояние приборов в режиме memory живёт в памяти процесса (сброс в STATE_PATH при наличии),
а в режиме postgres — в таблицах tanks, level_readings, dispense_records, receipt_records.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.domain.tank_book import (
    CALIBRATION_REQUIRED,
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
from app.schemas.station import TankOut
from app.services.calibration import LevelCalibration

_MAX_SEEN = 10_000

_lock = threading.Lock()
_books: dict[tuple[UUID, UUID], "TankBook"] = {}
_seen: set[str] = set()
_devices_by_token: dict[str, "TankDevice"] = {}
_devices_by_tank: dict[UUID, "TankDevice"] = {}
_devices_by_station: dict[UUID, list[UUID]] = {}


def _commit() -> None:
    from app.services.memory_state import persist

    persist()


@dataclass
class TankDevice:
    """Карточка резервуара: объём задаёт сайт, токен выбирает станцию и резервуар."""

    station_id: UUID
    tank_id: UUID
    code: str
    capacity_liters: float
    token: str


@dataclass
class TankBook:
    station_id: UUID
    tank_id: UUID
    opening_liters: float | None = None
    receipts_liters: float = 0.0
    dispense_liters: float = 0.0
    pending_dispense_liters: float = 0.0
    pending_receipt_liters: float = 0.0
    actual_remainder_liters: float | None = None
    calculated_remainder_liters: float | None = None
    delta_liters: float | None = None
    balance_status: str = "unknown"
    calibration: LevelCalibration | None = None
    last_volts: float | None = None
    last_measured_at: datetime | None = None
    level_ids: dict[str, UUID] = field(default_factory=dict)


def reset_device_ingest() -> None:
    with _lock:
        _books.clear()
        _seen.clear()
        _devices_by_token.clear()
        _devices_by_tank.clear()
        _devices_by_station.clear()
    try:
        from app.services.public_board import invalidate_public_board_cache

        invalidate_public_board_cache()
    except Exception:
        pass


def _remember_seen(key: str) -> None:
    if len(_seen) >= _MAX_SEEN:
        _seen.clear()
    _seen.add(key)


def get_tank_device(station_id: UUID, tank_id: UUID) -> TankDevice:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.get_tank_device(station_id, tank_id)
    with _lock:
        device = _devices_by_tank.get(tank_id)
        if device is None or device.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        return device


def has_calibration(station_id: UUID, tank_id: UUID) -> bool:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.has_calibration(station_id, tank_id)
    with _lock:
        book = _books.get((station_id, tank_id))
        return book is not None and book.calibration is not None


def tank_by_token(token: str | None) -> TankDevice | None:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.tank_by_token(token)
    if not token:
        return None
    with _lock:
        return _devices_by_token.get(token)


def list_tank_devices(station_id: UUID) -> list[TankDevice]:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.list_tank_devices(station_id)
    with _lock:
        ids = _devices_by_station.get(station_id, [])
        return [_devices_by_tank[tank_id] for tank_id in ids if tank_id in _devices_by_tank]


def list_station_tanks_out(station_id: UUID) -> list[TankOut]:
    """Возвращает все резервуары станции с фактическим и расчётным остатком за 1 обращение (без N+1)."""
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.list_station_tanks_out(station_id)
    with _lock:
        ids = _devices_by_station.get(station_id, [])
        result: list[TankOut] = []
        for tank_id in ids:
            device = _devices_by_tank.get(tank_id)
            if device is None:
                continue
            book = _books.get((station_id, tank_id))
            actual = None if book is None else book.actual_remainder_liters
            calc = (
                actual
                if book is None or book.calculated_remainder_liters is None
                else book.calculated_remainder_liters
            )
            measured = None if book is None else book.last_measured_at
            result.append(
                TankOut(
                    id=device.tank_id,
                    code=device.code,
                    capacity_liters=device.capacity_liters,
                    has_electronic_sensor=True,
                    actual_remainder_liters=actual,
                    calculated_remainder_liters=calc,
                    level_source="electronic",
                    last_measured_at=measured,
                )
            )
        return result


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.register_tank(station_id, code, capacity_liters)
    cleaned = code.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="укажите код резервуара")
    with _lock:
        for tank_id in _devices_by_station.get(station_id, []):
            if _devices_by_tank[tank_id].code == cleaned:
                raise HTTPException(status_code=409, detail="резервуар с таким кодом уже есть")
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
    _commit()
    try:
        from app.services.public_board import invalidate_public_board_cache

        invalidate_public_board_cache()
    except Exception:
        pass
    return device


def delete_tank_device(station_id: UUID, tank_id: UUID) -> None:
    from app.services.account_mode import use_postgres
    from app.services.shelly_link import remove_shelly_for_tank

    if use_postgres():
        from app.services import postgres_account

        postgres_account.delete_tank_device(station_id, tank_id)
        remove_shelly_for_tank(tank_id)
        return
    with _lock:
        device = _devices_by_tank.get(tank_id)
        if device is None or device.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        _devices_by_token.pop(device.token, None)
        _devices_by_tank.pop(tank_id, None)
        if station_id in _devices_by_station:
            _devices_by_station[station_id] = [
                tid for tid in _devices_by_station[station_id] if tid != tank_id
            ]
        _books.pop((station_id, tank_id), None)
    remove_shelly_for_tank(tank_id)
    _commit()
    try:
        from app.services.public_board import invalidate_public_board_cache

        invalidate_public_board_cache()
    except Exception:
        pass


def delete_station_devices(station_id: UUID) -> None:
    from app.services.account_mode import use_postgres
    from app.services.shelly_link import remove_shelly_for_tank

    if use_postgres():
        for device in list_tank_devices(station_id):
            remove_shelly_for_tank(device.tank_id)
        return
    with _lock:
        tank_ids = list(_devices_by_station.pop(station_id, []))
        for tank_id in tank_ids:
            device = _devices_by_tank.pop(tank_id, None)
            if device is not None:
                _devices_by_token.pop(device.token, None)
            _books.pop((station_id, tank_id), None)
    for tank_id in tank_ids:
        remove_shelly_for_tank(tank_id)
    _commit()
    try:
        from app.services.public_board import invalidate_public_board_cache

        invalidate_public_board_cache()
    except Exception:
        pass


def update_tank_device(
    station_id: UUID,
    tank_id: UUID,
    *,
    code: str | None = None,
    capacity_liters: float | None = None,
) -> TankDevice:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.update_tank_device(
            station_id,
            tank_id,
            code=code,
            capacity_liters=capacity_liters,
        )
    with _lock:
        device = _devices_by_tank.get(tank_id)
        if device is None or device.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        if code is not None:
            cleaned = code.strip()
            if not cleaned:
                raise HTTPException(status_code=422, detail="укажите код резервуара")
            for other_id in _devices_by_station.get(station_id, []):
                other = _devices_by_tank[other_id]
                if other.tank_id != tank_id and other.code == cleaned:
                    raise HTTPException(status_code=409, detail="резервуар с таким кодом уже есть")
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
    _commit()
    return device


def _assert_device_scope(
    device: TankDevice,
    station_id: UUID | None,
    tank_id: UUID | None,
) -> None:
    if station_id is not None and station_id != device.station_id:
        raise HTTPException(status_code=403, detail="токен принадлежит другой заправке")
    if tank_id is not None and tank_id != device.tank_id:
        raise HTTPException(status_code=403, detail="токен принадлежит другому резервуару")


def bind_level(body: LevelIngest, token: str | None) -> LevelIngest:
    device = tank_by_token(token)
    if device is not None:
        _assert_device_scope(device, body.station_id, body.tank_id)
        return body.model_copy(update={"station_id": device.station_id, "tank_id": device.tank_id})
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(
            status_code=422,
            detail="укажите резервуар токеном или полями station_id и tank_id",
        )
    return body


def bind_calibration(body: CalibrationIn, token: str | None) -> CalibrationIn:
    device = tank_by_token(token)
    if device is not None:
        _assert_device_scope(device, body.station_id, body.tank_id)
        return body.model_copy(
            update={
                "station_id": device.station_id,
                "tank_id": device.tank_id,
                "capacity_liters": device.capacity_liters,
            }
        )
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(
            status_code=422,
            detail="укажите резервуар токеном или полями station_id и tank_id",
        )
    if body.capacity_liters is None:
        raise HTTPException(status_code=422, detail="укажите объём резервуара на карточке")
    return body


def bind_dispense(body: DispenseIngest, token: str | None) -> DispenseIngest:
    device = tank_by_token(token)
    if device is not None:
        _assert_device_scope(device, body.station_id, body.tank_id)
        return body.model_copy(update={"station_id": device.station_id, "tank_id": device.tank_id})
    return body


def bind_receipt(body: ReceiptIngest, token: str | None) -> ReceiptIngest:
    device = tank_by_token(token)
    if device is not None:
        _assert_device_scope(device, body.station_id, body.tank_id)
        return body.model_copy(update={"station_id": device.station_id, "tank_id": device.tank_id})
    return body


def _book(station_id: UUID, tank_id: UUID) -> TankBook:
    key = (station_id, tank_id)
    book = _books.get(key)
    if book is None:
        book = TankBook(station_id=station_id, tank_id=tank_id)
        _books[key] = book
    return book


def tank_state(tank_id: UUID) -> TankIngestState:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.tank_state(tank_id)
    with _lock:
        for book in _books.values():
            if book.tank_id == tank_id:
                return build_tank_ingest_state(
                    book,
                    station_id=book.station_id,
                    tank_id=book.tank_id,
                    calibrated=book.calibration is not None,
                )
    raise HTTPException(status_code=404, detail="резервуар ещё не присылал данные")


def tank_remainder(tank_id: UUID) -> tuple[float | None, datetime | None]:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.tank_remainder(tank_id)
    with _lock:
        for book in _books.values():
            if book.tank_id == tank_id:
                return book.actual_remainder_liters, book.last_measured_at
        return None, None


def _poll_linked_shelly(tank_id: UUID) -> None:
    from app.services.shelly_link import poll_one

    try:
        poll_one(tank_id)
    except Exception:
        return


def set_calibration(body: CalibrationIn) -> TankIngestState:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        state = postgres_account.set_calibration(body)
        if body.tank_id is not None:
            _poll_linked_shelly(body.tank_id)
        return state
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(status_code=422, detail="укажите резервуар")
    if body.low_volts == body.high_volts:
        raise HTTPException(status_code=422, detail="точки калибровки совпадают по напряжению")
    with _lock:
        device = _devices_by_tank.get(body.tank_id)
        capacity = device.capacity_liters if device is not None else body.capacity_liters
        if capacity is None:
            raise HTTPException(status_code=422, detail="укажите объём резервуара на карточке")
        book = _book(body.station_id, body.tank_id)
        book.calibration = LevelCalibration(
            capacity_liters=capacity,
            low_volts=body.low_volts,
            low_percent=body.low_percent,
            high_volts=body.high_volts,
            high_percent=body.high_percent,
        )
    _commit()
    try:
        from app.services.public_board import invalidate_public_board_cache

        invalidate_public_board_cache()
    except Exception:
        pass
    _poll_linked_shelly(body.tank_id)
    return tank_state(body.tank_id)


def accept_level(body: LevelIngest) -> IngestAck:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.accept_level(body)
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(
            status_code=422,
            detail="укажите резервуар токеном или полями station_id и tank_id",
        )
    key = body.source_event_id or f"level:{body.tank_id}:{body.recorded_at.isoformat()}"
    with _lock:
        book = _book(body.station_id, body.tank_id)
        if key in _seen:
            return build_ingest_ack(
                book,
                message="duplicate",
                duplicate=True,
                entity_id=book.level_ids.get(key),
            )
        heard_at = datetime.now(timezone.utc)
        device = _devices_by_tank.get(body.tank_id)
        capacity = None if device is None else device.capacity_liters
        changed, _, _ = apply_level_reading(
            book,
            body,
            book.calibration,
            capacity_liters=capacity,
            heard_at=heard_at,
        )
        if not changed:
            ack = build_ingest_ack(book, message="level unchanged")
        else:
            entity_id = uuid4()
            _remember_seen(key)
            if len(book.level_ids) >= 2000:
                book.level_ids.clear()
            book.level_ids[key] = entity_id
            ack = build_ingest_ack(book, message="level accepted", entity_id=entity_id)
            try:
                from app.services.public_board import invalidate_public_board_cache

                invalidate_public_board_cache()
            except Exception:
                pass
    _commit()
    return ack


def accept_dispense(body: DispenseIngest) -> IngestAck:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.accept_dispense(body)
    key = body.external_txn_id or f"dispense:{body.dispenser_id}:{body.started_at.isoformat()}"
    with _lock:
        if key in _seen:
            if body.tank_id is None:
                return IngestAck(accepted=True, message="duplicate", duplicate=True)
            return build_ingest_ack(_book(body.station_id, body.tank_id), message="duplicate", duplicate=True)
        _remember_seen(key)
        if body.tank_id is None:
            ack = IngestAck(accepted=True, message="dispense accepted", entity_id=uuid4())
        else:
            book = _book(body.station_id, body.tank_id)
            apply_dispense_volume(book, body.volume_liters)
            ack = build_ingest_ack(book, message="dispense accepted", entity_id=uuid4())
    _commit()
    return ack


def accept_dispenses_batch(items: list[DispenseIngest]) -> DispenseBatchAck:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.accept_dispenses_batch(items)

    results: list[IngestAck] = []
    accepted = 0
    duplicates = 0
    total_volume = 0.0

    for item in items:
        ack = accept_dispense(item)
        results.append(ack)
        if ack.duplicate:
            duplicates += 1
        else:
            accepted += 1
            total_volume += item.volume_liters

    return DispenseBatchAck(
        accepted_count=accepted,
        duplicates_count=duplicates,
        total_volume_liters=round(total_volume, 3),
        results=results,
    )


def accept_levels_batch(items: list[LevelIngest]) -> LevelBatchAck:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.accept_levels_batch(items)

    results: list[IngestAck] = []
    accepted = 0
    duplicates = 0

    for item in items:
        ack = accept_level(item)
        results.append(ack)
        if ack.duplicate:
            duplicates += 1
        else:
            accepted += 1

    return LevelBatchAck(
        accepted_count=accepted,
        duplicates_count=duplicates,
        results=results,
    )


def accept_receipt(body: ReceiptIngest) -> IngestAck:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account.accept_receipt(body)
    key = body.source_event_id or f"receipt:{body.tank_id}:{body.recorded_at.isoformat()}"
    with _lock:
        book = _book(body.station_id, body.tank_id)
        if key in _seen:
            return build_ingest_ack(book, message="duplicate", duplicate=True)
        _remember_seen(key)
        apply_receipt_volume(book, body.volume_liters)
        ack = build_ingest_ack(book, message="receipt accepted", entity_id=uuid4())
    _commit()
    return ack


def _calibration_row(calibration: LevelCalibration | None) -> dict | None:
    if calibration is None:
        return None
    return {
        "capacity_liters": calibration.capacity_liters,
        "low_volts": calibration.low_volts,
        "low_percent": calibration.low_percent,
        "high_volts": calibration.high_volts,
        "high_percent": calibration.high_percent,
    }


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
                    "calibration": _calibration_row(book.calibration),
                    "last_volts": book.last_volts,
                    "last_measured_at": None
                    if book.last_measured_at is None
                    else book.last_measured_at.isoformat(),
                    "level_ids": {key: str(value) for key, value in book.level_ids.items()},
                }
                for book in _books.values()
            ],
            "seen": sorted(_seen),
        }


def restore_snapshot(data: dict) -> None:
    if not any(key in data for key in ("devices", "books", "seen")):
        return
    with _lock:
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
            book = TankBook(
                station_id=station_id,
                tank_id=tank_id,
                opening_liters=row.get("opening_liters"),
                receipts_liters=float(row.get("receipts_liters") or 0),
                dispense_liters=float(row.get("dispense_liters") or 0),
                pending_dispense_liters=float(row.get("pending_dispense_liters") or 0),
                pending_receipt_liters=float(row.get("pending_receipt_liters") or 0),
                actual_remainder_liters=row.get("actual_remainder_liters"),
                last_volts=row.get("last_volts"),
            )
            raw_cal = row.get("calibration")
            if isinstance(raw_cal, dict):
                book.calibration = LevelCalibration(
                    capacity_liters=float(raw_cal["capacity_liters"]),
                    low_volts=float(raw_cal["low_volts"]),
                    low_percent=float(raw_cal["low_percent"]),
                    high_volts=float(raw_cal["high_volts"]),
                    high_percent=float(raw_cal["high_percent"]),
                )
            measured = row.get("last_measured_at")
            if measured:
                book.last_measured_at = datetime.fromisoformat(str(measured).replace("Z", "+00:00"))
            for key, value in (row.get("level_ids") or {}).items():
                book.level_ids[str(key)] = UUID(str(value))
            recompute_tank_book(book)
            _books[(station_id, tank_id)] = book
