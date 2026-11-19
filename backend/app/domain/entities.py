"""Нейтральные доменные сущности, не зависящие от адаптера хранения (memory/postgres)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.calibration import LevelCalibration

TRUCK_STATUSES = ("idle", "loading", "in_transit", "arrived", "unloading")
COLUMN_MODES = ("none", "virtual", "edge")


@dataclass
class StationCard:
    id: UUID
    code: str
    name: str
    address: str | None
    lat: float
    lon: float
    is_active: bool
    columns_mode: str = "none"
    columns_count: int = 2


@dataclass
class TruckCard:
    id: UUID
    plate_number: str
    capacity_liters: float
    carrier_name: str | None
    status: str
    lat: float | None
    lon: float | None


@dataclass
class TankDevice:
    """Карточка резервуара: объём задаёт сайт, токен выбирает станцию и резервуар."""

    station_id: UUID
    tank_id: UUID
    code: str
    capacity_liters: float
    token: str


@dataclass
class TankBook:
    station_id: UUID
    tank_id: UUID
    opening_liters: float | None = None
    receipts_liters: float = 0.0
    dispense_liters: float = 0.0
    pending_dispense_liters: float = 0.0
    pending_receipt_liters: float = 0.0
    actual_remainder_liters: float | None = None
    calculated_remainder_liters: float | None = None
    delta_liters: float | None = None
    balance_status: str = "unknown"
    calibration: LevelCalibration | None = None
    last_volts: float | None = None
    last_measured_at: datetime | None = None
    level_ids: dict[str, UUID] = field(default_factory=dict)


@dataclass
class StationOwner:
    id: UUID
    station_id: UUID
    username: str
    password_hash: str
    kind: str = "owner"
    station_ids: list[UUID] = field(default_factory=list)

    def stations(self) -> list[UUID]:
        if self.station_ids:
            return list(self.station_ids)
        return [self.station_id]


@dataclass(frozen=True)
class TankBookAck:
    """Доменный результат приёма телеметрии по книге резервуара."""

    accepted: bool = True
    message: str = "queued"
    entity_id: UUID | None = None
    duplicate: bool = False
    actual_remainder_liters: float | None = None
    calculated_remainder_liters: float | None = None
    delta_liters: float | None = None
    balance_status: str | None = None


@dataclass(frozen=True)
class TankBookState:
    """Доменный снимок текущего состояния книги резервуара."""

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
    cal_low_volts: float | None = None
    cal_low_percent: float | None = None
    cal_high_volts: float | None = None
    cal_high_percent: float | None = None


def parse_dispense_meta(
    dispenser_id: UUID,
    raw_payload: str | None,
) -> tuple[int, str | None, float | None]:
    """Извлекает номер колонки (1..8), режим налива и цену из JSON raw_payload или dispenser_id."""
    fallback_addr = 2 if dispenser_id.int % 2 == 0 else 1
    if not raw_payload:
        return fallback_addr, None, None
    try:
        meta = json.loads(raw_payload)
    except (json.JSONDecodeError, TypeError):
        return fallback_addr, None, None
    if not isinstance(meta, dict):
        return fallback_addr, None, None

    raw_addr = meta.get("pump_address")
    if isinstance(raw_addr, int) and not isinstance(raw_addr, bool) and 1 <= raw_addr <= 8:
        pump_address = raw_addr
    else:
        pump_address = fallback_addr
    mode = str(meta["mode"]) if meta.get("mode") is not None else None
    raw_price = meta.get("price_kzt_per_liter")
    price = float(raw_price) if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool) else None
    return pump_address, mode, price
