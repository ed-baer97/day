"""Открытая витрина: остаток, процент и признак связи.

Считает то, что роутер раньше держал у себя. Ключей и сверки здесь нет.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.schemas.public import PublicStationOut, PublicTankOut
from app.services.calibration import remainder_fill_percent
from app.services.catalog import list_stations
from app.services.device_ingest import list_tank_devices, tank_remainder


def sensor_online(measured_at: datetime | None, *, now: datetime | None = None) -> bool:
    if measured_at is None:
        return False
    stamp = measured_at if measured_at.tzinfo is not None else measured_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age = (current - stamp).total_seconds()
    return age <= get_settings().sensor_stale_seconds


def list_public_stations() -> list[PublicStationOut]:
    rows: list[PublicStationOut] = []
    for station in list_stations():
        if not station.is_active:
            continue
        tanks: list[PublicTankOut] = []
        for device in list_tank_devices(station.id):
            remainder, measured_at = tank_remainder(device.tank_id)
            tanks.append(
                PublicTankOut(
                    code=device.code,
                    capacity_liters=device.capacity_liters,
                    remainder_liters=remainder,
                    fill_percent=remainder_fill_percent(remainder, device.capacity_liters),
                    measured_at=measured_at,
                    online=sensor_online(measured_at),
                )
            )
        rows.append(
            PublicStationOut(
                code=station.code,
                name=station.name,
                address=station.address,
                lat=station.lat,
                lon=station.lon,
                tanks=tanks,
            )
        )
    return rows
