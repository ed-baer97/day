"""Перевод напряжения датчика Холла в литры.

Та же формула потом копируется в скрипт Shelly.
Две точки с циферблата задают прямую «вольты → проценты объёма».
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LevelCalibration:
    capacity_liters: float
    low_volts: float
    low_percent: float
    high_volts: float
    high_percent: float


def volts_to_percent(volts: float, calibration: LevelCalibration) -> float:
    span = calibration.high_volts - calibration.low_volts
    if span == 0:
        raise ValueError("точки калибровки совпадают по напряжению")
    return calibration.low_percent + (volts - calibration.low_volts) / span * (
        calibration.high_percent - calibration.low_percent
    )


def volts_to_liters(volts: float, calibration: LevelCalibration) -> float:
    return volts_to_percent(volts, calibration) / 100 * calibration.capacity_liters
