"""Порт учёта и общая сервисная оркестрация над адаптерами (memory / postgres)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from app.config import get_settings
from app.domain.entities import StationCard, StationOwner, TankDevice, TruckCard
from app.domain.errors import ForbiddenError, NotFoundError, ValidationError
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
from app.services import account_mode
from app.services.account_helpers import (
    clean_optional_text,
    clean_owner_username,
    gps_event_key,
    is_gps_seen,
    remember_gps,
    require_calibration_points,
    require_columns_count,
    require_columns_mode,
    require_non_empty,
    require_station_and_tank,
    require_truck_status,
)
from app.services.board_cache import invalidate_public_board_cache

TankDeletedHook = Callable[[UUID], None]
CalibrationHook = Callable[[UUID], bool]

_TANK_DELETED_HOOKS: list[TankDeletedHook] = []
_CALIBRATION_HOOKS: list[CalibrationHook] = []


def register_tank_deleted_hook(hook: TankDeletedHook) -> None:
    if hook not in _TANK_DELETED_HOOKS:
        _TANK_DELETED_HOOKS.append(hook)


def register_calibration_hook(hook: CalibrationHook) -> None:
    if hook not in _CALIBRATION_HOOKS:
        _CALIBRATION_HOOKS.append(hook)


def _notify_tank_deleted(tank_id: UUID) -> None:
    for hook in _TANK_DELETED_HOOKS:
        hook(tank_id)


def _notify_calibrated(tank_id: UUID) -> bool:
    applied = False
    for hook in _CALIBRATION_HOOKS:
        if hook(tank_id):
            applied = True
    return applied


def backend() -> Any:
    if account_mode.use_postgres():
        from app.services import postgres_account

        return postgres_account
    from app.services import memory_account

    return memory_account


def list_stations() -> list[StationCard]:
    return backend().list_stations()


def get_station(station_id: UUID) -> StationCard:
    return backend().get_station(station_id)


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
    station = backend().create_station(
        code=cleaned_code,
        name=cleaned_name,
        address=clean_optional_text(address),
        lat=lat,
        lon=lon,
        is_active=is_active,
        columns_mode=valid_mode,
        columns_count=valid_count,
    )
    invalidate_public_board_cache()
    return station


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
    cleaned_code = None if code is None else require_non_empty(code, "код заправки")
    cleaned_name = None if name is None else require_non_empty(name, "название заправки")
    valid_mode = None if columns_mode is None else require_columns_mode(columns_mode)
    valid_count = None if columns_count is None else require_columns_count(columns_count)
    station = backend().update_station(
        station_id,
        code=cleaned_code,
        name=cleaned_name,
        address=clean_optional_text(address) if address_set else None,
        lat=lat,
        lon=lon,
        is_active=is_active,
        columns_mode=valid_mode,
        columns_count=valid_count,
        address_set=address_set,
    )
    invalidate_public_board_cache()
    return station


def delete_station(station_id: UUID) -> None:
    deleted_tank_ids = backend().delete_station(station_id) or []
    for tank_id in deleted_tank_ids:
        _notify_tank_deleted(tank_id)
    invalidate_public_board_cache()


def list_trucks() -> list[TruckCard]:
    return backend().list_trucks()


def get_truck(truck_id: UUID) -> TruckCard:
    return backend().get_truck(truck_id)


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
    return backend().create_truck(
        plate_number=plate,
        capacity_liters=capacity_liters,
        carrier_name=clean_optional_text(carrier_name),
        status=valid_status,
        lat=lat,
        lon=lon,
    )


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
    plate = None if plate_number is None else require_non_empty(plate_number, "номер газовоза")
    valid_status = None if status is None else require_truck_status(status)
    return backend().update_truck(
        truck_id,
        plate_number=plate,
        capacity_liters=capacity_liters,
        carrier_name=clean_optional_text(carrier_name) if carrier_set else None,
        status=valid_status,
        lat=lat,
        lon=lon,
        carrier_set=carrier_set,
        lat_set=lat_set,
        lon_set=lon_set,
    )


def delete_truck(truck_id: UUID) -> None:
    backend().delete_truck(truck_id)


def record_truck_position(
    truck_id: UUID,
    *,
    lat: float,
    lon: float,
    recorded_at: datetime,
    source_event_id: str | None,
) -> IngestAck:
    """Пишет координату газовоза. Повтор того же ключа в этом процессе координату не двигает."""
    key = gps_event_key(truck_id, recorded_at, source_event_id)
    if is_gps_seen(key):
        return IngestAck(accepted=True, message="duplicate", duplicate=True, entity_id=truck_id)
    backend().update_truck(truck_id, lat=lat, lon=lon, lat_set=True, lon_set=True)
    remember_gps(key)
    return IngestAck(accepted=True, message="gps accepted", entity_id=truck_id)


def list_active_stations_with_tanks() -> list[tuple[StationCard, list[TankOut]]]:
    return backend().list_active_stations_with_tanks()


def list_all_stations_with_overview() -> list[tuple[StationCard, list[tuple[TankDevice, TankIngestState | None]]]]:
    return backend().list_all_stations_with_overview()


def rotate_tank_token(station_id: UUID, tank_id: UUID) -> TankDevice:
    return backend().rotate_tank_token(station_id, tank_id)


def list_tank_devices(station_id: UUID) -> list[TankDevice]:
    return backend().list_tank_devices(station_id)


def list_station_tanks_out(station_id: UUID) -> list[TankOut]:
    return backend().list_station_tanks_out(station_id)


def get_tank_device(station_id: UUID, tank_id: UUID) -> TankDevice:
    return backend().get_tank_device(station_id, tank_id)


def tank_by_token(token: str | None) -> TankDevice | None:
    return backend().tank_by_token(token)


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
    cleaned = require_non_empty(code, "код резервуара")
    store = backend()
    store.get_station(station_id)
    device = store.register_tank(station_id, cleaned, capacity_liters)
    invalidate_public_board_cache()
    return device


def update_tank_device(station_id: UUID, tank_id: UUID, **kwargs) -> TankDevice:
    if kwargs.get("code") is not None:
        kwargs["code"] = require_non_empty(str(kwargs["code"]), "код резервуара")
    device = backend().update_tank_device(station_id, tank_id, **kwargs)
    invalidate_public_board_cache()
    return device


def delete_tank_device(station_id: UUID, tank_id: UUID) -> None:
    backend().delete_tank_device(station_id, tank_id)
    _notify_tank_deleted(tank_id)
    invalidate_public_board_cache()


def has_calibration(station_id: UUID, tank_id: UUID) -> bool:
    return backend().has_calibration(station_id, tank_id)


def set_calibration(body: CalibrationIn) -> TankIngestState:
    station_id, tank_id = require_station_and_tank(body.station_id, body.tank_id, "укажите резервуар")
    require_calibration_points(body.low_volts, body.high_volts, body.low_percent, body.high_percent)
    store = backend()
    state = store.set_calibration(body.model_copy(update={"station_id": station_id, "tank_id": tank_id}))
    invalidate_public_board_cache()
    if _notify_calibrated(tank_id):
        invalidate_public_board_cache()
        try:
            state = store.tank_state(tank_id)
        except NotFoundError:
            pass
    return state


def tank_remainder(tank_id: UUID) -> tuple[float | None, datetime | None]:
    return backend().tank_remainder(tank_id)


def tank_state(tank_id: UUID) -> TankIngestState:
    return backend().tank_state(tank_id)


def accept_level(body: LevelIngest) -> IngestAck:
    require_station_and_tank(body.station_id, body.tank_id)
    ack = backend().accept_level(body)
    if not ack.duplicate and ack.message != "level unchanged":
        invalidate_public_board_cache()
    return ack


def accept_levels_batch(items: list[LevelIngest]) -> LevelBatchAck:
    for item in items:
        require_station_and_tank(item.station_id, item.tank_id)
    ack = backend().accept_levels_batch(items)
    if any((not r.duplicate and r.message != "level unchanged") for r in ack.results):
        invalidate_public_board_cache()
    return ack


def accept_dispense(body: DispenseIngest) -> IngestAck:
    ack = backend().accept_dispense(body)
    if not ack.duplicate:
        invalidate_public_board_cache()
    return ack


def accept_dispenses_batch(items: list[DispenseIngest]) -> DispenseBatchAck:
    ack = backend().accept_dispenses_batch(items)
    if ack.accepted_count > 0:
        invalidate_public_board_cache()
    return ack


def accept_receipt(body: ReceiptIngest) -> IngestAck:
    require_station_and_tank(body.station_id, body.tank_id)
    ack = backend().accept_receipt(body)
    if not ack.duplicate:
        invalidate_public_board_cache()
    return ack


def _assert_device_scope(
    device: TankDevice,
    station_id: UUID | None,
    tank_id: UUID | None,
) -> None:
    if station_id is not None and station_id != device.station_id:
        raise ForbiddenError("токен принадлежит другой заправке")
    if tank_id is not None and tank_id != device.tank_id:
        raise ForbiddenError("токен принадлежит другому резервуару")


def bind_level(body: LevelIngest, token: str | None) -> LevelIngest:
    device = tank_by_token(token)
    if device is not None:
        _assert_device_scope(device, body.station_id, body.tank_id)
        return body.model_copy(update={"station_id": device.station_id, "tank_id": device.tank_id})
    require_station_and_tank(body.station_id, body.tank_id)
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
    require_station_and_tank(body.station_id, body.tank_id)
    if body.capacity_liters is None:
        raise ValidationError("укажите объём резервуара на карточке")
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


def list_station_users(station_id: UUID) -> list[StationOwner]:
    store = backend()
    store.get_station(station_id)
    return store.list_station_users(station_id)


def create_station_user(station_id: UUID, username: str, password: str) -> StationOwner:
    cleaned = clean_owner_username(
        username,
        get_settings().admin_username,
        empty_detail="укажите логин владельца",
    )
    store = backend()
    store.get_station(station_id)
    return store.create_station_user(station_id, cleaned, password)


def authenticate_station_user(username: str, password: str) -> StationOwner | None:
    return backend().authenticate_station_user(username, password)


def has_owner(username: str) -> bool:
    return backend().has_owner(username)


def list_all_owners() -> list[StationOwner]:
    return backend().list_all_owners()


def create_owner_account(username: str, password: str, station_ids: list[UUID]) -> StationOwner:
    return backend().create_owner_account(username, password, station_ids)


def update_owner_account(
    username: str,
    *,
    station_ids: list[UUID] | None = None,
    password: str | None = None,
) -> StationOwner:
    return backend().update_owner_account(username, station_ids=station_ids, password=password)


def detach_station_user(station_id: UUID, username: str) -> None:
    backend().detach_station_user(station_id, username)


def delete_owner_account(username: str) -> None:
    backend().delete_owner_account(username)


def list_level_readings(station_id: UUID, tank_id: UUID, **kwargs):
    return backend().list_level_readings(station_id, tank_id, **kwargs)


def list_dispense_records(station_id: UUID, **kwargs):
    return backend().list_dispense_records(station_id, **kwargs)


def list_batches() -> list[dict]:
    return backend().list_batches()


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
    return backend().create_batch(
        trail_code=trail_code,
        supplier_id=supplier_id,
        factory_id=factory_id,
        product_grade=product_grade,
        density_kg_per_liter=density_kg_per_liter,
        volume_liters=volume_liters,
        mass_kg=mass_kg,
        notes=notes,
    )


def get_batch_by_code(trail_code: str) -> dict | None:
    return backend().get_batch_by_code(trail_code)


def get_batch_by_id(batch_id: UUID) -> dict | None:
    return backend().get_batch_by_id(batch_id)


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
    return backend().add_batch_event(
        batch_id,
        node_type=node_type,
        title=title,
        description=description,
        ref_entity_type=ref_entity_type,
        ref_entity_id=ref_entity_id,
        volume_liters=volume_liters,
        status=status,
    )


def update_batch_status(batch_id: UUID, status: str, note: str | None = None) -> dict:
    return backend().update_batch_status(batch_id, status, note)


__all__ = [
    "accept_dispense",
    "accept_dispenses_batch",
    "accept_level",
    "accept_levels_batch",
    "accept_receipt",
    "add_batch_event",
    "authenticate_station_user",
    "backend",
    "bind_calibration",
    "bind_dispense",
    "bind_level",
    "bind_receipt",
    "create_batch",
    "create_owner_account",
    "create_station",
    "create_station_user",
    "create_truck",
    "delete_owner_account",
    "delete_station",
    "delete_tank_device",
    "delete_truck",
    "detach_station_user",
    "get_batch_by_code",
    "get_batch_by_id",
    "get_station",
    "get_tank_device",
    "get_truck",
    "has_calibration",
    "has_owner",
    "list_active_stations_with_tanks",
    "list_all_owners",
    "list_all_stations_with_overview",
    "list_batches",
    "list_dispense_records",
    "list_level_readings",
    "list_station_tanks_out",
    "list_station_users",
    "list_stations",
    "list_tank_devices",
    "list_trucks",
    "record_truck_position",
    "register_calibration_hook",
    "register_tank",
    "register_tank_deleted_hook",
    "rotate_tank_token",
    "set_calibration",
    "tank_by_token",
    "tank_remainder",
    "tank_state",
    "update_batch_status",
    "update_owner_account",
    "update_station",
    "update_tank_device",
    "update_truck",
]
