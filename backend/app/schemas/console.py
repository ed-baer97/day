"""Снимок пульта колонок."""

from uuid import UUID

from pydantic import BaseModel, Field


class PumpFace(BaseModel):
    pump_id: str
    name: str
    address: str
    status: str
    observation_quality: str
    price_kzt_per_liter: int
    dose_ml: int | None
    totalizer_ml: int | None
    provisional_kzt: int | None
    sale_id: str | None
    payment_status: str | None


class ShiftFace(BaseModel):
    shift_id: str
    number: int
    status: str


class ConsoleFace(BaseModel):
    station_id: UUID
    station_name: str
    emulator: bool
    link_up: bool
    commands_latched: bool
    shift: ShiftFace | None
    pumps: list[PumpFace]


class ConsoleAction(BaseModel):
    message: str
    desk: ConsoleFace


class DoseIn(BaseModel):
    mode: str = Field(pattern="^(money|volume)$")
    buffer: str = Field(default="", max_length=16)


class LatchIn(BaseModel):
    latched: bool


class LinkIn(BaseModel):
    up: bool


class JournalRow(BaseModel):
    occurred_at: str
    pump_name: str
    sale_number: str
    title: str
    change: str
    detail: str


class PriceIn(BaseModel):
    price_kzt_per_liter: int = Field(ge=1, le=100_000)


class CabinetPump(BaseModel):
    pump_id: str
    name: str
    delivered_ml: int
    amount_kzt: int
    sales: int


class CabinetSale(BaseModel):
    sale_id: str
    number: str
    pump_name: str
    delivered_ml: int
    amount_kzt: int
    price_kzt_per_liter: int
    finished_at: str


class CabinetFace(BaseModel):
    station_id: UUID
    price_kzt_per_liter: int
    delivered_ml: int
    amount_kzt: int
    sales: int
    pumps: list[CabinetPump]
    recent: list[CabinetSale]


class IncidentRow(BaseModel):
    incident_id: str
    severity: str
    code: str
    message: str
    pump_id: str | None
    sale_id: str | None
    occurred_at: str
    pump_name: str
    sale_number: str
    acknowledged: bool
