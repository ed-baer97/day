"""Общие зависимости и конвертеры ответов для роутеров станций, резервуаров и Shelly."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.auth import Principal, require_station_access
from app.config import get_settings
from app.domain.calibration import remainder_fill_percent
from app.domain.entities import StationCard, TankDevice
from app.schemas.ingest import TankIngestState
from app.schemas.station import (
    AdminStationOverviewOut,
    AdminTankOverviewOut,
    StationOut,
    TankDeviceOut,
)
from app.services.account import get_station
from app.services.public_board import sensor_online
from app.services.shelly_link import shelly_view


def station_to_out(station: StationCard) -> StationOut:
    return StationOut(
        id=station.id,
        code=station.code,
        name=station.name,
        address=station.address,
        lat=station.lat,
        lon=station.lon,
        is_active=station.is_active,
        columns_mode=station.columns_mode,
        columns_count=station.columns_count,
    )


def overview_station_to_out(
    station: StationCard,
    pairs: list[tuple[TankDevice, TankIngestState | None]],
    now: datetime,
) -> AdminStationOverviewOut:
    tanks: list[AdminTankOverviewOut] = []
    for device, state in pairs:
        actual = None if state is None else state.actual_remainder_liters
        last_measured = None if state is None else state.last_measured_at
        tanks.append(
            AdminTankOverviewOut(
                id=device.tank_id,
                code=device.code,
                capacity_liters=device.capacity_liters,
                ingest_token=device.token,
                actual_remainder_liters=actual,
                calculated_remainder_liters=None if state is None else state.calculated_remainder_liters,
                fill_percent=remainder_fill_percent(actual, device.capacity_liters),
                opening_liters=None if state is None else state.opening_liters,
                receipts_liters=0.0 if state is None else state.receipts_liters,
                dispense_liters=0.0 if state is None else state.dispense_liters,
                delta_liters=None if state is None else state.delta_liters,
                balance_status="unknown" if state is None else state.balance_status,
                calibrated=False if state is None else state.calibrated,
                cal_low_volts=None if state is None else state.cal_low_volts,
                cal_low_percent=None if state is None else state.cal_low_percent,
                cal_high_volts=None if state is None else state.cal_high_volts,
                cal_high_percent=None if state is None else state.cal_high_percent,
                last_volts=None if state is None else state.last_volts,
                last_measured_at=last_measured,
                online=sensor_online(last_measured, now=now),
                shelly=shelly_view(device.tank_id),
            )
        )
    return AdminStationOverviewOut(
        **station_to_out(station).model_dump(),
        tanks=tanks,
    )


def require_existing_station_access(station_id: UUID, principal: Principal) -> StationCard:
    station = get_station(station_id)
    require_station_access(station_id, principal)
    return station


def device_to_out(device: TankDevice) -> TankDeviceOut:
    settings = get_settings()
    return TankDeviceOut(
        id=device.tank_id,
        station_id=device.station_id,
        code=device.code,
        capacity_liters=device.capacity_liters,
        ingest_token=device.token,
        level_path=settings.ingest_level_path,
        ingest_url=settings.ingest_level_url,
        shelly=shelly_view(device.tank_id),
    )
