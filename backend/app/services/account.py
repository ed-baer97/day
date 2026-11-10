"""Порт учёта. Роутеры вызывают только его.

Режим memory или postgres выбирается здесь один раз на вызов.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.domain.errors import CalibrationRequired
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
from app.services.catalog import StationCard, TruckCard
from app.services.device_ingest import TankDevice


def backend() -> Any:
    from app.services.account_mode import use_postgres

    if use_postgres():
        from app.services import postgres_account

        return postgres_account
    from app.services import memory_account

    return memory_account


def _levels(call):
    try:
        return call()
    except CalibrationRequired as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc


def list_stations() -> list[StationCard]:
    return backend().list_stations()


def get_station(station_id: UUID) -> StationCard:
    return backend().get_station(station_id)


def create_station(**kwargs) -> StationCard:
    return backend().create_station(**kwargs)


def update_station(station_id: UUID, **kwargs) -> StationCard:
    return backend().update_station(station_id, **kwargs)


def delete_station(station_id: UUID) -> None:
    backend().delete_station(station_id)


def list_trucks() -> list[TruckCard]:
    return backend().list_trucks()


def get_truck(truck_id: UUID) -> TruckCard:
    return backend().get_truck(truck_id)


def create_truck(**kwargs) -> TruckCard:
    return backend().create_truck(**kwargs)


def update_truck(truck_id: UUID, **kwargs) -> TruckCard:
    return backend().update_truck(truck_id, **kwargs)


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
    return backend().record_truck_position(
        truck_id,
        lat=lat,
        lon=lon,
        recorded_at=recorded_at,
        source_event_id=source_event_id,
    )


def list_active_stations_with_tanks():
    return backend().list_active_stations_with_tanks()


def list_tank_devices(station_id: UUID) -> list[TankDevice]:
    return backend().list_tank_devices(station_id)


def list_station_tanks_out(station_id: UUID) -> list[TankOut]:
    return backend().list_station_tanks_out(station_id)


def get_tank_device(station_id: UUID, tank_id: UUID) -> TankDevice:
    return backend().get_tank_device(station_id, tank_id)


def tank_by_token(token: str | None) -> TankDevice | None:
    return backend().tank_by_token(token)


def register_tank(station_id: UUID, code: str, capacity_liters: float) -> TankDevice:
    return backend().register_tank(station_id, code, capacity_liters)


def update_tank_device(station_id: UUID, tank_id: UUID, **kwargs) -> TankDevice:
    return backend().update_tank_device(station_id, tank_id, **kwargs)


def delete_tank_device(station_id: UUID, tank_id: UUID) -> None:
    backend().delete_tank_device(station_id, tank_id)


def has_calibration(station_id: UUID, tank_id: UUID) -> bool:
    return backend().has_calibration(station_id, tank_id)


def set_calibration(body: CalibrationIn) -> TankIngestState:
    return backend().set_calibration(body)


def tank_remainder(tank_id: UUID):
    return backend().tank_remainder(tank_id)


def tank_state(tank_id: UUID) -> TankIngestState:
    return backend().tank_state(tank_id)


def accept_level(body: LevelIngest) -> IngestAck:
    return _levels(lambda: backend().accept_level(body))


def accept_levels_batch(items: list[LevelIngest]) -> LevelBatchAck:
    return _levels(lambda: backend().accept_levels_batch(items))


def accept_dispense(body: DispenseIngest) -> IngestAck:
    return backend().accept_dispense(body)


def accept_dispenses_batch(items: list[DispenseIngest]) -> DispenseBatchAck:
    return backend().accept_dispenses_batch(items)


def accept_receipt(body: ReceiptIngest) -> IngestAck:
    return backend().accept_receipt(body)


def bind_level(body: LevelIngest, token: str | None) -> LevelIngest:
    from app.services.device_ingest import bind_level as impl

    return impl(body, token)


def bind_calibration(body: CalibrationIn, token: str | None) -> CalibrationIn:
    from app.services.device_ingest import bind_calibration as impl

    return impl(body, token)


def bind_dispense(body: DispenseIngest, token: str | None) -> DispenseIngest:
    from app.services.device_ingest import bind_dispense as impl

    return impl(body, token)


def bind_receipt(body: ReceiptIngest, token: str | None) -> ReceiptIngest:
    from app.services.device_ingest import bind_receipt as impl

    return impl(body, token)


def list_station_users(station_id: UUID):
    return backend().list_station_users(station_id)


def create_station_user(station_id: UUID, username: str, password: str):
    return backend().create_station_user(station_id, username, password)


def authenticate_station_user(username: str, password: str):
    return backend().authenticate_station_user(username, password)


def list_level_readings(station_id: UUID, tank_id: UUID, **kwargs):
    return backend().list_level_readings(station_id, tank_id, **kwargs)
