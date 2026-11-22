"""Чистая доменная логика книги резервуара (Tank Book).

Не зависит от FastAPI, Pydantic-схем и адаптеров хранения (memory / PostgreSQL).
Формула книги:
    calculated_remainder = opening_liters + receipts_liters - dispense_liters
Отпуски и приёмки, пришедшие до первого показания физического уровня (opening_liters is None),
учитываются в pending_* и не сдвигают расчётный остаток после старта, так как уже учтены в стартовом уровне.
Пока приёмок и отпусков нет, начальный остаток следует за шкалой: симуляция уровня не создаёт расхождение.
После первой приёмки или отпуска книга больше не подстраивается под датчик.
Датчик остаётся ориентиром в полосе ёмкости. Инцидент пишется только на слив без документа
и на уход без колонки.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.domain.balance import (
    SENSOR_WATCH_GAP,
    SENSOR_WATCH_SLIDE,
    SensorAlert,
    as_utc,
    calculate_remainder,
    classify_discrepancy,
    classify_sensor_watch,
)
from app.domain.calibration import (
    LevelCalibration,
    level_volts_changed,
    round_percent,
    volts_to_percent,
)
from app.domain.entities import TankBookAck, TankBookState
from app.domain.errors import CalibrationRequired

CALIBRATION_REQUIRED = "для volts нужна калибровка резервуара: POST /ingest/calibration"


class LevelReadingInput(Protocol):
    volts: float | None
    actual_remainder_liters: float | None


class TankSummaryInput(Protocol):
    capacity_liters: float
    actual_remainder_liters: float | None
    calculated_remainder_liters: float | None


def _tank_capacity(target: Any, capacity_liters: float | None = None) -> float | None:
    if capacity_liters is not None and capacity_liters > 0:
        return capacity_liters
    raw = getattr(target, "capacity_liters", None)
    if raw is None:
        return None
    value = float(raw)
    return value if value > 0 else None


def recompute_tank_book(
    target: Any,
    *,
    capacity_liters: float | None = None,
) -> tuple[float | None, float | None, str]:
    """Пересчитывает расчётный остаток, невязку (delta) и статус ориентира датчика."""
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
    result = classify_discrepancy(
        calculated,
        target.actual_remainder_liters,
        capacity_liters=_tank_capacity(target, capacity_liters),
    )
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
) -> TankBookAck:
    """Формирует доменный результат операции по текущему состоянию резервуара."""
    calculated, delta, status = recompute_tank_book(target)
    return TankBookAck(
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
    calibration: LevelCalibration | None = None,
) -> TankBookState:
    """Формирует доменный снимок состояния книги резервуара."""
    calculated, delta, status = recompute_tank_book(target)
    return TankBookState(
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
        cal_low_volts=None if calibration is None else calibration.low_volts,
        cal_low_percent=None if calibration is None else calibration.low_percent,
        cal_high_volts=None if calibration is None else calibration.high_volts,
        cal_high_percent=None if calibration is None else calibration.high_percent,
    )


def _gauge_is_the_book(target: Any) -> bool:
    """Уровень — единственный источник, пока нет отдельной приёмки или отпуска."""
    return (
        float(getattr(target, "receipts_liters", 0) or 0) == 0
        and float(getattr(target, "dispense_liters", 0) or 0) == 0
        and float(getattr(target, "pending_receipt_liters", 0) or 0) == 0
        and float(getattr(target, "pending_dispense_liters", 0) or 0) == 0
    )


def _adopt_opening(target: Any, liters: float) -> None:
    if target.opening_liters is None or _gauge_is_the_book(target):
        target.opening_liters = liters


def _remember_capacity(target: Any, capacity_liters: float | None) -> None:
    if capacity_liters is None or capacity_liters <= 0:
        return
    if getattr(target, "capacity_liters", None) in (None, 0):
        target.capacity_liters = capacity_liters


def _set_sensor_watch(target: Any, liters: float, at: datetime) -> None:
    target.sensor_watch_liters = liters
    target.sensor_watch_at = as_utc(at)
    target.sensor_watch_receipts = float(getattr(target, "receipts_liters", 0) or 0)
    target.sensor_watch_dispense = float(getattr(target, "dispense_liters", 0) or 0)


def _clear_sensor_watch(target: Any) -> None:
    target.sensor_watch_liters = None
    target.sensor_watch_at = None
    target.sensor_watch_receipts = 0.0
    target.sensor_watch_dispense = 0.0
    target.pending_sensor_alert = None


def _arm_sensor_watch(target: Any, at: datetime | None) -> None:
    """Старт окна на текущем замере, до того как в книгу попадёт новая приёмка или отпуск."""
    if getattr(target, "sensor_watch_liters", None) is not None:
        return
    actual = getattr(target, "actual_remainder_liters", None)
    if actual is None:
        return
    _set_sensor_watch(target, float(actual), at or datetime.now(timezone.utc))


def observe_sensor_watch(
    target: Any,
    *,
    liters: float,
    recorded_at: datetime,
    capacity_liters: float | None,
) -> SensorAlert | None:
    """Сдвигает окно наблюдения и возвращает сигнал, если движение датчика не объяснено книгой."""
    recorded_at = as_utc(recorded_at)
    mark_liters = getattr(target, "sensor_watch_liters", None)
    mark_at = getattr(target, "sensor_watch_at", None)
    if mark_liters is None or mark_at is None:
        _set_sensor_watch(target, liters, recorded_at)
        target.pending_sensor_alert = None
        return None

    elapsed = recorded_at - as_utc(mark_at)
    if elapsed.total_seconds() < 0:
        elapsed = timedelta(0)
    if elapsed > SENSOR_WATCH_GAP:
        _set_sensor_watch(target, liters, recorded_at)
        target.pending_sensor_alert = None
        return None

    receipts_since = float(getattr(target, "receipts_liters", 0) or 0) - float(
        getattr(target, "sensor_watch_receipts", 0) or 0
    )
    dispense_since = float(getattr(target, "dispense_liters", 0) or 0) - float(
        getattr(target, "sensor_watch_dispense", 0) or 0
    )
    alert = classify_sensor_watch(
        previous_liters=float(mark_liters),
        current_liters=liters,
        elapsed=elapsed,
        receipts_liters=receipts_since,
        dispense_liters=dispense_since,
        capacity_liters=capacity_liters,
    )
    if alert is not None or elapsed >= SENSOR_WATCH_SLIDE:
        _set_sensor_watch(target, liters, recorded_at)
    target.pending_sensor_alert = alert
    return alert


def take_sensor_alert(target: Any) -> SensorAlert | None:
    alert = getattr(target, "pending_sensor_alert", None)
    target.pending_sensor_alert = None
    return alert


def apply_level_reading(
    target: Any,
    body: LevelReadingInput,
    calibration: LevelCalibration | None,
    *,
    capacity_liters: float | None = None,
    heard_at: datetime,
    recorded_at: datetime | None = None,
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
        _remember_capacity(target, effective_capacity)
        _adopt_opening(target, liters)
        recompute_tank_book(target, capacity_liters=effective_capacity)
        if _gauge_is_the_book(target):
            _clear_sensor_watch(target)
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

    target.actual_remainder_liters = liters
    _remember_capacity(target, effective_capacity)
    _adopt_opening(target, liters)
    target.last_measured_at = heard_at
    recompute_tank_book(target, capacity_liters=effective_capacity)
    if _gauge_is_the_book(target):
        _clear_sensor_watch(target)
    else:
        observe_sensor_watch(
            target,
            liters=liters,
            recorded_at=recorded_at or heard_at,
            capacity_liters=effective_capacity,
        )
    return True, liters, fill


def apply_dispense_volume(target: Any, volume_liters: float, *, at: datetime | None = None) -> None:
    """Проводит отпуск по книге резервуара."""
    if target.opening_liters is None:
        target.pending_dispense_liters += volume_liters
    else:
        _arm_sensor_watch(target, at)
        target.dispense_liters += volume_liters
        recompute_tank_book(target)


def apply_receipt_volume(target: Any, volume_liters: float, *, at: datetime | None = None) -> None:
    """Проводит приёмку (слив газовоза) по книге резервуара."""
    if target.opening_liters is None:
        target.pending_receipt_liters += volume_liters
    else:
        _arm_sensor_watch(target, at)
        target.receipts_liters += volume_liters
        recompute_tank_book(target)


def summarize_station_tanks(
    tanks: Sequence[TankSummaryInput],
) -> tuple[float | None, float | None, float | None, str]:
    """Считает суммарный остаток, ёмкость, дельту и статус ориентира по всем бакам станции."""
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
    booked_capacity = sum(
        t.capacity_liters
        for t in tanks
        if t.calculated_remainder_liters is not None and t.actual_remainder_liters is not None
    )
    result = classify_discrepancy(
        total_calc,
        total_act_with_book,
        capacity_liters=booked_capacity,
    )
    return total_actual, total_capacity, result.delta_liters, result.status
