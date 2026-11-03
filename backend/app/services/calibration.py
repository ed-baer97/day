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
    """Шаг 0,1 В: 3,19 → 3,2, 3,14 → 3,1. Мельче — погрешность, не изменение."""

    return float(Decimal(str(volts)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


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
