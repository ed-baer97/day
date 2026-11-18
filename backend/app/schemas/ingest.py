"""Ingest payloads from AGZS gateway / truck telematics."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class GpsIngest(BaseModel):
    truck_id: UUID
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed_kmh: float | None = Field(default=None, ge=0, le=300)
    recorded_at: datetime
    source_event_id: str | None = Field(default=None, max_length=128, description="Idempotency key from gateway")


class LevelIngest(BaseModel):
    """Shelly шлёт литры или сырые вольты датчика Холла.

    Вольты переводятся в литры по калибровке резервуара.
    Первое показание фиксирует стартовый остаток книги.
    """

    station_id: UUID | None = None
    tank_id: UUID | None = None
    actual_remainder_liters: float | None = Field(default=None, ge=0, le=1_000_000)
    volts: float | None = Field(default=None, ge=-50, le=50)
    level_source: str = Field(default="electronic", max_length=32)  # manual | electronic
    recorded_at: datetime
    source_event_id: str | None = Field(default=None, max_length=128)

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
    volume_liters: float = Field(gt=0, le=100_000)
    started_at: datetime
    finished_at: datetime | None = None
    external_txn_id: str | None = Field(default=None, max_length=128)
    raw_payload: str | None = Field(default=None, max_length=4096)


class ReceiptIngest(BaseModel):
    """Приёмка в резервуар. Не приходит с Shelly и не с Топаза."""

    station_id: UUID
    tank_id: UUID
    volume_liters: float = Field(gt=0, le=1_000_000)
    recorded_at: datetime
    source_event_id: str | None = Field(default=None, max_length=128)


class CalibrationIn(BaseModel):
    """Две точки циферблата: напряжение и процент объёма.

    Объём берётся с карточки резервуара, если прибор уже заведён на сайте.
    """

    station_id: UUID | None = None
    tank_id: UUID | None = None
    capacity_liters: float | None = Field(default=None, gt=0, le=1_000_000)
    low_volts: float = Field(ge=-50, le=50)
    low_percent: float = Field(ge=0, le=100)
    high_volts: float = Field(ge=-50, le=50)
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


class DispenseBatchIngest(BaseModel):
    """Пакет наливов с edge-компьютера АГЗС (АСКА-02 / Топаз)."""

    items: list[DispenseIngest] = Field(min_length=1, max_length=200)


class DispenseBatchAck(BaseModel):
    accepted_count: int
    duplicates_count: int
    total_volume_liters: float
    results: list[IngestAck]


class LevelBatchIngest(BaseModel):
    """Пакет замеров уровня (накопленные при обрыве связи)."""

    items: list[LevelIngest] = Field(min_length=1, max_length=200)


class LevelBatchAck(BaseModel):
    accepted_count: int
    duplicates_count: int
    results: list[IngestAck]


class EdgeReleaseManifest(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    artifact_url: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(min_length=64, max_length=64)
    channel: str = Field(default="stable", pattern="^(stable|canary|ring0|ring1|ring2)$")
    min_version: str | None = Field(default=None, max_length=64)
    notes: str = Field(default="", max_length=1024)


class EdgeReleaseOut(EdgeReleaseManifest):
    update_required: bool = False


class EdgeHeartbeatIn(BaseModel):
    station_code: str = Field(min_length=1, max_length=64)
    station_id: UUID | None = None
    current_version: str = Field(min_length=1, max_length=64)
    channel: str = Field(default="stable", pattern="^(stable|canary|ring0|ring1|ring2)$")
    outbox_pending: int = Field(default=0, ge=0)
    active_pumps: int = Field(default=0, ge=0, le=6)
    update_status: str = Field(default="ok", max_length=64)
    last_error: str | None = Field(default=None, max_length=1024)


class EdgeNodeStatus(BaseModel):
    station_code: str
    station_id: UUID | None = None
    current_version: str
    target_version: str
    channel: str
    up_to_date: bool
    outbox_pending: int
    active_pumps: int
    update_status: str
    last_error: str | None = None
    last_seen_at: datetime


class EdgeHeartbeatAck(BaseModel):
    accepted: bool = True
    update_required: bool
    release: EdgeReleaseOut


class EdgeFleetSummaryOut(BaseModel):
    total_nodes: int
    up_to_date_nodes: int
    outdated_nodes: int
    releases: dict[str, EdgeReleaseManifest]
    canary_stations: list[str]
    ring1_stations: list[str] = Field(default_factory=list)
    nodes: list[EdgeNodeStatus]

