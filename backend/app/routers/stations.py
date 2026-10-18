"""Station endpoints."""

from uuid import UUID

from fastapi import APIRouter

from app.schemas.station import (
    StationCreate,
    StationDetailOut,
    StationOut,
    StationUpdate,
    ShellyBind,
    TankDeviceCreate,
    TankDeviceOut,
    TankDeviceUpdate,
    TankOut,
)
from app.services.catalog import StationCard, create_station, get_station, list_stations, update_station
from app.services.device_ingest import (
    TankDevice,
    get_tank_device,
    list_tank_devices,
    register_tank,
    update_tank_device,
)
from app.services.shelly_link import connect_shelly, disconnect_shelly, shelly_view

router = APIRouter(prefix="/stations", tags=["stations"])

# Живая заправка с датчиком. Остальные точки карты — симуляция на фронте.
_DEMO_STATIONS: list[dict] = [
    {
        "id": UUID("a1111111-1111-1111-1111-111111111101"),
        "code": "AGZS-AKT-12",
        "name": "АГЗС Актау · 12 мкр",
        "address": "Актау, 12 микрорайон",
        "lat": 43.6479,
        "lon": 51.2480,
        "is_active": True,
        "tanks": [],
    },
]


def _station_out(station: StationCard) -> StationOut:
    return StationOut(
        id=station.id,
        code=station.code,
        name=station.name,
        address=station.address,
        lat=station.lat,
        lon=station.lon,
        is_active=station.is_active,
    )


@router.get("", response_model=list[StationOut])
def list_station_cards() -> list[StationOut]:
    return [_station_out(station) for station in list_stations()]


@router.post("", response_model=StationOut, status_code=201)
def create_station_card(body: StationCreate) -> StationOut:
    return _station_out(
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
def patch_station_card(station_id: UUID, body: StationUpdate) -> StationOut:
    fields = body.model_fields_set
    return _station_out(
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


@router.get("/{station_id}", response_model=StationDetailOut)
def get_station_card(station_id: UUID) -> StationDetailOut:
    station = get_station(station_id)
    demo = next((item for item in _DEMO_STATIONS if item["id"] == station_id), None)
    tanks = [TankOut(**tank) for tank in (demo["tanks"] if demo else [])]
    if demo is None or not tanks:
        return StationDetailOut(
            **_station_out(station).model_dump(),
            tanks=tanks,
            remainder_liters=0,
            capacity_liters=0,
            balance_status="unknown",
            calculated_vs_actual_delta=0,
        )
    capacity = sum(tank.capacity_liters for tank in tanks) or 15000
    actual = sum(tank.actual_remainder_liters or 0 for tank in tanks) or 5000
    calculated = sum(tank.calculated_remainder_liters or 0 for tank in tanks) or actual
    delta = actual - calculated
    status = "ok" if abs(delta) < 50 else ("shortage" if delta < 0 else "surplus")
    return StationDetailOut(
        **_station_out(station).model_dump(),
        tanks=tanks,
        remainder_liters=actual,
        capacity_liters=capacity,
        receipts_day_liters=8200,
        consumption_day_liters=3100,
        consumption_week_liters=21400,
        consumption_month_liters=86500,
        sales_day_count=142,
        active_trucks=[{"plate": "705 ABA 12", "status": "arrived"}],
        balance_status=status,
        calculated_vs_actual_delta=delta,
    )


@router.get("/{station_id}/tanks", response_model=list[TankOut])
def list_tanks(station_id: UUID) -> list[TankOut]:
    get_station(station_id)
    for station in _DEMO_STATIONS:
        if station["id"] == station_id:
            return [TankOut(**tank) for tank in station["tanks"]]
    return []


def _require_demo_station(station_id: UUID) -> None:
    get_station(station_id)


def _device_out(device: TankDevice) -> TankDeviceOut:
    return TankDeviceOut(
        id=device.tank_id,
        station_id=device.station_id,
        code=device.code,
        capacity_liters=device.capacity_liters,
        ingest_token=device.token,
        shelly=shelly_view(device.tank_id),
    )


@router.get("/{station_id}/devices", response_model=list[TankDeviceOut])
def list_station_devices(station_id: UUID) -> list[TankDeviceOut]:
    _require_demo_station(station_id)
    return [_device_out(device) for device in list_tank_devices(station_id)]


@router.post("/{station_id}/devices", response_model=TankDeviceOut, status_code=201)
def create_station_device(station_id: UUID, body: TankDeviceCreate) -> TankDeviceOut:
    _require_demo_station(station_id)
    return _device_out(register_tank(station_id, body.code, body.capacity_liters))


@router.put("/{station_id}/devices/{tank_id}/shelly", response_model=TankDeviceOut)
def put_station_shelly(station_id: UUID, tank_id: UUID, body: ShellyBind) -> TankDeviceOut:
    _require_demo_station(station_id)
    connect_shelly(station_id, tank_id, body.host)
    return _device_out(get_tank_device(station_id, tank_id))


@router.delete("/{station_id}/devices/{tank_id}/shelly", response_model=TankDeviceOut)
def delete_station_shelly(station_id: UUID, tank_id: UUID) -> TankDeviceOut:
    _require_demo_station(station_id)
    disconnect_shelly(station_id, tank_id)
    return _device_out(get_tank_device(station_id, tank_id))


@router.patch("/{station_id}/devices/{tank_id}", response_model=TankDeviceOut)
def patch_station_device(station_id: UUID, tank_id: UUID, body: TankDeviceUpdate) -> TankDeviceOut:
    _require_demo_station(station_id)
    return _device_out(
        update_tank_device(
            station_id,
            tank_id,
            code=body.code,
            capacity_liters=body.capacity_liters,
        )
    )
