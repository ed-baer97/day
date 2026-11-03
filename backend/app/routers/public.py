"""Открытый список заполненности. Для сайта, без учёта."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import get_settings
from app.schemas.public import PublicStationOut, PublicTankOut
from app.services.catalog import list_stations
from app.services.device_ingest import list_tank_devices, tank_remainder

router = APIRouter(prefix="/public", tags=["public"])


def _percent(remainder: float | None, capacity: float) -> float | None:
    if remainder is None or capacity <= 0:
        return None
    return float(round(remainder / capacity * 100))


def _online(measured_at: datetime | None) -> bool:
    if measured_at is None:
        return False
    stamp = measured_at if measured_at.tzinfo is not None else measured_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    return age <= get_settings().sensor_stale_seconds


@router.get("/levels", response_model=list[PublicStationOut])
def public_levels() -> list[PublicStationOut]:
    rows: list[PublicStationOut] = []
    for station in list_stations():
        if not station.is_active:
            continue
        tanks: list[PublicTankOut] = []
        for device in list_tank_devices(station.id):
            remainder, measured_at = tank_remainder(device.tank_id)
            tanks.append(
                PublicTankOut(
                    code=device.code,
                    capacity_liters=device.capacity_liters,
                    remainder_liters=remainder,
                    fill_percent=_percent(remainder, device.capacity_liters),
                    measured_at=measured_at,
                    online=_online(measured_at),
                )
            )
        rows.append(
            PublicStationOut(
                code=station.code,
                name=station.name,
                address=station.address,
                lat=station.lat,
                lon=station.lon,
                tanks=tanks,
            )
        )
    return rows
