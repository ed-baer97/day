"""Открытая витрина: остаток, процент и признак связи.

В режиме Postgres загружает все активные станции и их резервуары за 1 SQL-запрос (selectinload, без N+1).
В режиме memory читает остатки пакетно за 1 проход по бакам станции.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from app.config import get_settings
from app.schemas.public import PublicStationOut, PublicTankOut
from app.services.account import list_active_stations_with_tanks
from app.services.calibration import remainder_fill_percent

_cache_lock = threading.Lock()
_cached_rows: list[PublicStationOut] | None = None
_cached_at: float = 0.0
_CACHE_TTL_SEC: float = 2.5


def invalidate_public_board_cache() -> None:
    """Сбрасывает кэш витрины при поступлении свежих замеров."""
    global _cached_rows, _cached_at
    with _cache_lock:
        _cached_rows = None
        _cached_at = 0.0


def sensor_online(measured_at: datetime | None, *, now: datetime | None = None) -> bool:
    if measured_at is None:
        return False
    stamp = measured_at if measured_at.tzinfo is not None else measured_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age = (current - stamp).total_seconds()
    return age <= get_settings().sensor_stale_seconds


def list_public_stations() -> list[PublicStationOut]:
    global _cached_rows, _cached_at
    now_mono = time.monotonic()

    with _cache_lock:
        if _cached_rows is not None and (now_mono - _cached_at) < _CACHE_TTL_SEC:
            return _cached_rows

    now = datetime.now(timezone.utc)
    pairs = list_active_stations_with_tanks()

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

    with _cache_lock:
        _cached_rows = rows
        _cached_at = now_mono

    return rows
