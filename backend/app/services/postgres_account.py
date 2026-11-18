"""Учёт станций, резервуаров, газовозов и телеметрии в PostgreSQL.

Включается ACCOUNT_STORE=postgres. Поддерживает:
- пакетную выборку станций с резервуарами за 1 SQL-запрос (selectinload, без N+1);
- строковую блокировку (SELECT ... FOR UPDATE) резервуаров при параллельном приёме пакетов;
- персистентную идемпотентность отпусков (dispense_records) и приёмок (receipt_records) в БД.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.domain.calibration import LevelCalibration
from app.domain.entities import StationCard, StationOwner, TankDevice, TruckCard
from app.domain.errors import ConflictError, NotFoundError
from app.domain.tank_book import (
    apply_dispense_volume,
    apply_level_reading,
    apply_receipt_volume,
    build_ingest_ack,
    build_tank_ingest_state,
    recompute_tank_book,
)
from app.models.dispenser import DispenseRecord, ReceiptRecord
from app.models.station import LevelReading, LevelSource, Station, StationUser, Tank
from app.models.truck import Truck
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
    clean_optional_text,
    clean_owner_username,
    dispense_event_key,
    extract_book_fields,
    level_event_key,
    receipt_event_key,
    require_calibration_points,
    require_non_empty,
    require_owner_password,
    require_station_and_tank,
    require_truck_status,
    state_to_schema,
)
from app.services.passwords import hash_password, verify_password

logger = logging.getLogger(__name__)


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


def _truck_card(row: Truck) -> TruckCard:
    return TruckCard(
        id=row.id,
        plate_number=row.plate_number,
        capacity_liters=row.capacity_liters,
        carrier_name=row.carrier_name,
        status=row.status,
        lat=row.lat,
        lon=row.lon,
    )


def _device(row: Tank) -> TankDevice:
    return TankDevice(
        station_id=row.station_id,
        tank_id=row.id,
        code=row.code,
        capacity_liters=row.capacity_liters,
        token=row.ingest_token or "",
    )


def _tank_out(row: Tank) -> TankOut:
    return build_tank_out(
        tank_id=row.id,
        code=row.code,
        capacity_liters=row.capacity_liters,
        actual_remainder_liters=row.actual_remainder_liters,
        calculated_remainder_liters=row.calculated_remainder_liters,
        last_measured_at=row.last_measured_at,
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


def _state(row: Tank) -> TankIngestState:
    return state_to_schema(
        build_tank_ingest_state(
            row,
            station_id=row.station_id,
            tank_id=row.id,
            calibrated=_calibration(row) is not None,
        )
    )


def list_stations() -> list[StationCard]:
    with session() as db:
        rows = db.scalars(select(Station).order_by(Station.code)).all()
        return [_card(row) for row in rows]


def list_active_stations_with_tanks() -> list[tuple[StationCard, list[TankOut]]]:
    """Пакетно загружает все активные станции вместе с их резервуарами за 1 SQL-запрос (selectinload)."""
    with session() as db:
        stmt = (
            select(Station)
            .where(Station.is_active.is_(True))
            .options(selectinload(Station.tanks))
            .order_by(Station.code)
        )
        stations = db.scalars(stmt).all()
        result: list[tuple[StationCard, list[TankOut]]] = []
        for st in stations:
            sorted_tanks = sorted(st.tanks, key=lambda item: item.code)
            result.append((_card(st), [_tank_out(t) for t in sorted_tanks]))
        return result


def get_station(station_id: UUID) -> StationCard:
    with session() as db:
        row = db.get(Station, station_id)
        if row is None:
            raise NotFoundError("Station not found")
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
    cleaned_code = require_non_empty(code, "код заправки")
    cleaned_name = require_non_empty(name, "название заправки")
    with session() as db:
        if db.scalar(select(Station).where(Station.code == cleaned_code)):
            raise ConflictError("заправка с таким кодом уже есть")
        row = Station(
            id=uuid4(),
            code=cleaned_code,
            name=cleaned_name,
            address=clean_optional_text(address),
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
            raise NotFoundError("Station not found")
        if code is not None:
            cleaned = require_non_empty(code, "код заправки")
            other = db.scalar(select(Station).where(Station.code == cleaned, Station.id != station_id))
            if other is not None:
                raise ConflictError("заправка с таким кодом уже есть")
            row.code = cleaned
        if name is not None:
            row.name = require_non_empty(name, "название заправки")
        if address_set:
            row.address = clean_optional_text(address)
        if lat is not None:
            row.lat = lat
        if lon is not None:
            row.lon = lon
        if is_active is not None:
            row.is_active = is_active
        db.commit()
        db.refresh(row)
        return _card(row)


def delete_station(station_id: UUID) -> list[UUID]:
    with session() as db:
        row = db.scalar(
            select(Station)
            .where(Station.id == station_id)
            .options(selectinload(Station.tanks))
        )
        if row is None:
            raise NotFoundError("Station not found")
        tank_ids = [tank.id for tank in row.tanks]
        db.delete(row)
        db.commit()
        return tank_ids


def list_trucks() -> list[TruckCard]:
    with session() as db:
        rows = db.scalars(select(Truck).order_by(Truck.plate_number)).all()
        return [_truck_card(row) for row in rows]


def get_truck(truck_id: UUID) -> TruckCard:
    with session() as db:
        row = db.get(Truck, truck_id)
        if row is None:
            raise NotFoundError("Truck not found")
        return _truck_card(row)


def create_truck(
    *,
    plate_number: str,
    capacity_liters: float,
    carrier_name: str | None,
    status: str,
    lat: float | None,
    lon: float | None,
) -> TruckCard:
    plate = require_non_empty(plate_number, "номер газовоза")
    valid_status = require_truck_status(status)
    with session() as db:
        if db.scalar(select(Truck).where(Truck.plate_number == plate)):
            raise ConflictError("газовоз с таким номером уже есть")
        row = Truck(
            id=uuid4(),
            plate_number=plate,
            capacity_liters=capacity_liters,
            carrier_name=clean_optional_text(carrier_name),
            status=valid_status,
            lat=lat,
            lon=lon,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _truck_card(row)


def update_truck(
    truck_id: UUID,
    *,
    plate_number: str | None = None,
    capacity_liters: float | None = None,
    carrier_name: str | None = None,
    status: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    carrier_set: bool = False,
    lat_set: bool = False,
    lon_set: bool = False,
) -> TruckCard:
    with session() as db:
        row = db.get(Truck, truck_id)
        if row is None:
            raise NotFoundError("Truck not found")
        if plate_number is not None:
            plate = require_non_empty(plate_number, "номер газовоза")
            other = db.scalar(select(Truck).where(Truck.plate_number == plate, Truck.id != truck_id))
            if other is not None:
                raise ConflictError("газовоз с таким номером уже есть")
            row.plate_number = plate
        if capacity_liters is not None:
            row.capacity_liters = capacity_liters
        if carrier_set:
            row.carrier_name = clean_optional_text(carrier_name)
        if status is not None:
            row.status = require_truck_status(status)
        if lat_set:
            row.lat = lat
        if lon_set:
            row.lon = lon
        db.commit()
        db.refresh(row)
        return _truck_card(row)


def delete_truck(truck_id: UUID) -> None:
    with session() as db:
        row = db.get(Truck, truck_id)
        if row is None:
            raise NotFoundError("Truck not found")
        db.delete(row)
        db.commit()


def list_tank_devices(station_id: UUID) -> list[TankDevice]:
    with session() as db:
        rows = db.scalars(select(Tank).where(Tank.station_id == station_id).order_by(Tank.code)).all()
        return [_device(row) for row in rows]


def list_station_tanks_out(station_id: UUID) -> list[TankOut]:
    """Возвращает все резервуары станции с фактическим и расчётным остатком за 1 SQL-запрос."""
    with session() as db:
        rows = db.scalars(select(Tank).where(Tank.station_id == station_id).order_by(Tank.code)).all()
        return [_tank_out(row) for row in rows]


def get_tank_device(station_id: UUID, tank_id: UUID) -> TankDevice:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None or row.station_id != station_id:
            raise NotFoundError("резервуар не найден")
        return _device(row)


def tank_by_token(token: str | None) -> TankDevice | None:
    if not token:
        return None
    with session() as db:
        row = db.scalar(select(Tank).where(Tank.ingest_token == token))
        return None if row is None else _device(row)


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
    cleaned = require_non_empty(code, "код резервуара")
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        exists = db.scalar(select(Tank).where(Tank.station_id == station_id, Tank.code == cleaned))
        if exists is not None:
            raise ConflictError("резервуар с таким кодом уже есть")
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
            raise NotFoundError("резервуар не найден")
        if code is not None:
            cleaned = require_non_empty(code, "код резервуара")
            other = db.scalar(
                select(Tank).where(Tank.station_id == station_id, Tank.code == cleaned, Tank.id != tank_id)
            )
            if other is not None:
                raise ConflictError("резервуар с таким кодом уже есть")
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
            raise NotFoundError("резервуар не найден")
        db.delete(row)
        db.commit()


def has_calibration(station_id: UUID, tank_id: UUID) -> bool:
    with session() as db:
        row = db.get(Tank, tank_id)
        return row is not None and row.station_id == station_id and _calibration(row) is not None


def set_calibration(body: CalibrationIn) -> TankIngestState:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id, "укажите резервуар")
    require_calibration_points(body.low_volts, body.high_volts)
    with session() as db:
        row = db.scalar(select(Tank).where(Tank.id == tank_id).with_for_update())
        if row is None or row.station_id != station_id:
            raise NotFoundError("резервуар не найден")
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
            raise NotFoundError("резервуар ещё не присылал данные")
        return _state(row)


def _insert_once(db: Session, row: object, existing):
    """Вставляет строку в savepoint. Гонка уникального ключа не отменяет внешнюю транзакцию."""
    nested = db.begin_nested()
    try:
        db.add(row)
        db.flush()
    except IntegrityError:
        nested.rollback()
        return db.scalar(existing)
    nested.commit()
    return None


def _accept_level(db: Session, body: LevelIngest) -> IngestAck:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id)
    key = level_event_key(tank_id, body.recorded_at, body.source_event_id)
    row = db.scalar(select(Tank).where(Tank.id == tank_id).with_for_update())
    if row is None or row.station_id != station_id:
        raise NotFoundError("резервуар не найден")
    existing = db.scalar(select(LevelReading).where(LevelReading.source_event_id == key))
    if existing is not None:
        return ack_to_schema(build_ingest_ack(row, message="duplicate", duplicate=True, entity_id=existing.id))

    calibration = _calibration(row)
    heard_at = datetime.now(timezone.utc)
    entity_id = uuid4()
    nested = db.begin_nested()
    try:
        changed, liters, fill = apply_level_reading(
            row,
            body,
            calibration,
            capacity_liters=row.capacity_liters,
            heard_at=heard_at,
        )
        if changed:
            row.level_source = LevelSource.electronic
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
            db.flush()
    except IntegrityError:
        nested.rollback()
        db.refresh(row)
        duplicate = db.scalar(select(LevelReading).where(LevelReading.source_event_id == key))
        return ack_to_schema(
            build_ingest_ack(
                row,
                message="duplicate",
                duplicate=True,
                entity_id=None if duplicate is None else duplicate.id,
            )
        )
    nested.commit()
    if not changed:
        return ack_to_schema(build_ingest_ack(row, message="level unchanged"))
    return ack_to_schema(build_ingest_ack(row, message="level accepted", entity_id=entity_id))


def _accept_dispense(db: Session, body: DispenseIngest) -> IngestAck:
    key = dispense_event_key(body.dispenser_id, body.started_at, body.external_txn_id)
    existing = db.scalar(select(DispenseRecord).where(DispenseRecord.external_txn_id == key))
    if body.tank_id is None:
        if existing is not None:
            return IngestAck(accepted=True, message="duplicate", duplicate=True, entity_id=existing.id)
        entity_id = uuid4()
        duplicate = _insert_once(
            db,
            DispenseRecord(
                id=entity_id,
                station_id=body.station_id,
                tank_id=None,
                dispenser_id=body.dispenser_id,
                volume_liters=body.volume_liters,
                started_at=body.started_at,
                finished_at=body.finished_at,
                external_txn_id=key,
                raw_payload=body.raw_payload,
            ),
            select(DispenseRecord).where(DispenseRecord.external_txn_id == key),
        )
        if duplicate is not None:
            return IngestAck(
                accepted=True,
                message="duplicate",
                duplicate=True,
                entity_id=duplicate.id,
            )
        return IngestAck(accepted=True, message="dispense accepted", entity_id=entity_id)

    row = db.scalar(select(Tank).where(Tank.id == body.tank_id).with_for_update())
    if row is None or row.station_id != body.station_id:
        raise NotFoundError("резервуар не найден")
    if existing is not None:
        return ack_to_schema(build_ingest_ack(row, message="duplicate", duplicate=True, entity_id=existing.id))

    entity_id = uuid4()
    nested = db.begin_nested()
    try:
        apply_dispense_volume(row, body.volume_liters)
        db.add(
            DispenseRecord(
                id=entity_id,
                station_id=row.station_id,
                tank_id=row.id,
                dispenser_id=body.dispenser_id,
                volume_liters=body.volume_liters,
                started_at=body.started_at,
                finished_at=body.finished_at,
                external_txn_id=key,
                raw_payload=body.raw_payload,
            )
        )
        db.flush()
    except IntegrityError:
        nested.rollback()
        db.refresh(row)
        duplicate = db.scalar(select(DispenseRecord).where(DispenseRecord.external_txn_id == key))
        return ack_to_schema(
            build_ingest_ack(
                row,
                message="duplicate",
                duplicate=True,
                entity_id=None if duplicate is None else duplicate.id,
            )
        )
    nested.commit()
    return ack_to_schema(build_ingest_ack(row, message="dispense accepted", entity_id=entity_id))


def _commit(db: Session, ack: IngestAck) -> IngestAck:
    db.commit()
    return ack


def accept_level(body: LevelIngest) -> IngestAck:
    with session() as db:
        try:
            return _commit(db, _accept_level(db, body))
        except Exception:
            db.rollback()
            raise


def accept_dispense(body: DispenseIngest) -> IngestAck:
    with session() as db:
        try:
            return _commit(db, _accept_dispense(db, body))
        except Exception:
            db.rollback()
            raise


def accept_dispenses_batch(items: list[DispenseIngest]) -> DispenseBatchAck:
    """Один commit на пакет. Ошибка посередине откатывает уже принятые строки пакета."""
    with session() as db:
        results: list[IngestAck] = []
        try:
            for item in items:
                results.append(_accept_dispense(db, item))
            db.commit()
        except Exception:
            db.rollback()
            raise
    accepted, duplicates, total_volume = batch_counts(results, [item.volume_liters for item in items])
    return DispenseBatchAck(
        accepted_count=accepted,
        duplicates_count=duplicates,
        total_volume_liters=round(total_volume, 3),
        results=results,
    )


def accept_levels_batch(items: list[LevelIngest]) -> LevelBatchAck:
    """Один commit на пакет замеров. Ошибка посередине откатывает весь пакет."""
    with session() as db:
        results: list[IngestAck] = []
        try:
            for item in items:
                results.append(_accept_level(db, item))
            db.commit()
        except Exception:
            db.rollback()
            raise
    accepted, duplicates, _ = batch_counts(results)
    return LevelBatchAck(
        accepted_count=accepted,
        duplicates_count=duplicates,
        results=results,
    )


def accept_receipt(body: ReceiptIngest) -> IngestAck:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id)
    key = receipt_event_key(tank_id, body.recorded_at, body.source_event_id)
    with session() as db:
        row = db.scalar(select(Tank).where(Tank.id == tank_id).with_for_update())
        if row is None or row.station_id != station_id:
            raise NotFoundError("резервуар не найден")
        existing = db.scalar(select(ReceiptRecord).where(ReceiptRecord.source_event_id == key))
        if existing is not None:
            return ack_to_schema(build_ingest_ack(row, message="duplicate", duplicate=True, entity_id=existing.id))

        apply_receipt_volume(row, body.volume_liters)
        entity_id = uuid4()
        db.add(
            ReceiptRecord(
                id=entity_id,
                station_id=row.station_id,
                tank_id=row.id,
                volume_liters=body.volume_liters,
                recorded_at=body.recorded_at,
                source_event_id=key,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.get(Tank, tank_id)
            dup = db.scalar(select(ReceiptRecord).where(ReceiptRecord.source_event_id == key))
            assert row is not None
            return ack_to_schema(
                build_ingest_ack(
                    row,
                    message="duplicate",
                    duplicate=True,
                    entity_id=None if dup is None else dup.id,
                )
            )
        db.refresh(row)
        return ack_to_schema(build_ingest_ack(row, message="receipt accepted", entity_id=entity_id))


def list_level_readings(
    station_id: UUID,
    tank_id: UUID,
    *,
    since: datetime | None = None,
    limit: int = 50,
    newest_first: bool = True,
) -> list[LevelReading]:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None or row.station_id != station_id:
            raise NotFoundError("резервуар не найден")
        query = select(LevelReading).where(LevelReading.tank_id == tank_id)
        if since is not None:
            stamp = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
            query = query.where(LevelReading.recorded_at >= stamp)
        order = LevelReading.recorded_at.desc() if newest_first else LevelReading.recorded_at.asc()
        return list(db.scalars(query.order_by(order).limit(limit)).all())


def list_dispense_records(
    station_id: UUID,
    *,
    since: datetime | None = None,
    limit: int = 500,
) -> list[DispenseReadingOut]:
    with session() as db:
        query = select(DispenseRecord).where(DispenseRecord.station_id == station_id)
        if since is not None:
            stamp = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
            query = query.where(DispenseRecord.started_at >= stamp)
        rows = list(db.scalars(query.order_by(DispenseRecord.started_at.desc()).limit(limit)).all())
    return [
        build_dispense_out(
            record_id=row.id,
            station_id=row.station_id,
            tank_id=row.tank_id,
            dispenser_id=row.dispenser_id,
            volume_liters=row.volume_liters,
            started_at=row.started_at,
            finished_at=row.finished_at,
            external_txn_id=row.external_txn_id,
            raw_payload=row.raw_payload,
        )
        for row in rows
    ]


def _to_station_owner(rows: list[StationUser]) -> StationOwner:
    first = rows[0]
    kind = getattr(first, "kind", None) or "owner"
    return StationOwner(
        id=first.id,
        station_id=first.station_id,
        username=first.username,
        password_hash=first.password_hash,
        kind=kind,
        station_ids=[row.station_id for row in rows],
    )


def list_station_users(station_id: UUID) -> list[StationOwner]:
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        rows = list(
            db.scalars(
                select(StationUser).where(
                    StationUser.station_id == station_id,
                    StationUser.kind == "owner",
                )
            ).all()
        )
        return [_to_station_owner([row]) for row in rows]


def create_station_user(station_id: UUID, username: str, password: str) -> StationOwner:
    cleaned = clean_owner_username(
        username,
        get_settings().admin_username,
        empty_detail="укажите логин владельца",
    )
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        existing = list(db.scalars(select(StationUser).where(StationUser.username == cleaned)).all())
        if existing:
            already = next((row for row in existing if row.station_id == station_id), None)
            if already is None:
                row = StationUser(
                    id=uuid4(),
                    station_id=station_id,
                    username=cleaned,
                    password_hash=existing[0].password_hash,
                    kind="owner",
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                existing.append(row)
            return _to_station_owner(existing)
        require_owner_password(password)
        row = StationUser(
            id=uuid4(),
            station_id=station_id,
            username=cleaned,
            password_hash=hash_password(password),
            kind="owner",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_station_owner([row])


def authenticate_station_user(username: str, password: str) -> StationOwner | None:
    cleaned = username.strip().lower()
    if not cleaned:
        return None
    with session() as db:
        rows = list(
            db.scalars(
                select(StationUser)
                .where(StationUser.username == cleaned)
                .order_by(StationUser.created_at)
            ).all()
        )
        if not rows:
            return None
        if not verify_password(password, rows[0].password_hash):
            return None
        return _to_station_owner(rows)


def import_memory_snapshot(data: dict) -> None:
    """Разовый импорт state.json в пустую БД Postgres при старте."""
    catalog_data = data.get("catalog") if isinstance(data.get("catalog"), dict) else {}
    devices_data = data.get("devices") if isinstance(data.get("devices"), dict) else {}
    owners_data = data.get("owners") if isinstance(data.get("owners"), list) else []

    books_by_key: dict[tuple[UUID, UUID], dict] = {}
    for b in (devices_data or {}).get("books") or []:
        if isinstance(b, dict) and "station_id" in b and "tank_id" in b:
            books_by_key[(UUID(str(b["station_id"])), UUID(str(b["tank_id"])))] = b

    with session() as db:
        for row in (catalog_data or {}).get("stations") or []:
            if not isinstance(row, dict):
                continue
            db.add(
                Station(
                    id=UUID(str(row["id"])),
                    code=str(row["code"]).strip(),
                    name=str(row["name"]).strip(),
                    address=row.get("address"),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    is_active=bool(row.get("is_active", True)),
                )
            )
        for row in (catalog_data or {}).get("trucks") or []:
            if not isinstance(row, dict):
                continue
            db.add(
                Truck(
                    id=UUID(str(row["id"])),
                    plate_number=str(row["plate_number"]).strip(),
                    capacity_liters=float(row["capacity_liters"]),
                    carrier_name=row.get("carrier_name"),
                    status=str(row.get("status") or "idle"),
                    lat=None if row.get("lat") is None else float(row["lat"]),
                    lon=None if row.get("lon") is None else float(row["lon"]),
                )
            )
        for dev in (devices_data or {}).get("devices") or []:
            if not isinstance(dev, dict):
                continue
            sid = UUID(str(dev["station_id"]))
            tid = UUID(str(dev["tank_id"]))
            book = books_by_key.get((sid, tid), {})
            fields = extract_book_fields(book)
            cal = fields["calibration"]
            tank_row = Tank(
                id=tid,
                station_id=sid,
                code=str(dev["code"]).strip(),
                capacity_liters=float(dev["capacity_liters"]),
                has_electronic_sensor=True,
                level_source=LevelSource.electronic,
                ingest_token=str(dev.get("token") or secrets.token_urlsafe(24)),
                opening_liters=fields["opening_liters"],  # type: ignore[arg-type]
                receipts_liters=float(fields["receipts_liters"]),  # type: ignore[arg-type]
                dispense_liters=float(fields["dispense_liters"]),  # type: ignore[arg-type]
                pending_dispense_liters=float(fields["pending_dispense_liters"]),  # type: ignore[arg-type]
                pending_receipt_liters=float(fields["pending_receipt_liters"]),  # type: ignore[arg-type]
                actual_remainder_liters=fields["actual_remainder_liters"],  # type: ignore[arg-type]
                last_volts=fields["last_volts"],  # type: ignore[arg-type]
                last_measured_at=fields["last_measured_at"],  # type: ignore[arg-type]
                cal_low_volts=None if cal is None else cal.low_volts,  # type: ignore[union-attr]
                cal_low_percent=None if cal is None else cal.low_percent,  # type: ignore[union-attr]
                cal_high_volts=None if cal is None else cal.high_volts,  # type: ignore[union-attr]
                cal_high_percent=None if cal is None else cal.high_percent,  # type: ignore[union-attr]
            )
            recompute_tank_book(tank_row)
            db.add(tank_row)

        for owner in owners_data or []:
            if not isinstance(owner, dict):
                continue
            station_ids = owner.get("station_ids") or [owner.get("station_id")]
            for raw_sid in station_ids:
                if not raw_sid:
                    continue
                db.add(
                    StationUser(
                        id=uuid4(),
                        station_id=UUID(str(raw_sid)),
                        username=str(owner["username"]).strip().lower(),
                        password_hash=str(owner["password_hash"]),
                        kind="owner",
                    )
                )
        db.commit()
