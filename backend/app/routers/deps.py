"""Общие зависимости и конвертеры ответов для роутеров станций, резервуаров и Shelly."""

from __future__ import annotations

from uuid import UUID

from app.auth import Principal, require_station_access
from app.config import get_settings
from app.domain.entities import StationCard, TankDevice
from app.schemas.station import StationOut, TankDeviceOut
from app.services.account import get_station
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
