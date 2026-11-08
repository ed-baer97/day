"""Station endpoints."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth import Principal, require_admin, require_principal, require_station_access
from app.config import get_settings
from app.schemas.auth import LevelReadingOut, StationUserCreate, StationUserCreated
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
from app.services.account_mode import use_postgres
from app.services.catalog import (
    StationCard,
    create_station,
    delete_station,
    get_station,
    list_stations,
    update_station,
)
from app.services.device_ingest import (
    TankDevice,
    delete_tank_device,
    get_tank_device,
    list_tank_devices,
    register_tank,
    tank_remainder,
    update_tank_device,
)
from app.services.level_journal import published_levels
from app.services.shelly_link import connect_shelly, disconnect_shelly, shelly_view

router = APIRouter(prefix="/stations", tags=["stations"])


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


def _device_out(device: TankDevice) -> TankDeviceOut:
    settings = get_settings()
    return TankDeviceOut(
        id=device.tank_id,
        station_id=device.station_id,
        code=device.code,
        capacity_liters=device.capacity_liters,
        ingest_token=device.token,
        level_path=settings.ingest_level_path,
        ingest_url=settings.ingest_level_url,
        shelly=shelly_view(device.tank_id),
    )


def _station_tanks_out(station_id: UUID) -> list[TankOut]:
    tanks: list[TankOut] = []
    for device in list_tank_devices(station_id):
        remainder, measured = tank_remainder(device.tank_id)
        tanks.append(
            TankOut(
                id=device.tank_id,
                code=device.code,
                capacity_liters=device.capacity_liters,
                has_electronic_sensor=True,
                actual_remainder_liters=remainder,
                calculated_remainder_liters=remainder,
                level_source="electronic",
                last_measured_at=measured,
            )
        )
    return tanks


@router.get("", response_model=list[StationOut])
def list_station_cards(principal: Principal = Depends(require_principal)) -> list[StationOut]:
    rows = list_stations()
    if not principal.is_admin:
        rows = [row for row in rows if row.id == principal.station_id]
    return [_station_out(station) for station in rows]


@router.post("", response_model=StationOut, status_code=201)
def create_station_card(
    body: StationCreate,
    _admin: str = Depends(require_admin),
) -> StationOut:
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
def patch_station_card(
    station_id: UUID,
    body: StationUpdate,
    _admin: str = Depends(require_admin),
) -> StationOut:
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
    tanks = _station_tanks_out(station_id)
    return StationDetailOut(
        **_station_out(station).model_dump(),
        tanks=tanks,
        remainder_liters=sum(t.actual_remainder_liters or 0 for t in tanks) if tanks else None,
        capacity_liters=sum(t.capacity_liters for t in tanks) if tanks else None,
        balance_status="unknown",
        calculated_vs_actual_delta=None,
    )


@router.get("/{station_id}/tanks", response_model=list[TankOut])
def list_tanks(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
) -> list[TankOut]:
    _require_station(station_id, principal)
    return _station_tanks_out(station_id)


def _require_station(station_id: UUID, principal: Principal) -> None:
    get_station(station_id)
    require_station_access(station_id, principal)


@router.get("/{station_id}/devices", response_model=list[TankDeviceOut])
def list_station_devices(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
) -> list[TankDeviceOut]:
    _require_station(station_id, principal)
    return [_device_out(device) for device in list_tank_devices(station_id)]


@router.post("/{station_id}/devices", response_model=TankDeviceOut, status_code=201)
def create_station_device(
    station_id: UUID,
    body: TankDeviceCreate,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    return _device_out(register_tank(station_id, body.code, body.capacity_liters))


@router.put("/{station_id}/devices/{tank_id}/shelly", response_model=TankDeviceOut)
def put_station_shelly(
    station_id: UUID,
    tank_id: UUID,
    body: ShellyBind,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    connect_shelly(station_id, tank_id, body.host)
    return _device_out(get_tank_device(station_id, tank_id))


@router.delete("/{station_id}/devices/{tank_id}/shelly", response_model=TankDeviceOut)
def delete_station_shelly(
    station_id: UUID,
    tank_id: UUID,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    disconnect_shelly(station_id, tank_id)
    return _device_out(get_tank_device(station_id, tank_id))


@router.patch("/{station_id}/devices/{tank_id}", response_model=TankDeviceOut)
def patch_station_device(
    station_id: UUID,
    tank_id: UUID,
    body: TankDeviceUpdate,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    return _device_out(
        update_tank_device(
            station_id,
            tank_id,
            code=body.code,
            capacity_liters=body.capacity_liters,
        )
    )


@router.delete("/{station_id}/devices/{tank_id}", status_code=204)
def remove_station_device(
    station_id: UUID,
    tank_id: UUID,
    _admin: str = Depends(require_admin),
) -> Response:
    get_station(station_id)
    delete_tank_device(station_id, tank_id)
    return Response(status_code=204)


@router.get("/{station_id}/devices/{tank_id}/levels", response_model=list[LevelReadingOut])
def list_device_levels(
    station_id: UUID,
    tank_id: UUID,
    principal: Principal = Depends(require_principal),
    since: datetime | None = None,
    changes_only: bool = True,
    limit: int = 2000,
) -> list[LevelReadingOut]:
    """Журнал замеров. По умолчанию только смены остатка (не каждый пакет Shelly)."""

    _require_station(station_id, principal)
    get_tank_device(station_id, tank_id)
    if not use_postgres():
        return []
    from app.services import postgres_account

    capped = max(1, min(limit, 5000))
    rows = postgres_account.list_level_readings(
        station_id,
        tank_id,
        since=since,
        limit=capped,
        newest_first=False,
    )
    return [
        LevelReadingOut(
            id=row.id,
            tank_id=row.tank_id,
            volts=row.volts,
            remainder_liters=row.remainder_liters,
            fill_percent=row.fill_percent,
            recorded_at=row.recorded_at.isoformat(),
            delta_liters=row.delta_liters,
        )
        for row in published_levels(rows, changes_only=changes_only)
    ]


@router.post("/{station_id}/users", response_model=StationUserCreated, status_code=201)
def create_station_login(
    station_id: UUID,
    body: StationUserCreate,
    _admin: str = Depends(require_admin),
) -> StationUserCreated:
    get_station(station_id)
    if not use_postgres():
        from fastapi import HTTPException

        raise HTTPException(status_code=501, detail="вход станции доступен при ACCOUNT_STORE=postgres")
    from app.services import postgres_account

    user = postgres_account.create_station_user(station_id, body.username, body.password)
    return StationUserCreated(
        id=user.id,
        station_id=user.station_id,
        username=user.username,
        password=body.password,
    )
