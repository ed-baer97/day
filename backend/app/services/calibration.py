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


# До 0,1 В журнал не считает сменой остатка: шум 0,01 В иначе прыгает через границу процента.
LEVEL_NOISE_VOLTS = 0.1


def same_published_level(
    previous_volts: float | None,
    volts: float | None,
    previous_percent: float | None,
    percent: float | None,
    tolerance: float = LEVEL_NOISE_VOLTS,
) -> bool:
    """Сдвиг меньше tolerance — погрешность датчика, не новая строка журнала."""

    if volts is not None and previous_volts is not None:
        return abs(volts - previous_volts) <= tolerance + 1e-9
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
