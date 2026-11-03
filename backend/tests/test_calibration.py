"""Калибровка Холла без сети и без Shelly."""

import pytest

from app.services.calibration import LevelCalibration, round_volts, volts_to_liters, volts_to_percent

# 1.2 В = 20 %, 3.8 В = 80 %, сосуд 10 000 л
CAL = LevelCalibration(
    capacity_liters=10_000,
    low_volts=1.2,
    low_percent=20,
    high_volts=3.8,
    high_percent=80,
)


def test_midpoint_is_half_tank():
    assert volts_to_percent(2.5, CAL) == pytest.approx(50)
    assert volts_to_liters(2.5, CAL) == pytest.approx(5_000)


def test_endpoints_match_dial():
    assert volts_to_liters(1.2, CAL) == pytest.approx(2_000)
    assert volts_to_liters(3.8, CAL) == pytest.approx(8_000)


def test_dial_does_not_leave_five_to_ninety_five():
    assert volts_to_percent(0.0, CAL) == pytest.approx(5)
    assert volts_to_liters(0.0, CAL) == pytest.approx(500)
    assert volts_to_percent(10.0, CAL) == pytest.approx(95)
    assert volts_to_liters(10.0, CAL) == pytest.approx(9_500)


def test_volts_round_to_tenth():
    assert round_volts(3.19) == pytest.approx(3.2)
    assert round_volts(3.14) == pytest.approx(3.1)
    assert round_volts(3.15) == pytest.approx(3.2)


def test_same_volts_rejected():
    flat = LevelCalibration(10_000, 1, 0, 1, 100)
    with pytest.raises(ValueError):
        volts_to_percent(1, flat)
