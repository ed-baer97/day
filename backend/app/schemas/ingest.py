"""Ingest payloads from AGZS gateway / truck telematics."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class GpsIngest(BaseModel):
    truck_id: UUID
    lat: float
    lon: float
    speed_kmh: float | None = None
    recorded_at: datetime
    source_event_id: str | None = Field(default=None, description="Idempotency key from gateway")


class LevelIngest(BaseModel):
    """Shelly шлёт литры или сырые вольты датчика Холла.

    Вольты переводятся в литры по калибровке резервуара.
    Первое показание фиксирует стартовый остаток книги.
    """

    station_id: UUID | None = None
    tank_id: UUID | None = None
    actual_remainder_liters: float | None = None
    volts: float | None = None
    level_source: str = "electronic"  # manual | electronic
    recorded_at: datetime
    source_event_id: str | None = None

    @model_validator(mode="after")
    def reading_present(self) -> "LevelIngest":
        if self.actual_remainder_liters is None and self.volts is None:
            raise ValueError("передайте actual_remainder_liters или volts")
        return self


class DispenseIngest(BaseModel):
    """Read-only dispense data from Topaz-119-28M / ASKA-01 — never control commands."""

    station_id: UUID
    dispenser_id: UUID
    tank_id: UUID | None = None
    batch_id: UUID | None = None
    volume_liters: float = Field(gt=0)
    started_at: datetime
    finished_at: datetime | None = None
    external_txn_id: str | None = None
    raw_payload: str | None = None


class ReceiptIngest(BaseModel):
    """Приёмка в резервуар. Не приходит с Shelly и не с Топаза."""

    station_id: UUID
    tank_id: UUID
    volume_liters: float = Field(gt=0)
    recorded_at: datetime
    source_event_id: str | None = None


class CalibrationIn(BaseModel):
    """Две точки циферблата: напряжение и процент объёма.

    Объём берётся с карточки резервуара, если прибор уже заведён на сайте.
    """

    station_id: UUID | None = None
    tank_id: UUID | None = None
    capacity_liters: float | None = Field(default=None, gt=0)
    low_volts: float
    low_percent: float = Field(ge=0, le=100)
    high_volts: float
    high_percent: float = Field(ge=0, le=100)


class IngestAck(BaseModel):
    accepted: bool = True
    message: str = "queued"
    entity_id: UUID | None = None
    duplicate: bool = False
    actual_remainder_liters: float | None = None
    calculated_remainder_liters: float | None = None
    delta_liters: float | None = None
    balance_status: str | None = None


class TankIngestState(BaseModel):
    station_id: UUID
    tank_id: UUID
    opening_liters: float | None
    receipts_liters: float
    dispense_liters: float
    pending_dispense_liters: float
    calculated_remainder_liters: float | None
    actual_remainder_liters: float | None
    delta_liters: float | None
    balance_status: str
    calibrated: bool
    last_volts: float | None
    last_measured_at: datetime | None
