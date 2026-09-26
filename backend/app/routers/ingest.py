"""Ingest endpoints for AGZS gateway and truck telematics."""

from uuid import uuid4

from fastapi import APIRouter

from app.schemas.ingest import DispenseIngest, GpsIngest, IngestAck, LevelIngest

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Idempotency registry (stub — replace with DB unique constraint in MVP-1)
_SEEN_KEYS: set[str] = set()


@router.post("/gps", response_model=IngestAck)
def ingest_gps(body: GpsIngest) -> IngestAck:
    key = body.source_event_id or f"gps:{body.truck_id}:{body.recorded_at.isoformat()}"
    if key in _SEEN_KEYS:
        return IngestAck(accepted=True, message="duplicate", duplicate=True)
    _SEEN_KEYS.add(key)
    return IngestAck(accepted=True, message="gps accepted", entity_id=uuid4())


@router.post("/level", response_model=IngestAck)
def ingest_level(body: LevelIngest) -> IngestAck:
    key = body.source_event_id or f"level:{body.tank_id}:{body.recorded_at.isoformat()}"
    if key in _SEEN_KEYS:
        return IngestAck(accepted=True, message="duplicate", duplicate=True)
    _SEEN_KEYS.add(key)
    return IngestAck(accepted=True, message="level accepted", entity_id=uuid4())


@router.post("/dispense", response_model=IngestAck)
def ingest_dispense(body: DispenseIngest) -> IngestAck:
    """Accept read-only dispense readings from Topaz/ASKA — no control path."""
    key = body.external_txn_id or f"dispense:{body.dispenser_id}:{body.started_at.isoformat()}"
    if key in _SEEN_KEYS:
        return IngestAck(accepted=True, message="duplicate", duplicate=True)
    _SEEN_KEYS.add(key)
    return IngestAck(accepted=True, message="dispense accepted", entity_id=uuid4())
