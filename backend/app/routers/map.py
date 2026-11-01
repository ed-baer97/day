"""Map overview for main UI screen."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.common import MapOverviewOut, MapPoint
from app.services.catalog import list_stations

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/overview", response_model=MapOverviewOut)
def map_overview() -> MapOverviewOut:
    points = [
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
    return MapOverviewOut(
        generated_at=datetime.now(timezone.utc),
        points=points,
        active_trips=0,
        open_events=0,
    )
