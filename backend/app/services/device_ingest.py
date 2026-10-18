"""Приём Shelly (уровень) и Топаз-119-28М (отпуск).

Книга резервуара: старт + приёмки − отпуски.
Старт — первое показание уровня. Отпуски и приёмки до старта
сохраняются, но в книгу не входят: они уже сидят в физическом уровне.

Пока остальной API на демо-данных, состояние приборов тоже в памяти процесса.
Повтор с тем же ключом не двигает остаток.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.schemas.ingest import (
    CalibrationIn,
    DispenseIngest,
    IngestAck,
    LevelIngest,
    ReceiptIngest,
    TankIngestState,
)
from app.services.balance import calculate_remainder, classify_discrepancy
from app.services.calibration import LevelCalibration, volts_to_liters

CALIBRATION_REQUIRED = "для volts нужна калибровка резервуара: POST /ingest/calibration"

_lock = threading.Lock()
_books: dict[tuple[UUID, UUID], "TankBook"] = {}
_seen: set[str] = set()
_devices_by_token: dict[str, "TankDevice"] = {}
_devices_by_tank: dict[UUID, "TankDevice"] = {}
_devices_by_station: dict[UUID, list[UUID]] = {}


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


def get_tank_device(station_id: UUID, tank_id: UUID) -> TankDevice:
    with _lock:
        device = _devices_by_tank.get(tank_id)
        if device is None or device.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
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


def _device_for_token(token: str | None) -> TankDevice | None:
    if not token:
        return None
    return _devices_by_token.get(token)


def list_tank_devices(station_id: UUID) -> list[TankDevice]:
    with _lock:
        ids = _devices_by_station.get(station_id, [])
        return [_devices_by_tank[tank_id] for tank_id in ids if tank_id in _devices_by_tank]


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
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
        return device


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
        return device


def bind_level(body: LevelIngest, token: str | None) -> LevelIngest:
    with _lock:
        device = _device_for_token(token)
        if device is not None:
            return body.model_copy(update={"station_id": device.station_id, "tank_id": device.tank_id})
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(
            status_code=422,
            detail="укажите резервуар токеном или полями station_id и tank_id",
        )
    return body


def bind_calibration(body: CalibrationIn, token: str | None) -> CalibrationIn:
    with _lock:
        device = _device_for_token(token)
        if device is not None:
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


def _book(station_id: UUID, tank_id: UUID) -> TankBook:
    key = (station_id, tank_id)
    book = _books.get(key)
    if book is None:
        book = TankBook(station_id=station_id, tank_id=tank_id)
        _books[key] = book
    return book


def _recompute(book: TankBook) -> None:
    if book.opening_liters is None:
        book.calculated_remainder_liters = None
        book.delta_liters = None
        book.balance_status = "unknown"
        return
    calculated = calculate_remainder(
        book.opening_liters, book.receipts_liters, book.dispense_liters
    )
    result = classify_discrepancy(calculated, book.actual_remainder_liters)
    book.calculated_remainder_liters = result.calculated_remainder_liters
    book.delta_liters = result.delta_liters
    book.balance_status = result.status


def _ack(book: TankBook, *, message: str, duplicate: bool = False, entity_id: UUID | None = None) -> IngestAck:
    return IngestAck(
        accepted=True,
        message=message,
        entity_id=entity_id,
        duplicate=duplicate,
        actual_remainder_liters=book.actual_remainder_liters,
        calculated_remainder_liters=book.calculated_remainder_liters,
        delta_liters=book.delta_liters,
        balance_status=book.balance_status,
    )


def _state(book: TankBook) -> TankIngestState:
    return TankIngestState(
        station_id=book.station_id,
        tank_id=book.tank_id,
        opening_liters=book.opening_liters,
        receipts_liters=book.receipts_liters,
        dispense_liters=book.dispense_liters,
        pending_dispense_liters=book.pending_dispense_liters,
        calculated_remainder_liters=book.calculated_remainder_liters,
        actual_remainder_liters=book.actual_remainder_liters,
        delta_liters=book.delta_liters,
        balance_status=book.balance_status,
        calibrated=book.calibration is not None,
        last_volts=book.last_volts,
        last_measured_at=book.last_measured_at,
    )


def tank_state(tank_id: UUID) -> TankIngestState:
    with _lock:
        for book in _books.values():
            if book.tank_id == tank_id:
                return _state(book)
    raise HTTPException(status_code=404, detail="резервуар ещё не присылал данные")


def tank_remainder(tank_id: UUID) -> tuple[float | None, datetime | None]:
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
    _poll_linked_shelly(body.tank_id)
    return tank_state(body.tank_id)


def _liters_from_level(body: LevelIngest, book: TankBook) -> float:
    if body.volts is not None:
        book.last_volts = body.volts
    if body.actual_remainder_liters is not None:
        return body.actual_remainder_liters
    if book.calibration is None:
        raise HTTPException(
            status_code=422,
            detail=CALIBRATION_REQUIRED,
        )
    assert body.volts is not None
    book.last_volts = body.volts
    return volts_to_liters(body.volts, book.calibration)


def accept_level(body: LevelIngest) -> IngestAck:
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(
            status_code=422,
            detail="укажите резервуар токеном или полями station_id и tank_id",
        )
    key = body.source_event_id or f"level:{body.tank_id}:{body.recorded_at.isoformat()}"
    with _lock:
        book = _book(body.station_id, body.tank_id)
        if key in _seen:
            return _ack(book, message="duplicate", duplicate=True, entity_id=book.level_ids.get(key))
        liters = _liters_from_level(body, book)
        if book.opening_liters is None:
            book.opening_liters = liters
        book.actual_remainder_liters = liters
        book.last_measured_at = body.recorded_at
        _recompute(book)
        entity_id = uuid4()
        _seen.add(key)
        book.level_ids[key] = entity_id
        return _ack(book, message="level accepted", entity_id=entity_id)


def accept_dispense(body: DispenseIngest) -> IngestAck:
    key = body.external_txn_id or f"dispense:{body.dispenser_id}:{body.started_at.isoformat()}"
    with _lock:
        if key in _seen:
            if body.tank_id is None:
                return IngestAck(accepted=True, message="duplicate", duplicate=True)
            return _ack(_book(body.station_id, body.tank_id), message="duplicate", duplicate=True)
        _seen.add(key)
        if body.tank_id is None:
            return IngestAck(accepted=True, message="dispense accepted", entity_id=uuid4())
        book = _book(body.station_id, body.tank_id)
        if book.opening_liters is None:
            book.pending_dispense_liters += body.volume_liters
            return _ack(book, message="dispense accepted", entity_id=uuid4())
        book.dispense_liters += body.volume_liters
        _recompute(book)
        return _ack(book, message="dispense accepted", entity_id=uuid4())


def accept_receipt(body: ReceiptIngest) -> IngestAck:
    key = body.source_event_id or f"receipt:{body.tank_id}:{body.recorded_at.isoformat()}"
    with _lock:
        book = _book(body.station_id, body.tank_id)
        if key in _seen:
            return _ack(book, message="duplicate", duplicate=True)
        _seen.add(key)
        if book.opening_liters is None:
            book.pending_receipt_liters += body.volume_liters
            return _ack(book, message="receipt accepted", entity_id=uuid4())
        book.receipts_liters += body.volume_liters
        _recompute(book)
        return _ack(book, message="receipt accepted", entity_id=uuid4())
