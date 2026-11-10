"""Роутер паспортов АГЗС (/api/v1/stations)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.auth import Principal, require_admin, require_principal, require_station_access
from app.domain.tank_book import summarize_station_tanks
from app.schemas.station import (
    StationCreate,
    StationDetailOut,
    StationOut,
    StationUpdate,
)
from app.services.catalog import (
    StationCard,
    create_station,
    delete_station,
    get_station,
    list_stations,
    update_station,
)
from app.services.device_ingest import list_station_tanks_out

router = APIRouter(prefix="/stations", tags=["stations"])


def station_to_out(station: StationCard) -> StationOut:
    return StationOut(
        id=station.id,
        code=station.code,
        name=station.name,
        address=station.address,
        lat=station.lat,
        lon=station.lon,
        is_active=station.is_active,
    )


def require_existing_station_access(station_id: UUID, principal: Principal) -> StationCard:
    station = get_station(station_id)
    require_station_access(station_id, principal)
    return station


@router.get("", response_model=list[StationOut])
def list_station_cards(principal: Principal = Depends(require_principal)) -> list[StationOut]:
    rows = list_stations()
    if not principal.is_admin:
        allowed = set(principal.stations())
        rows = [row for row in rows if row.id in allowed]
    return [station_to_out(station) for station in rows]


@router.post("", response_model=StationOut, status_code=201)
def create_station_card(
    body: StationCreate,
    _admin: str = Depends(require_admin),
) -> StationOut:
    return station_to_out(
        create_station(
            code=body.code,
            name=body.name,
            address=body.address,
            lat=body.lat,
            lon=body.lon,
            is_active=body.is_active,
        )
    )


@router.patch("/{station_id}", response_model=StationOut)
def patch_station_card(
    station_id: UUID,
    body: StationUpdate,
    _admin: str = Depends(require_admin),
) -> StationOut:
    fields = body.model_fields_set
    return station_to_out(
        update_station(
            station_id,
            code=body.code if "code" in fields else None,
            name=body.name if "name" in fields else None,
            address=body.address,
            lat=body.lat if "lat" in fields else None,
            lon=body.lon if "lon" in fields else None,
            is_active=body.is_active if "is_active" in fields else None,
            address_set="address" in fields,
        )
    )


@router.delete("/{station_id}", status_code=204)
def remove_station_card(station_id: UUID, _admin: str = Depends(require_admin)) -> Response:
    delete_station(station_id)
    return Response(status_code=204)


@router.get("/{station_id}", response_model=StationDetailOut)
def get_station_card(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
) -> StationDetailOut:
    require_station_access(station_id, principal)
    station = get_station(station_id)
    tanks = list_station_tanks_out(station_id)
    remainder, capacity, delta, balance_status = summarize_station_tanks(tanks)
    return StationDetailOut(
        **station_to_out(station).model_dump(),
        tanks=tanks,
        remainder_liters=remainder,
        capacity_liters=capacity,
        balance_status=balance_status,
        calculated_vs_actual_delta=delta,
    )
