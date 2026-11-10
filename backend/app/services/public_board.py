"""Открытая витрина: остаток, процент и признак связи.

В режиме Postgres загружает все активные станции и их резервуары за 1 SQL-запрос (selectinload, без N+1).
В режиме memory читает остатки пакетно за 1 проход по бакам станции.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.schemas.public import PublicStationOut, PublicTankOut
from app.services.account_mode import use_postgres
from app.services.calibration import remainder_fill_percent
from app.services.catalog import list_stations
from app.services.device_ingest import list_station_tanks_out


def sensor_online(measured_at: datetime | None, *, now: datetime | None = None) -> bool:
    if measured_at is None:
        return False
    stamp = measured_at if measured_at.tzinfo is not None else measured_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age = (current - stamp).total_seconds()
    return age <= get_settings().sensor_stale_seconds


def list_public_stations() -> list[PublicStationOut]:
    now = datetime.now(timezone.utc)
    if use_postgres():
        from app.services import postgres_account

        pairs = postgres_account.list_active_stations_with_tanks()
    else:
        pairs = [
            (station, list_station_tanks_out(station.id))
            for station in list_stations()
            if station.is_active
        ]

    rows: list[PublicStationOut] = []
    for station, tank_outs in pairs:
        tanks = [
            PublicTankOut(
                code=tank.code,
                capacity_liters=tank.capacity_liters,
                remainder_liters=tank.actual_remainder_liters,
                fill_percent=remainder_fill_percent(tank.actual_remainder_liters, tank.capacity_liters),
                measured_at=tank.last_measured_at,
                online=sensor_online(tank.last_measured_at, now=now),
            )
            for tank in tank_outs
        ]
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
