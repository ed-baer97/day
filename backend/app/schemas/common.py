"""Shared / map schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HealthOut(BaseModel):
    status: str = "ok"
    service: str
    version: str


class MapPoint(BaseModel):
    id: UUID
    kind: str = Field(description="factory | truck | station")
    name: str
    lat: float
    lon: float
    status: str | None = None
    meta: dict | None = None


class MapOverviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    points: list[MapPoint]
    active_trips: int = 0
    open_events: int = 0
