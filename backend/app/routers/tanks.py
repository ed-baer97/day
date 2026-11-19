"""Роутер резервуаров, токенов телеметрии и журнала уровней АГЗС."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.auth import Principal, require_admin, require_principal
from app.routers.deps import device_to_out, require_existing_station_access
from app.schemas.station import (
    DispenseReadingOut,
    LevelReadingOut,
    TankDeviceCreate,
    TankDeviceOut,
    TankDeviceUpdate,
    TankOut,
)
from app.services.account import (
    delete_tank_device,
    get_station,
    get_tank_device,
    list_dispense_records,
    list_level_readings,
    list_station_tanks_out,
    list_tank_devices,
    register_tank,
    rotate_tank_token,
    update_tank_device,
)
from app.services.level_journal import published_levels

router = APIRouter(prefix="/stations/{station_id}", tags=["tanks"])


@router.get("/tanks", response_model=list[TankOut])
def list_tanks(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
) -> list[TankOut]:
    require_existing_station_access(station_id, principal)
    return list_station_tanks_out(station_id)


@router.get("/devices", response_model=list[TankDeviceOut])
def list_station_devices(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
) -> list[TankDeviceOut]:
    require_existing_station_access(station_id, principal)
    return [device_to_out(device) for device in list_tank_devices(station_id)]


@router.post("/devices", response_model=TankDeviceOut, status_code=201)
def create_station_device(
    station_id: UUID,
    body: TankDeviceCreate,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    return device_to_out(register_tank(station_id, body.code, body.capacity_liters))


@router.patch("/devices/{tank_id}", response_model=TankDeviceOut)
def patch_station_device(
    station_id: UUID,
    tank_id: UUID,
    body: TankDeviceUpdate,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    return device_to_out(
        update_tank_device(
            station_id,
            tank_id,
            code=body.code,
            capacity_liters=body.capacity_liters,
        )
    )


@router.delete("/devices/{tank_id}", status_code=204)
def remove_station_device(
    station_id: UUID,
    tank_id: UUID,
    _admin: str = Depends(require_admin),
) -> Response:
    get_station(station_id)
    delete_tank_device(station_id, tank_id)
    return Response(status_code=204)


@router.post("/devices/{tank_id}/rotate-token", response_model=TankDeviceOut)
def rotate_station_device_token(
    station_id: UUID,
    tank_id: UUID,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    return device_to_out(rotate_tank_token(station_id, tank_id))


@router.get("/devices/{tank_id}/levels", response_model=list[LevelReadingOut])
def list_device_levels(
    station_id: UUID,
    tank_id: UUID,
    principal: Principal = Depends(require_principal),
    since: datetime | None = None,
    changes_only: bool = True,
    limit: int = 2000,
) -> list[LevelReadingOut]:
    """Журнал замеров уровня. По умолчанию только смены остатка (без шума датчика)."""
    require_existing_station_access(station_id, principal)
    get_tank_device(station_id, tank_id)
    capped = max(1, min(limit, 5000))
    rows = list_level_readings(
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


@router.get("/dispenses", response_model=list[DispenseReadingOut])
def list_station_dispenses(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
    since: datetime | None = None,
    limit: int = 500,
) -> list[DispenseReadingOut]:
    """Журнал завершённых наливов ТРК (УЗГС-01 / АСКА-02) по станции."""
    require_existing_station_access(station_id, principal)
    capped = max(1, min(limit, 5000))
    return list_dispense_records(station_id, since=since, limit=capped)
