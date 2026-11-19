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
    columns_mode: str = "none"
    columns_count: int = 2


class StationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    address: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    is_active: bool = True
    columns_mode: str = Field(default="none", pattern="^(none|virtual|edge)$")
    columns_count: int = Field(default=2, ge=0, le=8)


class StationUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    is_active: bool | None = None
    columns_mode: str | None = Field(default=None, pattern="^(none|virtual|edge)$")
    columns_count: int | None = Field(default=None, ge=0, le=8)


class TankDeviceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    capacity_liters: float = Field(gt=0)


class TankDeviceUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    capacity_liters: float | None = Field(default=None, gt=0)


class ShellyBind(BaseModel):
    host: str = Field(min_length=1, max_length=253)


class ShellyLinkOut(BaseModel):
    host: str
    online: bool
    mac: str | None = None
    model: str | None = None
    firmware: str | None = None
    rssi: int | None = None
    sensor_ready: bool = False
    volts: float | None = None
    applied: bool = False
    last_polled_at: datetime | None = None
    last_error: str | None = None


class TankDeviceOut(BaseModel):
    id: UUID
    station_id: UUID
    code: str
    capacity_liters: float
    ingest_token: str | None = None
    level_path: str
    ingest_url: str | None = None
    shelly: ShellyLinkOut | None = None


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


class DispenseReadingOut(BaseModel):
    id: UUID
    station_id: UUID
    tank_id: UUID | None = None
    dispenser_id: UUID
    pump_address: int | None = None
    mode: str | None = None
    volume_liters: float
    price_kzt_per_liter: float | None = None
    started_at: str
    finished_at: str | None = None
    external_txn_id: str | None = None


class LevelReadingOut(BaseModel):
    id: UUID
    tank_id: UUID
    volts: float | None
    remainder_liters: float
    fill_percent: float | None
    recorded_at: str
    delta_liters: float | None = None


class AdminTankOverviewOut(BaseModel):
    id: UUID
    code: str
    capacity_liters: float
    ingest_token: str
    actual_remainder_liters: float | None = None
    calculated_remainder_liters: float | None = None
    fill_percent: float | None = None
    opening_liters: float | None = None
    receipts_liters: float = 0.0
    dispense_liters: float = 0.0
    delta_liters: float | None = None
    balance_status: str = "unknown"
    calibrated: bool = False
    cal_low_volts: float | None = None
    cal_low_percent: float | None = None
    cal_high_volts: float | None = None
    cal_high_percent: float | None = None
    last_volts: float | None = None
    last_measured_at: datetime | None = None
    online: bool = False
    shelly: ShellyLinkOut | None = None


class AdminStationOverviewOut(StationOut):
    tanks: list[AdminTankOverviewOut] = Field(default_factory=list)
