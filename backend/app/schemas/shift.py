"""Схемы кассовых смен и отчётов по смене."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.station import DispenseReadingOut


class ShiftOpenIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ShiftCloseIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ShiftTankSnapshotOut(BaseModel):
    tank_id: UUID
    code: str
    capacity_liters: float
    remainder_liters: float | None = None
    fill_percent: float | None = None
    measured_at: str | None = None


class ShiftColumnSummaryOut(BaseModel):
    pump_address: int
    code: str
    name: str
    volume_liters: float
    ops_count: int
    amount_kzt: float | None = None
    last_liters: float | None = None
    last_at: str | None = None


class ShiftOut(BaseModel):
    id: UUID
    station_id: UUID
    station_name: str | None = None
    station_code: str | None = None
    status: str
    opened_by: str
    closed_by: str | None = None
    opened_at: str
    closed_at: str | None = None
    opening_tank_liters: float | None = None
    closing_tank_liters: float | None = None
    opening_tanks: list[ShiftTankSnapshotOut] = Field(default_factory=list)
    closing_tanks: list[ShiftTankSnapshotOut] = Field(default_factory=list)
    receipts_liters: float = 0.0
    dispensed_liters: float = 0.0
    dispense_count: int = 0
    total_amount_kzt: float | None = None
    columns: list[ShiftColumnSummaryOut] = Field(default_factory=list)
    tank_delta_liters: float | None = None
    discrepancy_liters: float | None = None
    note: str | None = None


class ShiftDetailOut(ShiftOut):
    dispenses: list[DispenseReadingOut] = Field(default_factory=list)
