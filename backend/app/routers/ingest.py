"""Ingest endpoints for AGZS gateway and truck telematics.

Shelly → POST /level (литры или вольты).
Топаз-119-28М → POST /dispense, только чтение, без команд на колонку.
Если задан INGEST_TOKEN, запросы несут заголовок X-Device-Token (или сессию администратора).
"""

import hmac
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException

from app.auth import is_admin_authorization
from app.config import get_settings
from app.schemas.ingest import (
    CalibrationIn,
    DispenseBatchAck,
    DispenseBatchIngest,
    DispenseIngest,
    GpsIngest,
    IngestAck,
    LevelBatchAck,
    LevelBatchIngest,
    LevelIngest,
    ReceiptIngest,
    TankIngestState,
)
from app.services.device_ingest import (
    accept_dispense,
    accept_dispenses_batch,
    accept_level,
    accept_levels_batch,
    accept_receipt,
    bind_calibration,
    bind_dispense,
    bind_level,
    bind_receipt,
    set_calibration,
    tank_by_token,
    tank_state,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

_SEEN_GPS: set[str] = set()
_MAX_SEEN_GPS = 10_000


def require_device(
    x_device_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    if tank_by_token(x_device_token) is not None:
        return x_device_token
    # Сессия администратора. Флаг тестов сам по себе приём не открывает.
    if authorization and is_admin_authorization(authorization):
        return x_device_token
    expected = get_settings().ingest_token
    if not expected:
        return x_device_token
    if not x_device_token or not hmac.compare_digest(x_device_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="неверный токен устройства")
    return x_device_token


@router.post("/gps", response_model=IngestAck)
def ingest_gps(body: GpsIngest, _: str | None = Depends(require_device)) -> IngestAck:
    key = body.source_event_id or f"gps:{body.truck_id}:{body.recorded_at.isoformat()}"
    if key in _SEEN_GPS:
        return IngestAck(accepted=True, message="duplicate", duplicate=True)
    if len(_SEEN_GPS) >= _MAX_SEEN_GPS:
        _SEEN_GPS.clear()
    _SEEN_GPS.add(key)
    return IngestAck(accepted=True, message="gps accepted", entity_id=uuid4())


@router.put("/calibration", response_model=TankIngestState)
def calibrate(body: CalibrationIn, token: str | None = Depends(require_device)) -> TankIngestState:
    return set_calibration(bind_calibration(body, token))


@router.post("/level", response_model=IngestAck)
def ingest_level(body: LevelIngest, token: str | None = Depends(require_device)) -> IngestAck:
    return accept_level(bind_level(body, token))


@router.post("/levels/batch", response_model=LevelBatchAck)
def ingest_levels_batch(
    body: LevelBatchIngest, token: str | None = Depends(require_device)
) -> LevelBatchAck:
    """Пакетный приём замеров уровня при восстановлении связи со станцией."""
    bound_items = [bind_level(item, token) for item in body.items]
    return accept_levels_batch(bound_items)


@router.post("/dispense", response_model=IngestAck)
def ingest_dispense(body: DispenseIngest, token: str | None = Depends(require_device)) -> IngestAck:
    """Accept read-only dispense readings from Topaz/ASKA — no control path."""
    return accept_dispense(bind_dispense(body, token))


@router.post("/dispenses/batch", response_model=DispenseBatchAck)
def ingest_dispenses_batch(
    body: DispenseBatchIngest, token: str | None = Depends(require_device)
) -> DispenseBatchAck:
    """Пакетный приём наливов ТРК из очереди outbox edge-компьютера."""
    bound_items = [bind_dispense(item, token) for item in body.items]
    return accept_dispenses_batch(bound_items)


@router.post("/receipt", response_model=IngestAck)
def ingest_receipt(body: ReceiptIngest, token: str | None = Depends(require_device)) -> IngestAck:
    return accept_receipt(bind_receipt(body, token))


@router.get("/tanks/{tank_id}", response_model=TankIngestState)
def ingest_tank(
    tank_id: UUID,
    token: str | None = Depends(require_device),
    authorization: Annotated[str | None, Header()] = None,
) -> TankIngestState:
    device = tank_by_token(token)
    if device is not None and device.tank_id != tank_id:
        raise HTTPException(status_code=403, detail="токен принадлежит другому резервуару")
    settings = get_settings()
    if (
        device is None
        and not settings.ingest_token
        and not is_admin_authorization(authorization)
    ):
        raise HTTPException(status_code=401, detail="Нужен вход или токен резервуара")
    return tank_state(tank_id)
