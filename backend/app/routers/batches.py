"""Batch and digital trail endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from app.schemas.batch import BatchCreate, BatchOut, BatchTrailEventOut, BatchTrailOut
from app.services.trail import trail_chain_labels

router = APIRouter(prefix="/batches", tags=["batches"])

_NOW = datetime.now(timezone.utc)

_DEMO_BATCHES: dict[UUID, dict] = {
    UUID("e1111111-1111-1111-1111-111111111101"): {
        "id": UUID("e1111111-1111-1111-1111-111111111101"),
        "trail_code": "LPG-2026-00041",
        "supplier_id": UUID("11111111-1111-1111-1111-111111111001"),
        "factory_id": UUID("f1111111-1111-1111-1111-111111111101"),
        "product_grade": "ПБА",
        "density_kg_per_liter": 0.54,
        "volume_liters": 16500,
        "mass_kg": 8910,
        "status": "in_transit",
        "formed_at": _NOW - timedelta(hours=6),
        "notes": "Рейс на АГЗС Север",
        "created_at": _NOW - timedelta(hours=6),
        "events": [
            {
                "id": uuid4(),
                "node_type": "supplier",
                "occurred_at": _NOW - timedelta(hours=8),
                "title": "Поставщик подтвердил партию",
                "description": "ООО ГазСнаб",
                "ref_entity_type": "supplier",
                "ref_entity_id": UUID("11111111-1111-1111-1111-111111111001"),
                "volume_liters": 16500,
                "lat": None,
                "lon": None,
            },
            {
                "id": uuid4(),
                "node_type": "factory",
                "occurred_at": _NOW - timedelta(hours=7),
                "title": "Отгрузка с завода",
                "description": "Завод Тольятти",
                "ref_entity_type": "factory",
                "ref_entity_id": UUID("f1111111-1111-1111-1111-111111111101"),
                "volume_liters": 16500,
                "lat": 53.5078,
                "lon": 49.4204,
            },
            {
                "id": uuid4(),
                "node_type": "batch",
                "occurred_at": _NOW - timedelta(hours=6),
                "title": "Партия сформирована",
                "description": "LPG-2026-00041",
                "ref_entity_type": "batch",
                "ref_entity_id": UUID("e1111111-1111-1111-1111-111111111101"),
                "volume_liters": 16500,
                "lat": 53.5078,
                "lon": 49.4204,
            },
            {
                "id": uuid4(),
                "node_type": "truck",
                "occurred_at": _NOW - timedelta(hours=4),
                "title": "Газовоз выехал",
                "description": "А123ВС77",
                "ref_entity_type": "truck",
                "ref_entity_id": UUID("c1111111-1111-1111-1111-111111111101"),
                "volume_liters": 16500,
                "lat": 53.5078,
                "lon": 49.4204,
            },
            {
                "id": uuid4(),
                "node_type": "route",
                "occurred_at": _NOW - timedelta(hours=2),
                "title": "В пути",
                "description": "GPS-точка маршрута",
                "ref_entity_type": "truck",
                "ref_entity_id": UUID("c1111111-1111-1111-1111-111111111101"),
                "volume_liters": 16500,
                "lat": 55.75,
                "lon": 37.45,
            },
        ],
    }
}


@router.get("", response_model=list[BatchOut])
def list_batches() -> list[BatchOut]:
    return [BatchOut(**{k: v for k, v in b.items() if k != "events"}) for b in _DEMO_BATCHES.values()]


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
    _DEMO_BATCHES[batch_id] = record
    return BatchOut(**{k: v for k, v in record.items() if k != "events"})


@router.get("/by-code/{trail_code}", response_model=BatchOut)
def get_batch_by_code(trail_code: str) -> BatchOut:
    for b in _DEMO_BATCHES.values():
        if b["trail_code"] == trail_code:
            return BatchOut(**{k: v for k, v in b.items() if k != "events"})
    raise HTTPException(status_code=404, detail="Batch not found")


@router.get("/by-code/{trail_code}/trail", response_model=BatchTrailOut)
def get_trail_by_code(trail_code: str) -> BatchTrailOut:
    for b in _DEMO_BATCHES.values():
        if b["trail_code"] == trail_code:
            return BatchTrailOut(
                batch=BatchOut(**{k: v for k, v in b.items() if k != "events"}),
                chain=trail_chain_labels(),
                events=[BatchTrailEventOut(**e) for e in b["events"]],
            )
    raise HTTPException(status_code=404, detail="Batch not found")


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: UUID) -> BatchOut:
    b = _DEMO_BATCHES.get(batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchOut(**{k: v for k, v in b.items() if k != "events"})


@router.get("/{batch_id}/trail", response_model=BatchTrailOut)
def get_batch_trail(batch_id: UUID) -> BatchTrailOut:
    b = _DEMO_BATCHES.get(batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchTrailOut(
        batch=BatchOut(**{k: v for k, v in b.items() if k != "events"}),
        chain=trail_chain_labels(),
        events=[BatchTrailEventOut(**e) for e in b["events"]],
    )
