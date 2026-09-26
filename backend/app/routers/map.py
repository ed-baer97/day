"""Map overview for main UI screen."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter

from app.routers.stations import _DEMO_STATIONS
from app.routers.trucks import _DEMO_TRUCKS
from app.schemas.common import MapOverviewOut, MapPoint

router = APIRouter(prefix="/map", tags=["map"])

_FACTORIES = [
    {
        "id": UUID("f1111111-1111-1111-1111-111111111101"),
        "name": "Завод Тольятти",
        "lat": 53.5078,
        "lon": 49.4204,
        "status": "online",
    }
]


@router.get("/overview", response_model=MapOverviewOut)
def map_overview() -> MapOverviewOut:
    points: list[MapPoint] = []
    for f in _FACTORIES:
        points.append(
            MapPoint(
                id=f["id"],
                kind="factory",
                name=f["name"],
                lat=f["lat"],
                lon=f["lon"],
                status=f["status"],
            )
        )
    for s in _DEMO_STATIONS:
        points.append(
            MapPoint(
                id=s["id"],
                kind="station",
                name=s["name"],
                lat=s["lat"],
                lon=s["lon"],
                status="active" if s["is_active"] else "inactive",
                meta={"code": s["code"]},
            )
        )
    for t in _DEMO_TRUCKS:
        points.append(
            MapPoint(
                id=t["id"],
                kind="truck",
                name=t["plate_number"],
                lat=t["lat"],
                lon=t["lon"],
                status=t["status"],
                meta={"destination": t.get("destination_name")},
            )
        )
    return MapOverviewOut(
        generated_at=datetime.now(timezone.utc),
        points=points,
        active_trips=sum(1 for t in _DEMO_TRUCKS if t["status"] in ("in_transit", "arrived")),
        open_events=1,
    )
