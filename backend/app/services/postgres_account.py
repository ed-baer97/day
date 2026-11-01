"""Учёт станций и резервуаров в Postgres.

Включается ACCOUNT_STORE=postgres. Тесты и локальный стенд остаются на памяти.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.station import LevelReading, LevelSource, Station, StationUser, Tank
from app.schemas.ingest import CalibrationIn, IngestAck, LevelIngest, TankIngestState
from app.services.balance import calculate_remainder, classify_discrepancy
from app.services.calibration import LevelCalibration, volts_to_liters, volts_to_percent
from app.services.catalog import StationCard
from app.services.device_ingest import TankDevice
from app.services.passwords import hash_password, verify_password

logger = logging.getLogger(__name__)

CALIBRATION_REQUIRED = "для volts нужна калибровка резервуара: POST /ingest/calibration"


def session() -> Session:
    return SessionLocal()


def _card(row: Station) -> StationCard:
    return StationCard(
        id=row.id,
        code=row.code,
        name=row.name,
        address=row.address,
        lat=row.lat,
        lon=row.lon,
        is_active=row.is_active,
    )


def _device(row: Tank) -> TankDevice:
    return TankDevice(
        station_id=row.station_id,
        tank_id=row.id,
        code=row.code,
        capacity_liters=row.capacity_liters,
        token=row.ingest_token or "",
    )


def _calibration(row: Tank) -> LevelCalibration | None:
    if None in (row.cal_low_volts, row.cal_low_percent, row.cal_high_volts, row.cal_high_percent):
        return None
    return LevelCalibration(
        capacity_liters=row.capacity_liters,
        low_volts=float(row.cal_low_volts),
        low_percent=float(row.cal_low_percent),
        high_volts=float(row.cal_high_volts),
        high_percent=float(row.cal_high_percent),
    )


def _recompute(row: Tank) -> None:
    if row.opening_liters is None:
        row.calculated_remainder_liters = None
        return
    calculated = calculate_remainder(row.opening_liters, row.receipts_liters, row.dispense_liters)
    result = classify_discrepancy(calculated, row.actual_remainder_liters)
    row.calculated_remainder_liters = result.calculated_remainder_liters


def _ack(row: Tank, *, message: str, duplicate: bool = False, entity_id: UUID | None = None) -> IngestAck:
    calculated = row.calculated_remainder_liters
    actual = row.actual_remainder_liters
    delta = None if calculated is None or actual is None else actual - calculated
    status = "unknown"
    if calculated is not None and actual is not None:
        status = classify_discrepancy(calculated, actual).status
    return IngestAck(
        accepted=True,
        message=message,
        entity_id=entity_id,
        duplicate=duplicate,
        actual_remainder_liters=actual,
        calculated_remainder_liters=calculated,
        delta_liters=delta,
        balance_status=status,
    )


def _state(row: Tank) -> TankIngestState:
    calculated = row.calculated_remainder_liters
    actual = row.actual_remainder_liters
    delta = None if calculated is None or actual is None else actual - calculated
    status = "unknown"
    if calculated is not None and actual is not None:
        status = classify_discrepancy(calculated, actual).status
    return TankIngestState(
        station_id=row.station_id,
        tank_id=row.id,
        opening_liters=row.opening_liters,
        receipts_liters=row.receipts_liters,
        dispense_liters=row.dispense_liters,
        pending_dispense_liters=row.pending_dispense_liters,
        calculated_remainder_liters=calculated,
        actual_remainder_liters=actual,
        delta_liters=delta,
        balance_status=status,
        calibrated=_calibration(row) is not None,
        last_volts=row.last_volts,
        last_measured_at=row.last_measured_at,
    )


def list_stations() -> list[StationCard]:
    with session() as db:
        rows = db.scalars(select(Station).order_by(Station.code)).all()
        return [_card(row) for row in rows]


def get_station(station_id: UUID) -> StationCard:
    with session() as db:
        row = db.get(Station, station_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Station not found")
        return _card(row)


def create_station(
    *,
    code: str,
    name: str,
    address: str | None,
    lat: float,
    lon: float,
    is_active: bool,
) -> StationCard:
    with session() as db:
        if db.scalar(select(Station).where(Station.code == code.strip())):
            raise HTTPException(status_code=409, detail="заправка с таким кодом уже есть")
        row = Station(
            id=uuid4(),
            code=code.strip(),
            name=name.strip(),
            address=(address or "").strip() or None,
            lat=lat,
            lon=lon,
            is_active=is_active,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _card(row)


def update_station(
    station_id: UUID,
    *,
    code: str | None = None,
    name: str | None = None,
    address: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    is_active: bool | None = None,
    address_set: bool = False,
) -> StationCard:
    with session() as db:
        row = db.get(Station, station_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Station not found")
        if code is not None:
            cleaned = code.strip()
            other = db.scalar(select(Station).where(Station.code == cleaned, Station.id != station_id))
            if other is not None:
                raise HTTPException(status_code=409, detail="заправка с таким кодом уже есть")
            row.code = cleaned
        if name is not None:
            row.name = name.strip()
        if address_set:
            row.address = (address or "").strip() or None
        if lat is not None:
            row.lat = lat
        if lon is not None:
            row.lon = lon
        if is_active is not None:
            row.is_active = is_active
        db.commit()
        db.refresh(row)
        return _card(row)


def delete_station(station_id: UUID) -> None:
    with session() as db:
        row = db.get(Station, station_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Station not found")
        db.delete(row)
        db.commit()


def list_tank_devices(station_id: UUID) -> list[TankDevice]:
    with session() as db:
        rows = db.scalars(select(Tank).where(Tank.station_id == station_id).order_by(Tank.code)).all()
        return [_device(row) for row in rows]


def get_tank_device(station_id: UUID, tank_id: UUID) -> TankDevice:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None or row.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        return _device(row)


def tank_by_token(token: str | None) -> TankDevice | None:
    if not token:
        return None
    with session() as db:
        row = db.scalar(select(Tank).where(Tank.ingest_token == token))
        return None if row is None else _device(row)


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
    cleaned = code.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="укажите код резервуара")
    with session() as db:
        if db.get(Station, station_id) is None:
            raise HTTPException(status_code=404, detail="Station not found")
        exists = db.scalar(select(Tank).where(Tank.station_id == station_id, Tank.code == cleaned))
        if exists is not None:
            raise HTTPException(status_code=409, detail="резервуар с таким кодом уже есть")
        row = Tank(
            id=uuid4(),
            station_id=station_id,
            code=cleaned,
            capacity_liters=capacity_liters,
            has_electronic_sensor=True,
            level_source=LevelSource.electronic,
            ingest_token=secrets.token_urlsafe(24),
            receipts_liters=0.0,
            dispense_liters=0.0,
            pending_dispense_liters=0.0,
            pending_receipt_liters=0.0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _device(row)


def update_tank_device(
    station_id: UUID,
    tank_id: UUID,
    *,
    code: str | None = None,
    capacity_liters: float | None = None,
) -> TankDevice:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None or row.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        if code is not None:
            cleaned = code.strip()
            if not cleaned:
                raise HTTPException(status_code=422, detail="укажите код резервуара")
            other = db.scalar(
                select(Tank).where(Tank.station_id == station_id, Tank.code == cleaned, Tank.id != tank_id)
            )
            if other is not None:
                raise HTTPException(status_code=409, detail="резервуар с таким кодом уже есть")
            row.code = cleaned
        if capacity_liters is not None:
            row.capacity_liters = capacity_liters
        db.commit()
        db.refresh(row)
        return _device(row)


def delete_tank_device(station_id: UUID, tank_id: UUID) -> None:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None or row.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        db.delete(row)
        db.commit()


def has_calibration(station_id: UUID, tank_id: UUID) -> bool:
    with session() as db:
        row = db.get(Tank, tank_id)
        return row is not None and row.station_id == station_id and _calibration(row) is not None


def set_calibration(body: CalibrationIn) -> TankIngestState:
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(status_code=422, detail="укажите резервуар")
    if body.low_volts == body.high_volts:
        raise HTTPException(status_code=422, detail="точки калибровки совпадают по напряжению")
    with session() as db:
        row = db.get(Tank, body.tank_id)
        if row is None or row.station_id != body.station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        row.cal_low_volts = body.low_volts
        row.cal_low_percent = body.low_percent
        row.cal_high_volts = body.high_volts
        row.cal_high_percent = body.high_percent
        if body.capacity_liters is not None:
            row.capacity_liters = body.capacity_liters
        db.commit()
        db.refresh(row)
        return _state(row)


def tank_remainder(tank_id: UUID) -> tuple[float | None, datetime | None]:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None:
            return None, None
        return row.actual_remainder_liters, row.last_measured_at


def tank_state(tank_id: UUID) -> TankIngestState:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None:
            raise HTTPException(status_code=404, detail="резервуар ещё не присылал данные")
        return _state(row)


def accept_level(body: LevelIngest) -> IngestAck:
    if body.station_id is None or body.tank_id is None:
        raise HTTPException(
            status_code=422,
            detail="укажите резервуар токеном или полями station_id и tank_id",
        )
    key = body.source_event_id or f"level:{body.tank_id}:{body.recorded_at.isoformat()}"
    with session() as db:
        existing = db.scalar(select(LevelReading).where(LevelReading.source_event_id == key))
        row = db.get(Tank, body.tank_id)
        if row is None or row.station_id != body.station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        if existing is not None:
            return _ack(row, message="duplicate", duplicate=True, entity_id=existing.id)

        if body.volts is not None:
            row.last_volts = body.volts
        if body.actual_remainder_liters is not None:
            liters = body.actual_remainder_liters
            fill = None if row.capacity_liters <= 0 else liters / row.capacity_liters * 100
        else:
            calibration = _calibration(row)
            if calibration is None:
                raise HTTPException(status_code=422, detail=CALIBRATION_REQUIRED)
            assert body.volts is not None
            liters = volts_to_liters(body.volts, calibration)
            fill = volts_to_percent(body.volts, calibration)

        if row.opening_liters is None or (
            row.opening_liters < 0 and row.receipts_liters == 0 and row.dispense_liters == 0
        ):
            row.opening_liters = liters
        row.actual_remainder_liters = liters
        row.last_measured_at = body.recorded_at
        row.level_source = LevelSource.electronic
        _recompute(row)
        entity_id = uuid4()
        db.add(
            LevelReading(
                id=entity_id,
                tank_id=row.id,
                station_id=row.station_id,
                volts=body.volts,
                remainder_liters=liters,
                fill_percent=fill,
                recorded_at=body.recorded_at,
                source_event_id=key,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.get(Tank, body.tank_id)
            existing = db.scalar(select(LevelReading).where(LevelReading.source_event_id == key))
            assert row is not None
            return _ack(row, message="duplicate", duplicate=True, entity_id=None if existing is None else existing.id)
        db.refresh(row)
        return _ack(row, message="level accepted", entity_id=entity_id)


def list_level_readings(station_id: UUID, tank_id: UUID, *, limit: int = 50) -> list[LevelReading]:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None or row.station_id != station_id:
            raise HTTPException(status_code=404, detail="резервуар не найден")
        return list(
            db.scalars(
                select(LevelReading)
                .where(LevelReading.tank_id == tank_id)
                .order_by(LevelReading.recorded_at.desc())
                .limit(limit)
            ).all()
        )


def create_station_user(station_id: UUID, username: str, password: str) -> StationUser:
    cleaned = username.strip().lower()
    if not cleaned:
        raise HTTPException(status_code=422, detail="укажите логин")
    with session() as db:
        if db.get(Station, station_id) is None:
            raise HTTPException(status_code=404, detail="Station not found")
        if db.scalar(select(StationUser).where(StationUser.username == cleaned)):
            raise HTTPException(status_code=409, detail="логин уже занят")
        row = StationUser(
            id=uuid4(),
            station_id=station_id,
            username=cleaned,
            password_hash=hash_password(password),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def authenticate_station_user(username: str, password: str) -> StationUser | None:
    cleaned = username.strip().lower()
    with session() as db:
        row = db.scalar(select(StationUser).where(StationUser.username == cleaned))
        if row is None or not verify_password(password, row.password_hash):
            return None
        db.expunge(row)
        return row


def import_memory_snapshot(data: dict) -> None:
    """Разовый перенос state.json в пустую базу."""

    catalog = data.get("catalog") or {}
    devices = data.get("devices") or {}
    with session() as db:
        if db.scalar(select(Station).limit(1)) is not None:
            return
        for row in catalog.get("stations") or []:
            db.add(
                Station(
                    id=UUID(row["id"]),
                    code=row["code"],
                    name=row["name"],
                    address=row.get("address"),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    is_active=bool(row["is_active"]),
                )
            )
        books = {str(item["tank_id"]): item for item in devices.get("books") or []}
        for row in devices.get("devices") or []:
            book = books.get(str(row["tank_id"]), {})
            calibration = book.get("calibration") or {}
            measured = book.get("last_measured_at")
            tank = Tank(
                id=UUID(row["tank_id"]),
                station_id=UUID(row["station_id"]),
                code=row["code"],
                capacity_liters=float(row["capacity_liters"]),
                has_electronic_sensor=True,
                level_source=LevelSource.electronic,
                ingest_token=row["token"],
                actual_remainder_liters=book.get("actual_remainder_liters"),
                opening_liters=book.get("opening_liters"),
                receipts_liters=float(book.get("receipts_liters") or 0),
                dispense_liters=float(book.get("dispense_liters") or 0),
                pending_dispense_liters=float(book.get("pending_dispense_liters") or 0),
                pending_receipt_liters=float(book.get("pending_receipt_liters") or 0),
                last_volts=book.get("last_volts"),
                cal_low_volts=calibration.get("low_volts"),
                cal_low_percent=calibration.get("low_percent"),
                cal_high_volts=calibration.get("high_volts"),
                cal_high_percent=calibration.get("high_percent"),
            )
            if measured:
                tank.last_measured_at = datetime.fromisoformat(str(measured).replace("Z", "+00:00"))
            _recompute(tank)
            db.add(tank)
            if tank.actual_remainder_liters is not None and tank.last_measured_at is not None:
                fill = None
                if tank.capacity_liters > 0:
                    fill = tank.actual_remainder_liters / tank.capacity_liters * 100
                db.add(
                    LevelReading(
                        id=uuid4(),
                        tank_id=tank.id,
                        station_id=tank.station_id,
                        volts=tank.last_volts,
                        remainder_liters=tank.actual_remainder_liters,
                        fill_percent=fill,
                        recorded_at=tank.last_measured_at,
                        source_event_id=f"import-{tank.id}",
                    )
                )
        db.commit()
        logger.info("учёт из state.json перенесён в Postgres")
