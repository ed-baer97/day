"""Batch and digital trail endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.schemas.batch import BatchCreate, BatchOut, BatchTrailEventOut, BatchTrailOut
from app.services.batch_book import by_code, by_id, create_batch, list_batches
from app.services.trail import trail_chain_labels

router = APIRouter(prefix="/batches", tags=["batches"])


def _missing() -> HTTPException:
    return HTTPException(status_code=404, detail="Batch not found")


@router.get("", response_model=list[BatchOut])
def list_batch_cards() -> list[BatchOut]:
    return [BatchOut(**row) for row in list_batches()]


@router.post("", response_model=BatchOut, status_code=201)
def create_batch_card(body: BatchCreate) -> BatchOut:
    return BatchOut(**create_batch(**body.model_dump()))


@router.get("/by-code/{trail_code}", response_model=BatchOut)
def get_batch_by_code(trail_code: str) -> BatchOut:
    row = by_code(trail_code)
    if row is None:
        raise _missing()
    return BatchOut(**{key: value for key, value in row.items() if key != "events"})


@router.get("/by-code/{trail_code}/trail", response_model=BatchTrailOut)
def get_trail_by_code(trail_code: str) -> BatchTrailOut:
    row = by_code(trail_code)
    if row is None:
        raise _missing()
    return _trail(row)


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: UUID) -> BatchOut:
    row = by_id(batch_id)
    if row is None:
        raise _missing()
    return BatchOut(**{key: value for key, value in row.items() if key != "events"})


@router.get("/{batch_id}/trail", response_model=BatchTrailOut)
def get_batch_trail(batch_id: UUID) -> BatchTrailOut:
    row = by_id(batch_id)
    if row is None:
        raise _missing()
    return _trail(row)


def _trail(row: dict) -> BatchTrailOut:
    return BatchTrailOut(
        batch=BatchOut(**{key: value for key, value in row.items() if key != "events"}),
        chain=trail_chain_labels(),
        events=[BatchTrailEventOut(**event) for event in row["events"]],
    )
