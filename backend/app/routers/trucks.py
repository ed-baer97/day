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
        "plate_number": "А123ВС77",
        "capacity_liters": 18000,
        "carrier_name": "ГазТранс",
        "status": "in_transit",
        "lat": 55.7500,
        "lon": 37.4500,
        "recorded_at": _NOW,
        "supplier_name": "ООО ГазСнаб",
        "origin_name": "Завод Тольятти",
        "destination_name": "АГЗС Север",
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
            {"lat": 55.72, "lon": 37.40, "recorded_at": (_NOW - timedelta(minutes=30)).isoformat()},
            {"lat": 55.74, "lon": 37.43, "recorded_at": (_NOW - timedelta(minutes=15)).isoformat()},
            {"lat": 55.75, "lon": 37.45, "recorded_at": _NOW.isoformat()},
        ],
    },
    {
        "id": UUID("c1111111-1111-1111-1111-111111111102"),
        "plate_number": "В456ОР99",
        "capacity_liters": 20000,
        "carrier_name": "ЛПГ Логистика",
        "status": "arrived",
        "lat": 55.8701,
        "lon": 37.5450,
        "recorded_at": _NOW,
        "supplier_name": "ООО ГазСнаб",
        "origin_name": "Завод Тольятти",
        "destination_name": "АГЗС Север",
        "cargo_volume_liters": 0,
        "departed_at": _NOW - timedelta(hours=12),
        "arrived_at": _NOW - timedelta(hours=1),
        "trip_status": "unloading",
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
