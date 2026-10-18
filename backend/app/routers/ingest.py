"""Ingest endpoints for AGZS gateway and truck telematics.

Shelly → POST /level (литры или вольты).
Топаз-119-28М → POST /dispense, только чтение, без команд на колонку.
Если задан INGEST_TOKEN, оба запроса несут заголовок X-Device-Token.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import get_settings
from app.schemas.ingest import (
    CalibrationIn,
    DispenseIngest,
    GpsIngest,
    IngestAck,
    LevelIngest,
    ReceiptIngest,
    TankIngestState,
)
from app.services.device_ingest import (
    accept_dispense,
    accept_level,
    accept_receipt,
    bind_calibration,
    bind_level,
    set_calibration,
    tank_by_token,
    tank_state,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

_SEEN_GPS: set[str] = set()


def require_device(x_device_token: str | None = Header(default=None)) -> str | None:
    if tank_by_token(x_device_token) is not None:
        return x_device_token
    expected = get_settings().ingest_token
    if not expected:
        return x_device_token
    if x_device_token != expected:
        raise HTTPException(status_code=401, detail="неверный токен устройства")
    return x_device_token


@router.post("/gps", response_model=IngestAck)
def ingest_gps(body: GpsIngest) -> IngestAck:
    key = body.source_event_id or f"gps:{body.truck_id}:{body.recorded_at.isoformat()}"
    if key in _SEEN_GPS:
        return IngestAck(accepted=True, message="duplicate", duplicate=True)
    _SEEN_GPS.add(key)
    return IngestAck(accepted=True, message="gps accepted", entity_id=uuid4())


@router.put("/calibration", response_model=TankIngestState)
def calibrate(body: CalibrationIn, token: str | None = Depends(require_device)) -> TankIngestState:
    return set_calibration(bind_calibration(body, token))


@router.post("/level", response_model=IngestAck)
def ingest_level(body: LevelIngest, token: str | None = Depends(require_device)) -> IngestAck:
    return accept_level(bind_level(body, token))


@router.post("/dispense", response_model=IngestAck)
def ingest_dispense(body: DispenseIngest, _: None = Depends(require_device)) -> IngestAck:
    """Accept read-only dispense readings from Topaz/ASKA — no control path."""
    return accept_dispense(body)


@router.post("/receipt", response_model=IngestAck)
def ingest_receipt(body: ReceiptIngest, _: None = Depends(require_device)) -> IngestAck:
    return accept_receipt(body)


@router.get("/tanks/{tank_id}", response_model=TankIngestState)
def ingest_tank(tank_id: UUID, _: None = Depends(require_device)) -> TankIngestState:
    return tank_state(tank_id)
