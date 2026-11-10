"""Роутер привязки сетевых датчиков уровня Shelly к резервуарам АГЗС."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.routers.tanks import device_to_out
from app.schemas.station import ShellyBind, TankDeviceOut
from app.services.catalog import get_station
from app.services.device_ingest import get_tank_device
from app.services.shelly_link import connect_shelly, disconnect_shelly

router = APIRouter(prefix="/stations/{station_id}/devices/{tank_id}/shelly", tags=["shelly"])


@router.put("", response_model=TankDeviceOut)
def put_station_shelly(
    station_id: UUID,
    tank_id: UUID,
    body: ShellyBind,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    connect_shelly(station_id, tank_id, body.host)
    return device_to_out(get_tank_device(station_id, tank_id))


@router.delete("", response_model=TankDeviceOut)
def delete_station_shelly(
    station_id: UUID,
    tank_id: UUID,
    _admin: str = Depends(require_admin),
) -> TankDeviceOut:
    get_station(station_id)
    disconnect_shelly(station_id, tank_id)
    return device_to_out(get_tank_device(station_id, tank_id))
