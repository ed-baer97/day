"""Общие функции валидации, идемпотентности, сборки схем и сериализации для memory и postgres."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from uuid import UUID

from app.domain.calibration import LevelCalibration
from app.domain.entities import (
    COLUMN_MODES,
    TRUCK_STATUSES,
    ShiftColumnSummary,
    ShiftTankSnapshot,
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


def require_columns_mode(value: str) -> str:
    if value not in COLUMN_MODES:
        raise ValidationError("неизвестный режим колонок")
    return value


def require_columns_count(value: int) -> int:
    if value < 0 or value > 8:
        raise ValidationError("количество колонок от 0 до 8")
    return value


def require_station_and_tank(
    station_id: UUID | None,
    tank_id: UUID | None,
    detail: str = "укажите резервуар токеном или полями station_id и tank_id",
) -> tuple[UUID, UUID]:
    if station_id is None or tank_id is None:
        raise ValidationError(detail)
    return station_id, tank_id


def require_calibration_points(
    low_volts: float,
    high_volts: float,
    low_percent: float | None = None,
    high_percent: float | None = None,
) -> None:
    if low_volts == high_volts:
        raise ValidationError("точки калибровки совпадают по напряжению")
    if low_percent is not None and high_percent is not None and low_percent == high_percent:
        raise ValidationError("точки калибровки совпадают по проценту")


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


def require_user_password(password: str, label: str = "пользователя") -> None:
    if len(password) < 6:
        raise ValidationError(f"пароль {label} не короче 6 символов")


def require_owner_password(password: str) -> None:
    require_user_password(password, "владельца")


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
        cal_low_volts=state.cal_low_volts,
        cal_low_percent=state.cal_low_percent,
        cal_high_volts=state.cal_high_volts,
        cal_high_percent=state.cal_high_percent,
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


BATCH_STATUS_TITLES = {
    "formed": "Партия сформирована",
    "in_transit": "Газовоз в пути",
    "delivered": "Партия слита на АГЗС",
    "closed": "Партия закрыта по балансу",
}


def batch_status_title(status: str) -> str:
    return BATCH_STATUS_TITLES.get(status, f"Статус: {status}")


def batch_status_node_value(status: str) -> str:
    if status == "in_transit":
        return "route"
    if status == "delivered":
        return "tank"
    return "batch"


def dump_shift_tanks(items: list[ShiftTankSnapshot]) -> str:
    payload = [
        {
            "tank_id": str(item.tank_id),
            "code": item.code,
            "capacity_liters": float(item.capacity_liters),
            "remainder_liters": item.remainder_liters,
            "fill_percent": item.fill_percent,
            "measured_at": None if item.measured_at is None else item.measured_at.isoformat(),
        }
        for item in items
    ]
    return json.dumps(payload, ensure_ascii=False)


def load_shift_tanks(raw: object) -> list[ShiftTankSnapshot]:
    if not raw:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(data, list):
        return []
    result: list[ShiftTankSnapshot] = []
    for row in data:
        if not isinstance(row, dict) or not row.get("tank_id"):
            continue
        result.append(
            ShiftTankSnapshot(
                tank_id=UUID(str(row["tank_id"])),
                code=str(row.get("code") or ""),
                capacity_liters=float(row.get("capacity_liters") or 0.0),
                remainder_liters=None
                if row.get("remainder_liters") is None
                else float(row["remainder_liters"]),
                fill_percent=None
                if row.get("fill_percent") is None
                else float(row["fill_percent"]),
                measured_at=parse_iso_utc(row.get("measured_at")),
            )
        )
    return result


def dump_shift_columns(items: list[ShiftColumnSummary]) -> str:
    payload = [
        {
            "pump_address": int(item.pump_address),
            "code": item.code,
            "name": item.name,
            "volume_liters": float(item.volume_liters),
            "ops_count": int(item.ops_count),
            "amount_kzt": item.amount_kzt,
            "last_liters": item.last_liters,
            "last_at": None if item.last_at is None else item.last_at.isoformat(),
        }
        for item in items
    ]
    return json.dumps(payload, ensure_ascii=False)


def load_shift_columns(raw: object) -> list[ShiftColumnSummary]:
    if not raw:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(data, list):
        return []
    result: list[ShiftColumnSummary] = []
    for row in data:
        if not isinstance(row, dict) or row.get("pump_address") is None:
            continue
        result.append(
            ShiftColumnSummary(
                pump_address=int(row["pump_address"]),
                code=str(row.get("code") or f"ТРК-{int(row['pump_address'])}"),
                name=str(row.get("name") or f"Колонка {int(row['pump_address'])}"),
                volume_liters=float(row.get("volume_liters") or 0.0),
                ops_count=int(row.get("ops_count") or 0),
                amount_kzt=None if row.get("amount_kzt") is None else float(row["amount_kzt"]),
                last_liters=None if row.get("last_liters") is None else float(row["last_liters"]),
                last_at=parse_iso_utc(row.get("last_at")),
            )
        )
    return result

