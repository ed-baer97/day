"""Batch and digital trail endpoints."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from app.schemas.batch import BatchCreate, BatchOut, BatchTrailEventOut, BatchTrailOut
from app.services.trail import trail_chain_labels

router = APIRouter(prefix="/batches", tags=["batches"])

_BATCHES: dict[UUID, dict] = {}


@router.get("", response_model=list[BatchOut])
def list_batches() -> list[BatchOut]:
    return [BatchOut(**{k: v for k, v in b.items() if k != "events"}) for b in _BATCHES.values()]


@router.post("", response_model=BatchOut, status_code=201)
def create_batch(body: BatchCreate) -> BatchOut:
    batch_id = uuid4()
    now = datetime.now(timezone.utc)
    record = {
        "id": batch_id,
        "trail_code": body.trail_code,
        "supplier_id": body.supplier_id,
        "factory_id": body.factory_id,
        "product_grade": body.product_grade,
        "density_kg_per_liter": body.density_kg_per_liter,
        "volume_liters": body.volume_liters,
        "mass_kg": body.mass_kg,
        "status": "formed",
        "formed_at": now,
        "notes": body.notes,
        "created_at": now,
        "events": [],
    }
    _BATCHES[batch_id] = record
    return BatchOut(**{k: v for k, v in record.items() if k != "events"})


@router.get("/by-code/{trail_code}", response_model=BatchOut)
def get_batch_by_code(trail_code: str) -> BatchOut:
    for b in _BATCHES.values():
        if b["trail_code"] == trail_code:
            return BatchOut(**{k: v for k, v in b.items() if k != "events"})
    raise HTTPException(status_code=404, detail="Batch not found")


@router.get("/by-code/{trail_code}/trail", response_model=BatchTrailOut)
def get_trail_by_code(trail_code: str) -> BatchTrailOut:
    for b in _BATCHES.values():
        if b["trail_code"] == trail_code:
            return BatchTrailOut(
                batch=BatchOut(**{k: v for k, v in b.items() if k != "events"}),
                chain=trail_chain_labels(),
                events=[BatchTrailEventOut(**e) for e in b["events"]],
            )
    raise HTTPException(status_code=404, detail="Batch not found")


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: UUID) -> BatchOut:
    b = _BATCHES.get(batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchOut(**{k: v for k, v in b.items() if k != "events"})


@router.get("/{batch_id}/trail", response_model=BatchTrailOut)
def get_batch_trail(batch_id: UUID) -> BatchTrailOut:
    b = _BATCHES.get(batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchTrailOut(
        batch=BatchOut(**{k: v for k, v in b.items() if k != "events"}),
        chain=trail_chain_labels(),
        events=[BatchTrailEventOut(**e) for e in b["events"]],
    )
