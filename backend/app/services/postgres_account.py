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

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.domain.calibration import LevelCalibration
from app.domain.entities import (
    ShiftColumnSummary,
    ShiftTankSnapshot,
    StationCard,
    StationOwner,
    StationShift,
    TankDevice,
    TruckCard,
)
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.tank_book import (
    apply_dispense_volume,
    apply_level_reading,
    apply_receipt_volume,
    build_ingest_ack,
    build_tank_ingest_state,
    recompute_tank_book,
)
from app.services.balance_log import publish_pending_sensor_alert
from app.models.batch import Batch, BatchStatus, BatchTrailEvent, TrailNodeType
from app.models.dispenser import DispenseRecord, ReceiptRecord
from app.models.shift import StationShiftRecord
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
    batch_status_node_value,
    batch_status_title,
    build_dispense_out,
    build_tank_out,
    clean_optional_text,
    clean_owner_username,
    dispense_event_key,
    dump_shift_columns,
    dump_shift_tanks,
    extract_book_fields,
    level_event_key,
    load_shift_columns,
    load_shift_tanks,
    parse_iso_utc,
    receipt_event_key,
    require_calibration_points,
    require_columns_count,
    require_columns_mode,
    require_non_empty,
    require_owner_password,
    require_station_and_tank,
    require_truck_status,
    require_user_password,
    state_to_schema,
)
from app.services.passwords import hash_password, verify_password
from app.services.trail import make_trail_event_payload

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
        columns_mode=getattr(row, "columns_mode", None) or "none",
        columns_count=getattr(row, "columns_count", None) if getattr(row, "columns_count", None) is not None else 2,
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
    cal = _calibration(row)
    return state_to_schema(
        build_tank_ingest_state(
            row,
            station_id=row.station_id,
            tank_id=row.id,
            calibrated=cal is not None,
            calibration=cal,
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


def list_all_stations_with_overview() -> list[tuple[StationCard, list[tuple[TankDevice, TankIngestState | None]]]]:
    """Пакетно загружает все АГЗС (включая скрытые) и их резервуары для кабинета администратора."""
    with session() as db:
        stmt = (
            select(Station)
            .options(selectinload(Station.tanks))
            .order_by(Station.code)
        )
        stations = db.scalars(stmt).all()
        result: list[tuple[StationCard, list[tuple[TankDevice, TankIngestState | None]]]] = []
        for st in stations:
            sorted_tanks = sorted(st.tanks, key=lambda item: item.code)
            pairs = [(_device(t), _state(t)) for t in sorted_tanks]
            result.append((_card(st), pairs))
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
    columns_mode: str = "none",
    columns_count: int = 2,
) -> StationCard:
    cleaned_code = require_non_empty(code, "код заправки")
    cleaned_name = require_non_empty(name, "название заправки")
    valid_mode = require_columns_mode(columns_mode)
    valid_count = require_columns_count(columns_count)
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
            columns_mode=valid_mode,
            columns_count=valid_count,
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
    columns_mode: str | None = None,
    columns_count: int | None = None,
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
        if columns_mode is not None:
            row.columns_mode = require_columns_mode(columns_mode)
        if columns_count is not None:
            row.columns_count = require_columns_count(columns_count)
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


def rotate_tank_token(station_id: UUID, tank_id: UUID) -> TankDevice:
    with session() as db:
        row = db.get(Tank, tank_id)
        if row is None or row.station_id != station_id:
            raise NotFoundError("резервуар не найден")
        row.ingest_token = secrets.token_urlsafe(24)
        db.commit()
        db.refresh(row)
        return _device(row)


def has_calibration(station_id: UUID, tank_id: UUID) -> bool:
    with session() as db:
        row = db.get(Tank, tank_id)
        return row is not None and row.station_id == station_id and _calibration(row) is not None


def set_calibration(body: CalibrationIn) -> TankIngestState:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id, "укажите резервуар")
    require_calibration_points(body.low_volts, body.high_volts, body.low_percent, body.high_percent)
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
            recorded_at=body.recorded_at,
        )
        publish_pending_sensor_alert(row, station_id=station_id, tank_id=tank_id)
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
        apply_dispense_volume(row, body.volume_liters, at=body.started_at)
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

        apply_receipt_volume(row, body.volume_liters, at=body.recorded_at)
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
    until: datetime | None = None,
    limit: int = 500,
) -> list[DispenseReadingOut]:
    with session() as db:
        query = select(DispenseRecord).where(DispenseRecord.station_id == station_id)
        effective_at = func.coalesce(DispenseRecord.finished_at, DispenseRecord.started_at)
        if since is not None:
            stamp = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
            query = query.where(effective_at >= stamp)
        if until is not None:
            stamp_until = until if until.tzinfo is not None else until.replace(tzinfo=timezone.utc)
            query = query.where(effective_at <= stamp_until)
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


def list_receipt_volume(station_id: UUID, *, since: datetime, until: datetime) -> float:
    since_utc = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
    until_utc = until if until.tzinfo is not None else until.replace(tzinfo=timezone.utc)
    with session() as db:
        total = db.scalar(
            select(func.coalesce(func.sum(ReceiptRecord.volume_liters), 0.0)).where(
                ReceiptRecord.station_id == station_id,
                ReceiptRecord.recorded_at >= since_utc,
                ReceiptRecord.recorded_at <= until_utc,
            )
        )
    return round(float(total or 0.0), 3)


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
            if existing[0].kind != "owner":
                raise ConflictError("логин уже занят кассиром")
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


def has_owner(username: str) -> bool:
    cleaned = username.strip().lower()
    if not cleaned:
        return False
    with session() as db:
        row = db.scalar(
            select(StationUser).where(
                StationUser.username == cleaned,
                StationUser.kind == "owner",
            )
        )
        return row is not None


def list_all_owners() -> list[StationOwner]:
    with session() as db:
        rows = list(
            db.scalars(
                select(StationUser)
                .where(StationUser.kind == "owner")
                .order_by(StationUser.username, StationUser.created_at)
            ).all()
        )
        grouped: dict[str, list[StationUser]] = {}
        for row in rows:
            grouped.setdefault(row.username, []).append(row)
        return [_to_station_owner(grouped[name]) for name in sorted(grouped.keys())]


def create_owner_account(username: str, password: str, station_ids: list[UUID]) -> StationOwner:
    cleaned = clean_owner_username(
        username,
        get_settings().admin_username,
        empty_detail="укажите логин владельца",
    )
    require_owner_password(password)
    unique_ids = list(dict.fromkeys(station_ids))
    if not unique_ids:
        raise ValidationError("укажите хотя бы одну АГЗС")
    with session() as db:
        existing_user = db.scalar(select(StationUser).where(StationUser.username == cleaned))
        if existing_user is not None:
            if existing_user.kind != "owner":
                raise ConflictError("логин уже занят кассиром")
            raise ConflictError("владелец с таким логином уже существует")
        for sid in unique_ids:
            if db.get(Station, sid) is None:
                raise NotFoundError("Station not found")
        pwd_hash = hash_password(password)
        created_rows: list[StationUser] = []
        for sid in unique_ids:
            row = StationUser(
                id=uuid4(),
                station_id=sid,
                username=cleaned,
                password_hash=pwd_hash,
                kind="owner",
            )
            db.add(row)
            created_rows.append(row)
        db.commit()
        for row in created_rows:
            db.refresh(row)
        return _to_station_owner(created_rows)


def update_owner_account(
    username: str,
    *,
    station_ids: list[UUID] | None = None,
    password: str | None = None,
) -> StationOwner:
    cleaned = username.strip().lower()
    if not cleaned:
        raise NotFoundError("владелец не найден")
    with session() as db:
        rows = list(
            db.scalars(
                select(StationUser)
                .where(StationUser.username == cleaned, StationUser.kind == "owner")
                .order_by(StationUser.created_at)
            ).all()
        )
        if not rows:
            raise NotFoundError("владелец не найден")
        pwd_hash = rows[0].password_hash
        if password is not None:
            require_owner_password(password)
            pwd_hash = hash_password(password)
            for row in rows:
                row.password_hash = pwd_hash
        if station_ids is not None:
            unique_ids = list(dict.fromkeys(station_ids))
            if not unique_ids:
                raise ValidationError("оставьте хотя бы одну АГЗС или удалите владельца")
            for sid in unique_ids:
                if db.get(Station, sid) is None:
                    raise NotFoundError("Station not found")
            target_set = set(unique_ids)
            existing_by_sid = {row.station_id: row for row in rows}
            for sid, row in existing_by_sid.items():
                if sid not in target_set:
                    db.delete(row)
            kept = [row for row in rows if row.station_id in target_set]
            for sid in unique_ids:
                if sid not in existing_by_sid:
                    new_row = StationUser(
                        id=uuid4(),
                        station_id=sid,
                        username=cleaned,
                        password_hash=pwd_hash,
                        kind="owner",
                    )
                    db.add(new_row)
                    kept.append(new_row)
            rows = kept
        db.commit()
        for row in rows:
            db.refresh(row)
        return _to_station_owner(rows)


def detach_station_user(station_id: UUID, username: str) -> None:
    cleaned = username.strip().lower()
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        row = db.scalar(
            select(StationUser).where(
                StationUser.station_id == station_id,
                StationUser.username == cleaned,
                StationUser.kind == "owner",
            )
        )
        if row is None:
            raise NotFoundError("владелец не привязан к этой АГЗС")
        db.delete(row)
        db.commit()


def delete_owner_account(username: str) -> None:
    cleaned = username.strip().lower()
    with session() as db:
        rows = list(
            db.scalars(
                select(StationUser).where(
                    StationUser.username == cleaned,
                    StationUser.kind == "owner",
                )
            ).all()
        )
        if not rows:
            raise NotFoundError("владелец не найден")
        for row in rows:
            db.delete(row)
        db.commit()


def list_station_cashiers(station_id: UUID) -> list[StationOwner]:
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        rows = list(
            db.scalars(
                select(StationUser)
                .where(
                    StationUser.station_id == station_id,
                    StationUser.kind == "cashier",
                )
                .order_by(StationUser.username)
            ).all()
        )
        return [_to_station_owner([row]) for row in rows]


def list_cashiers_for_stations(station_ids: list[UUID] | None = None) -> list[StationOwner]:
    with session() as db:
        stmt = select(StationUser).where(StationUser.kind == "cashier")
        if station_ids is not None:
            if not station_ids:
                return []
            stmt = stmt.where(StationUser.station_id.in_(station_ids))
        rows = list(db.scalars(stmt.order_by(StationUser.username)).all())
        return [_to_station_owner([row]) for row in rows]


def create_station_cashier(station_id: UUID, username: str, password: str) -> StationOwner:
    cleaned = clean_owner_username(
        username,
        get_settings().admin_username,
        empty_detail="укажите логин кассира",
    )
    require_user_password(password, "кассира")
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        if db.scalar(select(StationUser).where(StationUser.username == cleaned)) is not None:
            raise ConflictError("пользователь с таким логином уже существует")
        row = StationUser(
            id=uuid4(),
            station_id=station_id,
            username=cleaned,
            password_hash=hash_password(password),
            kind="cashier",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_station_owner([row])


def update_station_cashier(
    station_id: UUID,
    username: str,
    *,
    password: str | None = None,
    new_station_id: UUID | None = None,
) -> StationOwner:
    cleaned = username.strip().lower()
    if not cleaned:
        raise NotFoundError("кассир не найден")
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        row = db.scalar(
            select(StationUser).where(
                StationUser.station_id == station_id,
                StationUser.username == cleaned,
                StationUser.kind == "cashier",
            )
        )
        if row is None:
            raise NotFoundError("кассир не найден")
        if password is not None:
            require_user_password(password, "кассира")
            row.password_hash = hash_password(password)
        if new_station_id is not None:
            if db.get(Station, new_station_id) is None:
                raise NotFoundError("Station not found")
            row.station_id = new_station_id
        db.commit()
        db.refresh(row)
        return _to_station_owner([row])


def delete_station_cashier(station_id: UUID, username: str) -> None:
    cleaned = username.strip().lower()
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        row = db.scalar(
            select(StationUser).where(
                StationUser.station_id == station_id,
                StationUser.username == cleaned,
                StationUser.kind == "cashier",
            )
        )
        if row is None:
            raise NotFoundError("кассир не найден")
        db.delete(row)
        db.commit()


def _to_station_shift(row: StationShiftRecord) -> StationShift:
    return StationShift(
        id=row.id,
        station_id=row.station_id,
        status=row.status,
        opened_by=row.opened_by,
        opened_at=row.opened_at,
        closed_by=row.closed_by,
        closed_at=row.closed_at,
        opening_tank_liters=row.opening_tank_liters,
        closing_tank_liters=row.closing_tank_liters,
        opening_tanks=load_shift_tanks(row.opening_tanks_json),
        closing_tanks=load_shift_tanks(row.closing_tanks_json),
        receipts_liters=float(row.receipts_liters or 0.0),
        dispensed_liters=float(row.dispensed_liters or 0.0),
        dispense_count=int(row.dispense_count or 0),
        total_amount_kzt=row.total_amount_kzt,
        columns=load_shift_columns(row.columns_summary_json),
        tank_delta_liters=row.tank_delta_liters,
        discrepancy_liters=row.discrepancy_liters,
        note=row.note,
    )


def list_shifts(station_id: UUID, *, limit: int = 50) -> list[StationShift]:
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        rows = list(
            db.scalars(
                select(StationShiftRecord)
                .where(StationShiftRecord.station_id == station_id)
                .order_by(StationShiftRecord.opened_at.desc())
                .limit(max(1, limit))
            ).all()
        )
        return [_to_station_shift(row) for row in rows]


def get_shift(station_id: UUID, shift_id: UUID) -> StationShift:
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        row = db.scalar(
            select(StationShiftRecord).where(
                StationShiftRecord.id == shift_id,
                StationShiftRecord.station_id == station_id,
            )
        )
        if row is None:
            raise NotFoundError("смена не найдена")
        return _to_station_shift(row)


def get_open_shift(station_id: UUID) -> StationShift | None:
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        row = db.scalar(
            select(StationShiftRecord)
            .where(
                StationShiftRecord.station_id == station_id,
                StationShiftRecord.status == "open",
            )
            .order_by(StationShiftRecord.opened_at.desc())
        )
        return None if row is None else _to_station_shift(row)


def open_shift(
    station_id: UUID,
    *,
    opened_by: str,
    opened_at: datetime,
    opening_tank_liters: float | None,
    opening_tanks: list[ShiftTankSnapshot],
    note: str | None = None,
) -> StationShift:
    cleaned_note = clean_optional_text(note)
    with session() as db:
        if db.scalar(select(Station).where(Station.id == station_id).with_for_update()) is None:
            raise NotFoundError("Station not found")
        existing = db.scalar(
            select(StationShiftRecord).where(
                StationShiftRecord.station_id == station_id,
                StationShiftRecord.status == "open",
            )
        )
        if existing is not None:
            raise ConflictError("на этой АГЗС уже открыта смена")
        row = StationShiftRecord(
            id=uuid4(),
            station_id=station_id,
            status="open",
            opened_by=opened_by,
            opened_at=opened_at,
            opening_tank_liters=opening_tank_liters,
            opening_tanks_json=dump_shift_tanks(opening_tanks),
            note=cleaned_note,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_station_shift(row)


def close_shift(
    station_id: UUID,
    shift_id: UUID,
    *,
    closed_by: str,
    closed_at: datetime,
    closing_tank_liters: float | None,
    closing_tanks: list[ShiftTankSnapshot],
    receipts_liters: float,
    dispensed_liters: float,
    dispense_count: int,
    total_amount_kzt: float | None,
    columns: list[ShiftColumnSummary],
    tank_delta_liters: float | None,
    discrepancy_liters: float | None,
    note: str | None = None,
) -> StationShift:
    cleaned_note = clean_optional_text(note)
    with session() as db:
        if db.get(Station, station_id) is None:
            raise NotFoundError("Station not found")
        row = db.scalar(
            select(StationShiftRecord)
            .where(
                StationShiftRecord.id == shift_id,
                StationShiftRecord.station_id == station_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("смена не найдена")
        if row.status != "open":
            raise ConflictError("смена уже закрыта")
        row.status = "closed"
        row.closed_by = closed_by
        row.closed_at = closed_at
        row.closing_tank_liters = closing_tank_liters
        row.closing_tanks_json = dump_shift_tanks(closing_tanks)
        row.receipts_liters = receipts_liters
        row.dispensed_liters = dispensed_liters
        row.dispense_count = dispense_count
        row.total_amount_kzt = total_amount_kzt
        row.columns_summary_json = dump_shift_columns(columns)
        row.tank_delta_liters = tank_delta_liters
        row.discrepancy_liters = discrepancy_liters
        if cleaned_note is not None:
            row.note = cleaned_note
        db.commit()
        db.refresh(row)
        return _to_station_shift(row)


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _batch_public(row: Batch) -> dict:
    return {
        "id": row.id,
        "trail_code": row.trail_code,
        "supplier_id": row.supplier_id,
        "factory_id": row.factory_id,
        "product_grade": row.product_grade,
        "density_kg_per_liter": row.density_kg_per_liter,
        "volume_liters": row.volume_liters,
        "mass_kg": row.mass_kg,
        "status": _enum_str(row.status),
        "formed_at": row.formed_at,
        "notes": row.notes,
        "created_at": row.created_at,
    }


def _batch_event_dict(ev: BatchTrailEvent) -> dict:
    return {
        "id": ev.id,
        "node_type": _enum_str(ev.node_type),
        "occurred_at": ev.occurred_at,
        "title": ev.title,
        "description": ev.description,
        "ref_entity_type": ev.ref_entity_type,
        "ref_entity_id": ev.ref_entity_id,
        "volume_liters": ev.volume_liters,
        "lat": ev.lat,
        "lon": ev.lon,
    }


def _batch_with_events(row: Batch) -> dict:
    ordered = sorted(
        row.trail_events,
        key=lambda ev: (ev.occurred_at, ev.created_at or ev.occurred_at, str(ev.id)),
    )
    return {
        **_batch_public(row),
        "events": [_batch_event_dict(ev) for ev in ordered],
    }


def _new_trail_event_row(
    batch_id: UUID,
    node_type: TrailNodeType,
    payload: dict,
    created_at: datetime,
) -> BatchTrailEvent:
    return BatchTrailEvent(
        id=uuid4(),
        batch_id=batch_id,
        node_type=node_type,
        occurred_at=payload["occurred_at"],
        title=payload["title"],
        description=payload["description"],
        ref_entity_type=payload["ref_entity_type"],
        ref_entity_id=payload["ref_entity_id"],
        volume_liters=payload["volume_liters"],
        lat=payload["lat"],
        lon=payload["lon"],
        created_at=created_at,
    )


def list_batches() -> list[dict]:
    with session() as db:
        rows = db.scalars(select(Batch).order_by(Batch.created_at.desc())).all()
        return [_batch_public(row) for row in rows]


def create_batch(
    *,
    trail_code: str,
    supplier_id: UUID | None,
    factory_id: UUID | None,
    product_grade: str | None,
    density_kg_per_liter: float | None,
    volume_liters: float,
    mass_kg: float | None,
    notes: str | None,
) -> dict:
    cleaned_code = require_non_empty(trail_code, "код партии")
    batch_id = uuid4()
    now = datetime.now(timezone.utc)
    with session() as db:
        existing = db.scalar(
            select(Batch.id).where(func.lower(Batch.trail_code) == cleaned_code.lower())
        )
        if existing is not None:
            raise ConflictError("партия с таким кодом уже зарегистрирована")
        row = Batch(
            id=batch_id,
            trail_code=cleaned_code,
            supplier_id=supplier_id,
            factory_id=factory_id,
            product_grade=product_grade,
            density_kg_per_liter=density_kg_per_liter,
            volume_liters=volume_liters,
            mass_kg=mass_kg,
            status=BatchStatus.formed,
            formed_at=now,
            notes=notes,
            created_at=now,
        )
        db.add(row)
        db.flush()
        payload = make_trail_event_payload(
            node_type=TrailNodeType.batch,
            title=f"Зарегистрирована партия {cleaned_code}",
            description=notes or f"Марка: {product_grade or 'ПБТ'}",
            ref_entity_type="batch",
            ref_entity_id=batch_id,
            volume_liters=volume_liters,
            occurred_at=now,
        )
        db.add(_new_trail_event_row(batch_id, TrailNodeType.batch, payload, now))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ConflictError("партия с таким кодом уже зарегистрирована") from exc
        db.refresh(row)
        return _batch_public(row)


def get_batch_by_code(trail_code: str) -> dict | None:
    cleaned = trail_code.strip().lower()
    if not cleaned:
        return None
    with session() as db:
        row = db.scalar(
            select(Batch)
            .where(func.lower(Batch.trail_code) == cleaned)
            .options(selectinload(Batch.trail_events))
        )
        return None if row is None else _batch_with_events(row)


def get_batch_by_id(batch_id: UUID) -> dict | None:
    with session() as db:
        row = db.scalar(
            select(Batch)
            .where(Batch.id == batch_id)
            .options(selectinload(Batch.trail_events))
        )
        return None if row is None else _batch_with_events(row)


def add_batch_event(
    batch_id: UUID,
    *,
    node_type: str,
    title: str,
    description: str | None = None,
    ref_entity_type: str | None = None,
    ref_entity_id: UUID | None = None,
    volume_liters: float | None = None,
    status: str | None = None,
) -> dict:
    try:
        node = TrailNodeType(node_type)
    except ValueError as exc:
        raise ValidationError("неизвестный тип события цепочки") from exc
    target_status: BatchStatus | None = None
    if status is not None:
        try:
            target_status = BatchStatus(status)
        except ValueError as exc:
            raise ValidationError("неизвестный статус партии") from exc

    now = datetime.now(timezone.utc)
    payload = make_trail_event_payload(
        node_type=node,
        title=title.strip(),
        description=description.strip() if description else None,
        ref_entity_type=ref_entity_type,
        ref_entity_id=ref_entity_id,
        volume_liters=volume_liters,
        occurred_at=now,
    )
    with session() as db:
        row = db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update())
        if row is None:
            raise NotFoundError("Batch not found")
        db.add(_new_trail_event_row(batch_id, node, payload, now))
        if target_status is not None:
            row.status = target_status
        db.commit()
        loaded = db.scalar(
            select(Batch)
            .where(Batch.id == batch_id)
            .options(selectinload(Batch.trail_events))
        )
        assert loaded is not None
        return _batch_with_events(loaded)


def update_batch_status(batch_id: UUID, status: str, note: str | None = None) -> dict:
    try:
        target_status = BatchStatus(status)
    except ValueError as exc:
        raise ValidationError("неизвестный статус партии") from exc
    node = TrailNodeType(batch_status_node_value(target_status.value))
    now = datetime.now(timezone.utc)
    payload = make_trail_event_payload(
        node_type=node,
        title=batch_status_title(target_status.value),
        description=note.strip() if note else None,
        ref_entity_type="batch",
        ref_entity_id=batch_id,
        occurred_at=now,
    )
    with session() as db:
        row = db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update())
        if row is None:
            raise NotFoundError("Batch not found")
        row.status = target_status
        db.add(_new_trail_event_row(batch_id, node, payload, now))
        db.commit()
        db.refresh(row)
        return _batch_public(row)


def _insert_batches_from_snapshot(
    db: Session,
    batches_data: list,
    *,
    skip_existing: bool = False,
) -> int:
    seen_ids: set[UUID] = set()
    seen_codes: set[str] = set()
    if skip_existing:
        for existing in db.scalars(select(Batch)).all():
            seen_ids.add(existing.id)
            seen_codes.add(existing.trail_code.strip().lower())

    imported = 0
    for row in batches_data or []:
        if not isinstance(row, dict):
            continue
        batch_id = UUID(str(row["id"]))
        trail_code = str(row["trail_code"]).strip()
        code_key = trail_code.lower()
        if not trail_code or batch_id in seen_ids or code_key in seen_codes:
            continue
        seen_ids.add(batch_id)
        seen_codes.add(code_key)

        created_at = parse_iso_utc(row.get("created_at")) or datetime.now(timezone.utc)
        formed_at = parse_iso_utc(row.get("formed_at"))
        batch_row = Batch(
            id=batch_id,
            trail_code=trail_code,
            supplier_id=None if not row.get("supplier_id") else UUID(str(row["supplier_id"])),
            factory_id=None if not row.get("factory_id") else UUID(str(row["factory_id"])),
            product_grade=row.get("product_grade"),
            density_kg_per_liter=row.get("density_kg_per_liter"),
            volume_liters=float(row["volume_liters"]),
            mass_kg=row.get("mass_kg"),
            status=BatchStatus(str(row.get("status") or "formed")),
            formed_at=formed_at,
            notes=row.get("notes"),
            created_at=created_at,
        )
        db.add(batch_row)
        db.flush()
        for ev in row.get("events") or []:
            if not isinstance(ev, dict):
                continue
            db.add(
                BatchTrailEvent(
                    id=UUID(str(ev["id"])),
                    batch_id=batch_id,
                    node_type=TrailNodeType(str(ev["node_type"])),
                    occurred_at=parse_iso_utc(ev.get("occurred_at")) or created_at,
                    title=str(ev["title"]),
                    description=ev.get("description"),
                    ref_entity_type=ev.get("ref_entity_type"),
                    ref_entity_id=None
                    if not ev.get("ref_entity_id")
                    else UUID(str(ev["ref_entity_id"])),
                    volume_liters=ev.get("volume_liters"),
                    lat=ev.get("lat"),
                    lon=ev.get("lon"),
                    created_at=created_at,
                )
            )
        imported += 1
    return imported


def import_batches_snapshot(batches_data: list) -> int:
    """Доимпортирует партии из state.json в Postgres, пропуская уже существующие."""
    if not batches_data:
        return 0
    with session() as db:
        imported = _insert_batches_from_snapshot(db, batches_data, skip_existing=True)
        db.commit()
        return imported


def import_memory_snapshot(data: dict) -> None:
    """Разовый импорт state.json в пустую БД Postgres при старте."""
    catalog_data = data.get("catalog") if isinstance(data.get("catalog"), dict) else {}
    devices_data = data.get("devices") if isinstance(data.get("devices"), dict) else {}
    owners_data = data.get("owners") if isinstance(data.get("owners"), list) else []
    batches_data = data.get("batches") if isinstance(data.get("batches"), list) else []
    shifts_data = data.get("shifts") if isinstance(data.get("shifts"), list) else []

    books_by_key: dict[tuple[UUID, UUID], dict] = {}
    for b in (devices_data or {}).get("books") or []:
        if isinstance(b, dict) and "station_id" in b and "tank_id" in b:
            books_by_key[(UUID(str(b["station_id"])), UUID(str(b["tank_id"])))] = b

    with session() as db:
        for row in (catalog_data or {}).get("stations") or []:
            if not isinstance(row, dict):
                continue
            code = str(row["code"]).strip()
            name = str(row["name"]).strip()
            default_mode = (
                "virtual"
                if ("rekon" in name.lower() or code.lower() in {"agzs-akt-12", "akt-12mkr"})
                else "none"
            )
            db.add(
                Station(
                    id=UUID(str(row["id"])),
                    code=code,
                    name=name,
                    address=row.get("address"),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    is_active=bool(row.get("is_active", True)),
                    columns_mode=str(row.get("columns_mode") or default_mode),
                    columns_count=int(row["columns_count"]) if row.get("columns_count") is not None else 2,
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
                sensor_watch_liters=fields["sensor_watch_liters"],  # type: ignore[arg-type]
                sensor_watch_at=fields["sensor_watch_at"],  # type: ignore[arg-type]
                sensor_watch_receipts=float(fields["sensor_watch_receipts"]),  # type: ignore[arg-type]
                sensor_watch_dispense=float(fields["sensor_watch_dispense"]),  # type: ignore[arg-type]
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
            kind = str(owner.get("kind") or "owner")
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
                        kind=kind,
                    )
                )
        for shift in shifts_data or []:
            if not isinstance(shift, dict) or not shift.get("id") or not shift.get("station_id"):
                continue
            opened_at = parse_iso_utc(shift.get("opened_at"))
            if opened_at is None:
                continue
            db.add(
                StationShiftRecord(
                    id=UUID(str(shift["id"])),
                    station_id=UUID(str(shift["station_id"])),
                    status=str(shift.get("status") or "open"),
                    opened_by=str(shift.get("opened_by") or ""),
                    closed_by=None if shift.get("closed_by") is None else str(shift["closed_by"]),
                    opened_at=opened_at,
                    closed_at=parse_iso_utc(shift.get("closed_at")),
                    opening_tank_liters=None
                    if shift.get("opening_tank_liters") is None
                    else float(shift["opening_tank_liters"]),
                    opening_tanks_json=dump_shift_tanks(load_shift_tanks(shift.get("opening_tanks"))),
                    closing_tank_liters=None
                    if shift.get("closing_tank_liters") is None
                    else float(shift["closing_tank_liters"]),
                    closing_tanks_json=dump_shift_tanks(load_shift_tanks(shift.get("closing_tanks"))),
                    receipts_liters=float(shift.get("receipts_liters") or 0.0),
                    dispensed_liters=float(shift.get("dispensed_liters") or 0.0),
                    dispense_count=int(shift.get("dispense_count") or 0),
                    total_amount_kzt=None
                    if shift.get("total_amount_kzt") is None
                    else float(shift["total_amount_kzt"]),
                    columns_summary_json=dump_shift_columns(load_shift_columns(shift.get("columns"))),
                    tank_delta_liters=None
                    if shift.get("tank_delta_liters") is None
                    else float(shift["tank_delta_liters"]),
                    discrepancy_liters=None
                    if shift.get("discrepancy_liters") is None
                    else float(shift["discrepancy_liters"]),
                    note=None if shift.get("note") is None else str(shift["note"]),
                )
            )
        _insert_batches_from_snapshot(db, batches_data, skip_existing=False)
        db.commit()
