"""Balance schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BalanceReconcileRequest(BaseModel):
    station_id: UUID
    tank_id: UUID
    period_start: datetime
    period_end: datetime
    previous_remainder_liters: float
    receipts_liters: float = 0.0
    dispense_liters: float = 0.0
    actual_remainder_liters: float | None = None


class BalanceSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    station_id: UUID
    tank_id: UUID
    period_start: datetime
    period_end: datetime
    previous_remainder_liters: float
    receipts_liters: float
    dispense_liters: float
    calculated_remainder_liters: float
    actual_remainder_liters: float | None
    delta_liters: float | None
    status: str
    created_at: datetime


class ConsumptionSummary(BaseModel):
    station_id: UUID
    day_liters: float = 0.0
    week_liters: float = 0.0
    month_liters: float = 0.0
    sales_day_count: int = 0
    movement_history: list[dict] = Field(default_factory=list)
