"""Обзорная карта сети АГЗС и парка газовозов."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.common import MapOverviewOut, MapPoint
from app.services.catalog import list_stations, list_trucks
from app.services.event_log import list_events

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/overview", response_model=MapOverviewOut)
def map_overview() -> MapOverviewOut:
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
    return MapOverviewOut(
        generated_at=datetime.now(timezone.utc),
        points=[*station_points, *truck_points],
        active_trips=active_trips,
        open_events=open_events,
    )
