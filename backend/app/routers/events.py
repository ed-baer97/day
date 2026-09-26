"""Discrepancy event endpoints."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from app.routers.balance import get_generated_events
from app.schemas.event import DiscrepancyEventOut, DiscrepancyResolveRequest

router = APIRouter(prefix="/events", tags=["events"])

_SEED: list[dict] = [
    {
        "id": UUID("91111111-1111-1111-1111-111111111101"),
        "station_id": UUID("a1111111-1111-1111-1111-111111111101"),
        "tank_id": UUID("b1111111-1111-1111-1111-111111111101"),
        "balance_snapshot_id": None,
        "event_type": "shortage",
        "severity": "warning",
        "delta_liters": -150.0,
        "title": "Недостача",
        "description": "Факт ниже расчёта на 150 л",
        "is_resolved": False,
        "detected_at": datetime.now(timezone.utc),
        "resolved_at": None,
    }
]


def _all_events() -> list[dict]:
    return _SEED + get_generated_events()


@router.get("", response_model=list[DiscrepancyEventOut])
def list_events(station_id: UUID | None = None, unresolved_only: bool = False) -> list[DiscrepancyEventOut]:
    items = _all_events()
    if station_id is not None:
        items = [e for e in items if e["station_id"] == station_id]
    if unresolved_only:
        items = [e for e in items if not e["is_resolved"]]
    return [DiscrepancyEventOut(**e) for e in items]


@router.get("/{event_id}", response_model=DiscrepancyEventOut)
def get_event(event_id: UUID) -> DiscrepancyEventOut:
    for e in _all_events():
        if e["id"] == event_id:
            return DiscrepancyEventOut(**e)
    raise HTTPException(status_code=404, detail="Event not found")


@router.post("/{event_id}/resolve", response_model=DiscrepancyEventOut)
def resolve_event(event_id: UUID, body: DiscrepancyResolveRequest) -> DiscrepancyEventOut:
    for e in _all_events():
        if e["id"] == event_id:
            e["is_resolved"] = True
            e["resolved_at"] = datetime.now(timezone.utc)
            if body.note:
                e["description"] = (e.get("description") or "") + f" | resolved: {body.note}"
            return DiscrepancyEventOut(**e)
    raise HTTPException(status_code=404, detail="Event not found")
