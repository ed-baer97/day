"""Проверка области действия токена и привязка телеметрии к резервуару/АГЗС.

Отделено от записи в книгу резервуара и не импортирует FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.domain.entities import TankDevice
from app.domain.errors import ForbiddenError, NotFoundError
from app.schemas.ingest import DispenseIngest, LevelIngest
from app.services.account import get_station, tank_by_token
from app.services.account_helpers import require_station_and_tank

CallerKind = Literal["tank_device", "admin", "shared_ingest", "gps_device", "anonymous"]


@dataclass(frozen=True)
class IngestCaller:
    """Аутентифицированный источник запроса в /api/v1/ingest/*."""

    kind: CallerKind
    device: TankDevice | None = None
    station_code: str | None = None


def resolve_tank_device_caller(token: str) -> IngestCaller | None:
    """Находит карточку резервуара и код АГЗС по X-Device-Token."""
    device = tank_by_token(token)
    if device is None:
        return None
    station_code: str | None = None
    try:
        station_code = get_station(device.station_id).code
    except NotFoundError:
        station_code = None
    return IngestCaller(kind="tank_device", device=device, station_code=station_code)


def _assert_device_scope(
    device: TankDevice,
    station_id: UUID | None,
    tank_id: UUID | None,
) -> None:
    if station_id is not None and station_id != device.station_id:
        raise ForbiddenError("токен принадлежит другой заправке")
    if tank_id is not None and tank_id != device.tank_id:
        raise ForbiddenError("токен принадлежит другому резервуару")


def bind_level_for_caller(body: LevelIngest, caller: IngestCaller) -> LevelIngest:
    """Жёстко привязывает замер уровня к карточке токена или проверяет station_id/tank_id."""
    if caller.kind == "tank_device":
        if caller.device is None:
            raise ForbiddenError("токен не привязан к резервуару")
        _assert_device_scope(caller.device, body.station_id, body.tank_id)
        return body.model_copy(
            update={"station_id": caller.device.station_id, "tank_id": caller.device.tank_id}
        )
    require_station_and_tank(body.station_id, body.tank_id)
    return body


def bind_dispense_for_caller(body: DispenseIngest, caller: IngestCaller) -> DispenseIngest:
    """Жёстко привязывает налив ТРК к резервуару и АГЗС токена."""
    if caller.kind == "tank_device":
        if caller.device is None:
            raise ForbiddenError("токен не привязан к резервуару")
        _assert_device_scope(caller.device, body.station_id, body.tank_id)
        return body.model_copy(
            update={"station_id": caller.device.station_id, "tank_id": caller.device.tank_id}
        )
    return body


def assert_tank_read_access(tank_id: UUID, caller: IngestCaller) -> None:
    """Токен резервуара может читать состояние только своего резервуара."""
    if caller.kind == "tank_device":
        if caller.device is None or caller.device.tank_id != tank_id:
            raise ForbiddenError("токен принадлежит другому резервуару")


def resolve_edge_station_scope(
    caller: IngestCaller,
    requested_station_code: str | None,
    requested_station_id: UUID | None = None,
) -> tuple[str | None, UUID | None]:
    """Привязывает heartbeat и запрос релиза к АГЗС токена и запрещает подмену чужого кода."""
    if caller.kind == "tank_device":
        if caller.device is None or not caller.station_code:
            raise ForbiddenError("токен не привязан к действующей заправке")
        cleaned_code = requested_station_code.strip() if requested_station_code else ""
        if cleaned_code and cleaned_code.lower() != caller.station_code.lower():
            raise ForbiddenError("токен принадлежит другой заправке")
        if requested_station_id is not None and requested_station_id != caller.device.station_id:
            raise ForbiddenError("токен принадлежит другой заправке")
        return caller.station_code, caller.device.station_id
    return (requested_station_code.strip() if requested_station_code else None), requested_station_id


__all__ = [
    "CallerKind",
    "IngestCaller",
    "assert_tank_read_access",
    "bind_dispense_for_caller",
    "bind_level_for_caller",
    "resolve_edge_station_scope",
    "resolve_tank_device_caller",
]
