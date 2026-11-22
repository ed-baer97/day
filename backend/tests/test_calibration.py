"""Калибровка Холла без сети и без Shelly."""

import pytest

from app.services.calibration import (
    LevelCalibration,
    round_percent,
    round_volts,
    level_volts_changed,
    same_published_level,
    volts_to_liters,
    volts_to_percent,
)

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


def test_empty_volts_are_zero_percent_and_the_top_stays_at_ninety_five():
    assert volts_to_percent(0.0, CAL) == pytest.approx(0)
    assert volts_to_liters(0.0, CAL) == pytest.approx(0)
    assert volts_to_percent(10.0, CAL) == pytest.approx(95)
    assert volts_to_liters(10.0, CAL) == pytest.approx(9_500)


def test_zero_volts_on_the_empty_point_stay_empty():
    empty = LevelCalibration(21_000, 0.0, 0.0, 3.44, 72.95)
    assert volts_to_percent(0.0, empty) == pytest.approx(0)
    assert volts_to_liters(0.0, empty) == pytest.approx(0)


def test_volts_round_to_tenth():
    assert round_volts(3.19) == pytest.approx(3.2)
    assert round_volts(3.14) == pytest.approx(3.1)
    assert round_volts(3.15) == pytest.approx(3.2)


def test_hundredth_of_a_volt_is_noise_and_two_hundredths_are_a_change():
    assert not level_volts_changed(3.15, 3.16)
    assert level_volts_changed(3.14, 3.16)
    assert same_published_level(3.15, 3.16, 65, 66)
    assert not same_published_level(3.14, 3.16, 65, 65)


def test_percent_rounds_to_one():
    assert round_percent(65.4) == 65
    assert round_percent(65.5) == 66
    assert round_percent(64.769) == 65


def test_same_volts_rejected():
    flat = LevelCalibration(10_000, 1, 0, 1, 100)
    with pytest.raises(ValueError):
        volts_to_percent(1, flat)
