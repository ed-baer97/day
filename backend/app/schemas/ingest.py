"""Ingest payloads from AGZS gateway / truck telematics."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GpsIngest(BaseModel):
    truck_id: UUID
    lat: float
    lon: float
    speed_kmh: float | None = None
    recorded_at: datetime
    source_event_id: str | None = Field(default=None, description="Idempotency key from gateway")


class LevelIngest(BaseModel):
    station_id: UUID
    tank_id: UUID
    actual_remainder_liters: float
    level_source: str = "electronic"  # manual | electronic
    recorded_at: datetime
    source_event_id: str | None = None


class DispenseIngest(BaseModel):
    """Read-only dispense data from Topaz-119-28M / ASKA-01 — never control commands."""

    station_id: UUID
    dispenser_id: UUID
    tank_id: UUID | None = None
    batch_id: UUID | None = None
    volume_liters: float
    started_at: datetime
    finished_at: datetime | None = None
    external_txn_id: str | None = None
    raw_payload: str | None = None


class IngestAck(BaseModel):
    accepted: bool = True
    message: str = "queued"
    entity_id: UUID | None = None
    duplicate: bool = False
