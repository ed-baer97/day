"""Общие функции валидации, идемпотентности, сборки схем и сериализации для memory и postgres."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import UUID

from app.domain.calibration import LevelCalibration
from app.domain.entities import (
    TRUCK_STATUSES,
    TankBookAck,
    TankBookState,
    parse_dispense_meta,
)
from app.domain.errors import ConflictError, ValidationError
from app.schemas.ingest import IngestAck, TankIngestState
from app.schemas.station import DispenseReadingOut, TankOut

_GPS_LOCK = threading.Lock()
_SEEN_GPS: set[str] = set()
_MAX_SEEN_GPS = 10_000


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def require_non_empty(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"укажите {label}")
    return cleaned


def require_truck_status(value: str) -> str:
    if value not in TRUCK_STATUSES:
        raise ValidationError("неизвестный статус газовоза")
    return value


def require_station_and_tank(
    station_id: UUID | None,
    tank_id: UUID | None,
    detail: str = "укажите резервуар токеном или полями station_id и tank_id",
) -> tuple[UUID, UUID]:
    if station_id is None or tank_id is None:
        raise ValidationError(detail)
    return station_id, tank_id


def require_calibration_points(low_volts: float, high_volts: float) -> None:
    if low_volts == high_volts:
        raise ValidationError("точки калибровки совпадают по напряжению")


def clean_owner_username(
    username: str,
    admin_username: str,
    *,
    empty_detail: str = "укажите логин",
) -> str:
    cleaned = username.strip().lower()
    if not cleaned:
        raise ValidationError(empty_detail)
    if cleaned == admin_username.strip().lower():
        raise ConflictError("этот логин занят администратором платформы")
    return cleaned


def require_owner_password(password: str) -> None:
    if len(password) < 6:
        raise ValidationError("пароль владельца не короче 6 символов")


def level_event_key(tank_id: UUID, recorded_at: datetime, source_event_id: str | None) -> str:
    return source_event_id or f"level:{tank_id}:{recorded_at.isoformat()}"


def dispense_event_key(dispenser_id: UUID, started_at: datetime, external_txn_id: str | None) -> str:
    return external_txn_id or f"dispense:{dispenser_id}:{started_at.isoformat()}"


def receipt_event_key(tank_id: UUID, recorded_at: datetime, source_event_id: str | None) -> str:
    return source_event_id or f"receipt:{tank_id}:{recorded_at.isoformat()}"


def gps_event_key(truck_id: UUID, recorded_at: datetime, source_event_id: str | None) -> str:
    return source_event_id or f"gps:{truck_id}:{recorded_at.isoformat()}"


def is_gps_seen(key: str) -> bool:
    with _GPS_LOCK:
        return key in _SEEN_GPS


def remember_gps(key: str) -> None:
    with _GPS_LOCK:
        if len(_SEEN_GPS) >= _MAX_SEEN_GPS:
            _SEEN_GPS.clear()
        _SEEN_GPS.add(key)


def reset_gps_seen() -> None:
    with _GPS_LOCK:
        _SEEN_GPS.clear()


def ack_to_schema(ack: TankBookAck) -> IngestAck:
    return IngestAck(
        accepted=ack.accepted,
        message=ack.message,
        entity_id=ack.entity_id,
        duplicate=ack.duplicate,
        actual_remainder_liters=ack.actual_remainder_liters,
        calculated_remainder_liters=ack.calculated_remainder_liters,
        delta_liters=ack.delta_liters,
        balance_status=ack.balance_status,
    )


def state_to_schema(state: TankBookState) -> TankIngestState:
    return TankIngestState(
        station_id=state.station_id,
        tank_id=state.tank_id,
        opening_liters=state.opening_liters,
        receipts_liters=state.receipts_liters,
        dispense_liters=state.dispense_liters,
        pending_dispense_liters=state.pending_dispense_liters,
        calculated_remainder_liters=state.calculated_remainder_liters,
        actual_remainder_liters=state.actual_remainder_liters,
        delta_liters=state.delta_liters,
        balance_status=state.balance_status,
        calibrated=state.calibrated,
        last_volts=state.last_volts,
        last_measured_at=state.last_measured_at,
    )


def build_tank_out(
    *,
    tank_id: UUID,
    code: str,
    capacity_liters: float,
    actual_remainder_liters: float | None,
    calculated_remainder_liters: float | None,
    last_measured_at: datetime | None,
    has_electronic_sensor: bool = True,
    level_source: str = "electronic",
) -> TankOut:
    calc = actual_remainder_liters if calculated_remainder_liters is None else calculated_remainder_liters
    return TankOut(
        id=tank_id,
        code=code,
        capacity_liters=capacity_liters,
        has_electronic_sensor=has_electronic_sensor,
        actual_remainder_liters=actual_remainder_liters,
        calculated_remainder_liters=calc,
        level_source=level_source,
        last_measured_at=last_measured_at,
    )


def build_dispense_out(
    *,
    record_id: UUID,
    station_id: UUID,
    tank_id: UUID | None,
    dispenser_id: UUID,
    volume_liters: float,
    started_at: datetime,
    finished_at: datetime | None,
    external_txn_id: str | None,
    raw_payload: str | None,
) -> DispenseReadingOut:
    pump_address, mode, price = parse_dispense_meta(dispenser_id, raw_payload)
    return DispenseReadingOut(
        id=record_id,
        station_id=station_id,
        tank_id=tank_id,
        dispenser_id=dispenser_id,
        pump_address=pump_address,
        mode=mode,
        volume_liters=volume_liters,
        price_kzt_per_liter=price,
        started_at=started_at.isoformat(),
        finished_at=None if finished_at is None else finished_at.isoformat(),
        external_txn_id=external_txn_id,
    )


def batch_counts(
    results: list[IngestAck],
    volumes: list[float] | None = None,
) -> tuple[int, int, float]:
    accepted = 0
    duplicates = 0
    total = 0.0
    for index, ack in enumerate(results):
        if ack.duplicate:
            duplicates += 1
            continue
        accepted += 1
        if volumes is not None:
            total += volumes[index]
    return accepted, duplicates, total


def calibration_to_dict(calibration: LevelCalibration | None) -> dict[str, float] | None:
    if calibration is None:
        return None
    return {
        "capacity_liters": calibration.capacity_liters,
        "low_volts": calibration.low_volts,
        "low_percent": calibration.low_percent,
        "high_volts": calibration.high_volts,
        "high_percent": calibration.high_percent,
    }


def calibration_from_dict(
    raw_cal: object,
    *,
    default_capacity: float | None = None,
) -> LevelCalibration | None:
    if not isinstance(raw_cal, dict):
        return None
    if None in (
        raw_cal.get("low_volts"),
        raw_cal.get("low_percent"),
        raw_cal.get("high_volts"),
        raw_cal.get("high_percent"),
    ):
        return None
    raw_cap = raw_cal.get("capacity_liters", default_capacity)
    if raw_cap is None:
        return None
    return LevelCalibration(
        capacity_liters=float(raw_cap),
        low_volts=float(raw_cal["low_volts"]),
        low_percent=float(raw_cal["low_percent"]),
        high_volts=float(raw_cal["high_volts"]),
        high_percent=float(raw_cal["high_percent"]),
    )


def parse_iso_utc(raw: object) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def extract_book_fields(row: dict) -> dict[str, object]:
    """Нормализует поля книги резервуара из JSON-снимка для restore_snapshot и Postgres import."""
    return {
        "opening_liters": row.get("opening_liters"),
        "receipts_liters": float(row.get("receipts_liters") or 0.0),
        "dispense_liters": float(row.get("dispense_liters") or 0.0),
        "pending_dispense_liters": float(row.get("pending_dispense_liters") or 0.0),
        "pending_receipt_liters": float(row.get("pending_receipt_liters") or 0.0),
        "actual_remainder_liters": row.get("actual_remainder_liters"),
        "last_volts": row.get("last_volts"),
        "last_measured_at": parse_iso_utc(row.get("last_measured_at")),
        "calibration": calibration_from_dict(row.get("calibration")),
    }
