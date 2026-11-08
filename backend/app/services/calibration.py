"""Перевод напряжения датчика Холла в литры.

Та же формула потом копируется в скрипт Shelly.
Две точки с циферблата задают прямую «вольты → проценты объёма».
Сам циферблат размечен от 5 % до 95 %: ниже и выше этих рисок стрелки нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.domain.policy import (
    DIAL_MAX_PERCENT,
    DIAL_MIN_PERCENT,
    LEVEL_STEP_VOLTS,
    PERCENT_QUANTUM,
    VOLT_QUANTUM,
)


@dataclass(frozen=True)
class LevelCalibration:
    capacity_liters: float
    low_volts: float
    low_percent: float
    high_volts: float
    high_percent: float


def round_volts(volts: float) -> float:
    """Шаг volt_quantum из level_policy.json: 3,19 → 3,2 при шаге 0,1."""

    return float(Decimal(str(volts)).quantize(VOLT_QUANTUM, rounding=ROUND_HALF_UP))


def round_percent(percent: float) -> int:
    """Шаг percent_quantum из level_policy.json. Мельче — погрешность, не изменение."""

    return int(Decimal(str(percent)).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP))


def remainder_fill_percent(remainder: float | None, capacity: float) -> float | None:
    """Процент витрины тем же округлением, что и журнал."""

    if remainder is None or capacity <= 0:
        return None
    return float(round_percent(remainder / capacity * 100))


def _millivolts(volts: float) -> int:
    return int((Decimal(str(volts)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def level_volts_changed(previous: float, current: float, step: float = LEVEL_STEP_VOLTS) -> bool:
    """True, когда напряжение ушло от последнего записанного замера не меньше чем на step."""

    return abs(_millivolts(current) - _millivolts(previous)) >= _millivolts(step)


def same_published_level(
    previous_volts: float | None,
    volts: float | None,
    previous_percent: float | None,
    percent: float | None,
) -> bool:
    """Та же ступень журнала: сдвиг меньше 0,02 В — шум, не новая строка."""

    if volts is not None and previous_volts is not None:
        return not level_volts_changed(previous_volts, volts)
    if percent is not None and previous_percent is not None:
        return round_percent(percent) == round_percent(previous_percent)
    return False


def volts_to_percent(volts: float, calibration: LevelCalibration) -> float:
    span = calibration.high_volts - calibration.low_volts
    if span == 0:
        raise ValueError("точки калибровки совпадают по напряжению")
    percent = calibration.low_percent + (volts - calibration.low_volts) / span * (
        calibration.high_percent - calibration.low_percent
    )
    if percent < DIAL_MIN_PERCENT:
        return DIAL_MIN_PERCENT
    if percent > DIAL_MAX_PERCENT:
        return DIAL_MAX_PERCENT
    return percent


def volts_to_liters(volts: float, calibration: LevelCalibration) -> float:
    return volts_to_percent(volts, calibration) / 100 * calibration.capacity_liters
