"""Перевод напряжения датчика Холла в литры.

Та же формула потом копируется в скрипт Shelly.
Две точки с циферблата задают прямую «вольты → проценты объёма».
Сам циферблат размечен от 5 % до 95 %: ниже и выше этих рисок стрелки нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


DIAL_MIN_PERCENT = 5.0
DIAL_MAX_PERCENT = 95.0


@dataclass(frozen=True)
class LevelCalibration:
    capacity_liters: float
    low_volts: float
    low_percent: float
    high_volts: float
    high_percent: float


def round_volts(volts: float) -> float:
    """Шаг 0,1 В: 3,19 → 3,2, 3,14 → 3,1."""

    return float(Decimal(str(volts)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_percent(percent: float) -> int:
    """Шаг 1 %: 65,4 → 65, 65,5 → 66. Мельче — погрешность, не изменение."""

    return int(Decimal(str(percent)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Шум датчика 0,01 В. Новая строка в базе — только после сдвига на 0,02 В от последнего записанного замера.
LEVEL_STEP_VOLTS = 0.02


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
