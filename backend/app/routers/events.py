"""Discrepancy event endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.schemas.event import DiscrepancyEventOut, DiscrepancyResolveRequest
from app.services.event_log import get_event, list_events, resolve_event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[DiscrepancyEventOut])
def list_event_cards(
    station_id: UUID | None = None,
    unresolved_only: bool = False,
) -> list[DiscrepancyEventOut]:
    return [DiscrepancyEventOut(**row) for row in list_events(station_id, unresolved_only)]


@router.get("/{event_id}", response_model=DiscrepancyEventOut)
def get_event_card(event_id: UUID) -> DiscrepancyEventOut:
    row = get_event(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return DiscrepancyEventOut(**row)


@router.post("/{event_id}/resolve", response_model=DiscrepancyEventOut)
def resolve_event_card(event_id: UUID, body: DiscrepancyResolveRequest) -> DiscrepancyEventOut:
    row = resolve_event(event_id, body.note)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return DiscrepancyEventOut(**row)
