"""Batch and digital trail schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BatchCreate(BaseModel):
    trail_code: str = Field(min_length=1, max_length=64)
    supplier_id: UUID | None = None
    factory_id: UUID | None = None
    product_grade: str | None = Field(default=None, max_length=32)
    density_kg_per_liter: float | None = Field(default=None, gt=0, le=2.0)
    volume_liters: float = Field(gt=0, le=1_000_000)
    mass_kg: float | None = Field(default=None, gt=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=512)


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trail_code: str
    supplier_id: UUID | None
    factory_id: UUID | None
    product_grade: str | None
    density_kg_per_liter: float | None
    volume_liters: float
    mass_kg: float | None
    status: str
    formed_at: datetime | None
    notes: str | None
    created_at: datetime


class BatchTrailEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    node_type: str
    occurred_at: datetime
    title: str
    description: str | None
    ref_entity_type: str | None
    ref_entity_id: UUID | None
    volume_liters: float | None
    lat: float | None
    lon: float | None


class BatchTrailOut(BaseModel):
    batch: BatchOut
    chain: list[str] = Field(
        default_factory=lambda: [
            "supplier",
            "factory",
            "batch",
            "truck",
            "route",
            "station",
            "tank",
            "dispense",
            "sale",
        ]
    )
    events: list[BatchTrailEventOut] = Field(default_factory=list)
