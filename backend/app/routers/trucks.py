"""Truck endpoints."""

from uuid import UUID

from fastapi import APIRouter, Response

from app.schemas.truck import TruckCreate, TruckDetailOut, TruckOut, TruckUpdate
from app.services.account import (
    create_truck,
    delete_truck,
    get_truck,
    list_trucks,
    update_truck,
)
from app.services.catalog import TruckCard

router = APIRouter(prefix="/trucks", tags=["trucks"])


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


@router.delete("/{truck_id}", status_code=204)
def remove_truck_card(truck_id: UUID) -> Response:
    delete_truck(truck_id)
    return Response(status_code=204)


@router.get("/{truck_id}", response_model=TruckDetailOut)
def get_truck_card(truck_id: UUID) -> TruckDetailOut:
    truck = get_truck(truck_id)
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
