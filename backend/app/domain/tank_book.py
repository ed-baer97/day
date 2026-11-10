"""Чистая доменная логика книги резервуара (Tank Book).

Не зависит от способа хранения (in-memory словарь или PostgreSQL ORM).
Формула книги:
    calculated_remainder = opening_liters + receipts_liters - dispense_liters
Отпуски и приёмки, пришедшие до первого показания физического уровня (opening_liters is None),
учитываются в pending_* и не сдвигают расчётный остаток после старта, так как уже учтены в стартовом уровне.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from app.domain.errors import CalibrationRequired
from app.schemas.ingest import IngestAck, LevelIngest, TankIngestState
from app.schemas.station import TankOut
from app.services.balance import calculate_remainder, classify_discrepancy
from app.services.calibration import (
    LevelCalibration,
    level_volts_changed,
    round_percent,
    volts_to_percent,
)

CALIBRATION_REQUIRED = "для volts нужна калибровка резервуара: POST /ingest/calibration"


def recompute_tank_book(target: Any) -> tuple[float | None, float | None, str]:
    """Пересчитывает расчётный остаток, невязку (delta) и статус сверки для бака."""
    if target.opening_liters is None:
        target.calculated_remainder_liters = None
        if hasattr(target, "delta_liters"):
            target.delta_liters = None
        if hasattr(target, "balance_status"):
            target.balance_status = "unknown"
        return None, None, "unknown"

    calculated = calculate_remainder(
        target.opening_liters,
        target.receipts_liters,
        target.dispense_liters,
    )
    result = classify_discrepancy(calculated, target.actual_remainder_liters)
    target.calculated_remainder_liters = result.calculated_remainder_liters
    if hasattr(target, "delta_liters"):
        target.delta_liters = result.delta_liters
    if hasattr(target, "balance_status"):
        target.balance_status = result.status
    return result.calculated_remainder_liters, result.delta_liters, result.status


def build_ingest_ack(
    target: Any,
    *,
    message: str,
    duplicate: bool = False,
    entity_id: UUID | None = None,
) -> IngestAck:
    """Формирует стандартный ответ IngestAck по текущему состоянию резервуара."""
    calculated, delta, status = recompute_tank_book(target)
    return IngestAck(
        accepted=True,
        message=message,
        entity_id=entity_id,
        duplicate=duplicate,
        actual_remainder_liters=target.actual_remainder_liters,
        calculated_remainder_liters=calculated,
        delta_liters=delta,
        balance_status=status,
    )


def build_tank_ingest_state(
    target: Any,
    *,
    station_id: UUID,
    tank_id: UUID,
    calibrated: bool,
) -> TankIngestState:
    """Формирует карточку состояния книги резервуара TankIngestState."""
    calculated, delta, status = recompute_tank_book(target)
    return TankIngestState(
        station_id=station_id,
        tank_id=tank_id,
        opening_liters=target.opening_liters,
        receipts_liters=target.receipts_liters,
        dispense_liters=target.dispense_liters,
        pending_dispense_liters=target.pending_dispense_liters,
        calculated_remainder_liters=calculated,
        actual_remainder_liters=target.actual_remainder_liters,
        delta_liters=delta,
        balance_status=status,
        calibrated=calibrated,
        last_volts=target.last_volts,
        last_measured_at=target.last_measured_at,
    )


def apply_level_reading(
    target: Any,
    body: LevelIngest,
    calibration: LevelCalibration | None,
    *,
    capacity_liters: float | None = None,
    heard_at: datetime,
) -> tuple[bool, float, float | None]:
    """Применяет показание уровня к баку.

    Возвращает кортеж (changed, liters, fill_percent):
    - changed=False, если напряжение volts изменилось в пределах шума (процент не сдвинулся);
    - changed=True, если замер новый и должен быть записан в журнал.
    """
    effective_capacity = (
        capacity_liters
        if capacity_liters is not None
        else (calibration.capacity_liters if calibration is not None else getattr(target, "capacity_liters", 0.0) or 0.0)
    )

    if (
        body.volts is not None
        and body.actual_remainder_liters is None
        and target.last_volts is not None
        and calibration is not None
        and not level_volts_changed(target.last_volts, body.volts)
    ):
        percent = round_percent(volts_to_percent(target.last_volts, calibration))
        liters = percent / 100 * calibration.capacity_liters
        target.actual_remainder_liters = liters
        target.last_measured_at = heard_at
        recompute_tank_book(target)
        return False, liters, float(percent)

    if body.actual_remainder_liters is not None:
        if body.volts is not None:
            target.last_volts = body.volts
        liters = body.actual_remainder_liters
        fill = (
            None
            if effective_capacity <= 0
            else float(round_percent(liters / effective_capacity * 100))
        )
    else:
        if calibration is None or body.volts is None:
            raise CalibrationRequired(CALIBRATION_REQUIRED)
        percent = round_percent(volts_to_percent(body.volts, calibration))
        target.last_volts = body.volts
        liters = percent / 100 * calibration.capacity_liters
        fill = float(percent)

    if target.opening_liters is None or (
        target.opening_liters < 0 and target.receipts_liters == 0 and target.dispense_liters == 0
    ):
        target.opening_liters = liters

    target.actual_remainder_liters = liters
    target.last_measured_at = heard_at
    recompute_tank_book(target)
    return True, liters, fill


def apply_dispense_volume(target: Any, volume_liters: float) -> None:
    """Проводит отпуск по книге резервуара."""
    if target.opening_liters is None:
        target.pending_dispense_liters += volume_liters
    else:
        target.dispense_liters += volume_liters
        recompute_tank_book(target)


def apply_receipt_volume(target: Any, volume_liters: float) -> None:
    """Проводит приёмку (слив газовоза) по книге резервуара."""
    if target.opening_liters is None:
        target.pending_receipt_liters += volume_liters
    else:
        target.receipts_liters += volume_liters
        recompute_tank_book(target)


def summarize_station_tanks(
    tanks: Sequence[TankOut],
) -> tuple[float | None, float | None, float | None, str]:
    """Считает суммарный остаток, ёмкость, дельту и статус сверки по всем бакам станции."""
    if not tanks:
        return None, None, None, "unknown"

    total_actual = sum(t.actual_remainder_liters or 0.0 for t in tanks)
    total_capacity = sum(t.capacity_liters for t in tanks)

    has_any_book = any(
        t.calculated_remainder_liters is not None and t.actual_remainder_liters is not None
        for t in tanks
    )
    if not has_any_book:
        return total_actual, total_capacity, None, "unknown"

    total_calc = sum(
        t.calculated_remainder_liters
        for t in tanks
        if t.calculated_remainder_liters is not None and t.actual_remainder_liters is not None
    )
    total_act_with_book = sum(
        t.actual_remainder_liters
        for t in tanks
        if t.calculated_remainder_liters is not None and t.actual_remainder_liters is not None
    )
    result = classify_discrepancy(total_calc, total_act_with_book)
    return total_actual, total_capacity, result.delta_liters, result.status
