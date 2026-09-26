"""Discrepancy event schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DiscrepancyEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    station_id: UUID
    tank_id: UUID | None
    balance_snapshot_id: UUID | None
    event_type: str
    severity: str
    delta_liters: float | None
    title: str
    description: str | None
    is_resolved: bool
    detected_at: datetime
    resolved_at: datetime | None


class DiscrepancyResolveRequest(BaseModel):
    note: str | None = None
