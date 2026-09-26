"""Station and tank schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TankOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    capacity_liters: float
    has_electronic_sensor: bool
    actual_remainder_liters: float | None
    calculated_remainder_liters: float | None
    level_source: str
    last_measured_at: datetime | None


class StationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    address: str | None
    lat: float
    lon: float
    is_active: bool


class StationDetailOut(StationOut):
    tanks: list[TankOut] = Field(default_factory=list)
    remainder_liters: float | None = None
    capacity_liters: float | None = None
    receipts_day_liters: float = 0.0
    consumption_day_liters: float = 0.0
    consumption_week_liters: float = 0.0
    consumption_month_liters: float = 0.0
    sales_day_count: int = 0
    active_trucks: list[dict] = Field(default_factory=list)
    balance_status: str = "unknown"
    calculated_vs_actual_delta: float | None = None
