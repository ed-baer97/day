"""Truck endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter

from app.schemas.truck import TruckCreate, TruckDetailOut, TruckOut, TruckTripOut, TruckUpdate
from app.services.catalog import TruckCard, create_truck, get_truck, list_trucks, update_truck

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


def _truck_out(truck: TruckCard) -> TruckOut:
    return TruckOut(
        id=truck.id,
        plate_number=truck.plate_number,
        capacity_liters=truck.capacity_liters,
        carrier_name=truck.carrier_name,
        status=truck.status,
        lat=truck.lat,
        lon=truck.lon,
    )


@router.get("", response_model=list[TruckOut])
def list_truck_cards() -> list[TruckOut]:
    return [_truck_out(truck) for truck in list_trucks()]


@router.post("", response_model=TruckOut, status_code=201)
def create_truck_card(body: TruckCreate) -> TruckOut:
    return _truck_out(
        create_truck(
            plate_number=body.plate_number,
            capacity_liters=body.capacity_liters,
            carrier_name=body.carrier_name,
            status=body.status,
            lat=body.lat,
            lon=body.lon,
        )
    )


@router.patch("/{truck_id}", response_model=TruckOut)
def patch_truck_card(truck_id: UUID, body: TruckUpdate) -> TruckOut:
    fields = body.model_fields_set
    return _truck_out(
        update_truck(
            truck_id,
            plate_number=body.plate_number if "plate_number" in fields else None,
            capacity_liters=body.capacity_liters if "capacity_liters" in fields else None,
            carrier_name=body.carrier_name,
            status=body.status if "status" in fields else None,
            lat=body.lat,
            lon=body.lon,
            carrier_set="carrier_name" in fields,
            lat_set="lat" in fields,
            lon_set="lon" in fields,
        )
    )


@router.get("/{truck_id}", response_model=TruckDetailOut)
def get_truck_card(truck_id: UUID) -> TruckDetailOut:
    truck = get_truck(truck_id)
    for demo in _DEMO_TRUCKS:
        if demo["id"] == truck_id:
            trip = TruckTripOut(**demo["active_trip"]) if demo.get("active_trip") else None
            return TruckDetailOut(
                id=truck.id,
                plate_number=truck.plate_number,
                capacity_liters=truck.capacity_liters,
                carrier_name=truck.carrier_name,
                status=truck.status,
                lat=truck.lat if truck.lat is not None else demo["lat"],
                lon=truck.lon if truck.lon is not None else demo["lon"],
                recorded_at=demo["recorded_at"],
                supplier_name=demo["supplier_name"],
                origin_name=demo["origin_name"],
                destination_name=demo["destination_name"],
                cargo_volume_liters=demo["cargo_volume_liters"],
                departed_at=demo["departed_at"],
                arrived_at=demo["arrived_at"],
                trip_status=demo["trip_status"],
                route_geojson=demo["route_geojson"],
                active_trip=trip,
                recent_positions=demo["recent_positions"],
            )
    return TruckDetailOut(
        id=truck.id,
        plate_number=truck.plate_number,
        capacity_liters=truck.capacity_liters,
        carrier_name=truck.carrier_name,
        status=truck.status,
        lat=truck.lat,
        lon=truck.lon,
        recent_positions=[],
    )
