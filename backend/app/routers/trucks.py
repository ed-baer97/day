"""Truck endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.schemas.truck import TruckDetailOut, TruckOut, TruckTripOut

router = APIRouter(prefix="/trucks", tags=["trucks"])

_NOW = datetime.now(timezone.utc)

_DEMO_TRUCKS: list[dict] = [
    {
        "id": UUID("c1111111-1111-1111-1111-111111111101"),
        "plate_number": "705 ABA 12",
        "capacity_liters": 18000,
        "carrier_name": "ГазТранс Мангыстау",
        "status": "in_transit",
        "lat": 43.55,
        "lon": 52.05,
        "recorded_at": _NOW,
        "supplier_name": "ТОО КазГаз",
        "origin_name": "КазГаз",
        "destination_name": "АГЗС Актау · 12 мкр",
        "cargo_volume_liters": 16500,
        "departed_at": _NOW - timedelta(hours=4),
        "arrived_at": None,
        "trip_status": "in_transit",
        "route_geojson": None,
        "active_trip": {
            "id": UUID("d1111111-1111-1111-1111-111111111101"),
            "batch_id": UUID("e1111111-1111-1111-1111-111111111101"),
            "origin_factory_id": UUID("f1111111-1111-1111-1111-111111111101"),
            "destination_station_id": UUID("a1111111-1111-1111-1111-111111111101"),
            "loaded_volume_liters": 16500,
            "loaded_mass_kg": 8910,
            "status": "in_transit",
            "departed_at": _NOW - timedelta(hours=4),
            "arrived_at": None,
        },
        "recent_positions": [
            {"lat": 43.45, "lon": 52.25, "recorded_at": (_NOW - timedelta(minutes=30)).isoformat()},
            {"lat": 43.50, "lon": 52.15, "recorded_at": (_NOW - timedelta(minutes=15)).isoformat()},
            {"lat": 43.55, "lon": 52.05, "recorded_at": _NOW.isoformat()},
        ],
    },
    {
        "id": UUID("c1111111-1111-1111-1111-111111111102"),
        "plate_number": "701 ABA 12",
        "capacity_liters": 20000,
        "carrier_name": "ЛПГ Мангыстау",
        "status": "in_transit",
        "lat": 43.45,
        "lon": 52.35,
        "recorded_at": _NOW,
        "supplier_name": "ТОО КазГаз",
        "origin_name": "КазГаз",
        "destination_name": "АГЗС Жетыбай",
        "cargo_volume_liters": 12000,
        "departed_at": _NOW - timedelta(hours=2),
        "arrived_at": None,
        "trip_status": "in_transit",
        "route_geojson": None,
        "active_trip": None,
        "recent_positions": [],
    },
]


@router.get("", response_model=list[TruckOut])
def list_trucks() -> list[TruckOut]:
    return [
        TruckOut(
            id=t["id"],
            plate_number=t["plate_number"],
            capacity_liters=t["capacity_liters"],
            carrier_name=t["carrier_name"],
            status=t["status"],
        )
        for t in _DEMO_TRUCKS
    ]


@router.get("/{truck_id}", response_model=TruckDetailOut)
def get_truck(truck_id: UUID) -> TruckDetailOut:
    for t in _DEMO_TRUCKS:
        if t["id"] == truck_id:
            trip = TruckTripOut(**t["active_trip"]) if t.get("active_trip") else None
            return TruckDetailOut(
                id=t["id"],
                plate_number=t["plate_number"],
                capacity_liters=t["capacity_liters"],
                carrier_name=t["carrier_name"],
                status=t["status"],
                lat=t["lat"],
                lon=t["lon"],
                recorded_at=t["recorded_at"],
                supplier_name=t["supplier_name"],
                origin_name=t["origin_name"],
                destination_name=t["destination_name"],
                cargo_volume_liters=t["cargo_volume_liters"],
                departed_at=t["departed_at"],
                arrived_at=t["arrived_at"],
                trip_status=t["trip_status"],
                route_geojson=t["route_geojson"],
                active_trip=trip,
                recent_positions=t["recent_positions"],
            )
    raise HTTPException(status_code=404, detail="Truck not found")
