"""Обзорная карта сети АГЗС и парка газовозов."""

import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.common import MapOverviewOut, MapPoint
from app.services.catalog import list_stations, list_trucks
from app.services.event_log import list_events

router = APIRouter(prefix="/map", tags=["map"])

_map_lock = threading.Lock()
_cached_map: MapOverviewOut | None = None
_cached_map_at: float = 0.0
_MAP_TTL_SEC: float = 3.0


def invalidate_map_cache() -> None:
    global _cached_map, _cached_map_at
    with _map_lock:
        _cached_map = None
        _cached_map_at = 0.0


@router.get("/overview", response_model=MapOverviewOut)
def map_overview() -> MapOverviewOut:
    global _cached_map, _cached_map_at
    now_mono = time.monotonic()

    with _map_lock:
        if _cached_map is not None and (now_mono - _cached_map_at) < _MAP_TTL_SEC:
            return _cached_map

    station_points = [
        MapPoint(
            id=station.id,
            kind="station",
            name=station.name,
            lat=station.lat,
            lon=station.lon,
            status="active" if station.is_active else "inactive",
            meta={"code": station.code},
        )
        for station in list_stations()
        if station.is_active
    ]
    trucks = list_trucks()
    truck_points = [
        MapPoint(
            id=truck.id,
            kind="truck",
            name=truck.plate_number,
            lat=truck.lat,
            lon=truck.lon,
            status=truck.status,
            meta={
                "plate_number": truck.plate_number,
                "capacity_liters": truck.capacity_liters,
                "carrier_name": truck.carrier_name,
            },
        )
        for truck in trucks
        if truck.lat is not None and truck.lon is not None
    ]
    active_trips = sum(1 for truck in trucks if truck.status in ("loading", "in_transit", "arrived", "unloading"))
    open_events = len(list_events(unresolved_only=True))
    overview = MapOverviewOut(
        generated_at=datetime.now(timezone.utc),
        points=[*station_points, *truck_points],
        active_trips=active_trips,
        open_events=open_events,
    )

    with _map_lock:
        _cached_map = overview
        _cached_map_at = now_mono

    return overview
