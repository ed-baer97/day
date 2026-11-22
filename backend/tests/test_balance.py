"""Unit tests for balance reconciliation (no DB required)."""

from datetime import timedelta

from app.domain.balance import (
    DiscrepancyType,
    classify_discrepancy,
    classify_sensor_watch,
    sensor_band_liters,
)
from app.services.balance import calculate_remainder


def test_calculate_remainder():
    assert calculate_remainder(10000, 5000, 3000) == 12000


def test_band_is_two_percent_of_capacity_and_at_least_100():
    assert sensor_band_liters(None) == 100
    assert sensor_band_liters(2000) == 100
    assert sensor_band_liters(10000) == 200


def test_ok_inside_sensor_band():
    r = classify_discrepancy(10000, 10150, capacity_liters=10000)
    assert r.status == "ok"
    assert r.discrepancy_type is None
    assert r.delta_liters == 150


def test_outside_band_does_not_open_shortage():
    r = classify_discrepancy(10000, 9700, capacity_liters=10000)
    assert r.status == "outside_band"
    assert r.discrepancy_type is None
    assert "колонкам" in (r.description or "")


def test_missing_sensor_is_unknown():
    r = classify_discrepancy(10000, None, capacity_liters=10000)
    assert r.status == "unknown"
    assert r.delta_liters is None


def test_unregistered_rise_without_receipt():
    alert = classify_sensor_watch(
        previous_liters=4000,
        current_liters=9200,
        elapsed=timedelta(minutes=20),
        receipts_liters=0,
        dispense_liters=30,
        capacity_liters=10000,
    )
    assert alert is not None
    assert alert.event_type == DiscrepancyType.unregistered_receipt


def test_documented_receipt_is_not_an_unregistered_rise():
    alert = classify_sensor_watch(
        previous_liters=4000,
        current_liters=9000,
        elapsed=timedelta(minutes=40),
        receipts_liters=5000,
        dispense_liters=0,
        capacity_liters=10000,
    )
    assert alert is None


def test_unmetered_drop_needs_a_quiet_column_and_three_hours():
    quiet = classify_sensor_watch(
        previous_liters=8000,
        current_liters=7500,
        elapsed=timedelta(hours=4),
        receipts_liters=0,
        dispense_liters=0,
        capacity_liters=10000,
    )
    assert quiet is not None
    assert quiet.event_type == DiscrepancyType.unregistered_dispense

    explained_by_sales = classify_sensor_watch(
        previous_liters=8000,
        current_liters=7500,
        elapsed=timedelta(hours=4),
        receipts_liters=0,
        dispense_liters=480,
        capacity_liters=10000,
    )
    assert explained_by_sales is None

    too_soon = classify_sensor_watch(
        previous_liters=8000,
        current_liters=7500,
        elapsed=timedelta(hours=1),
        receipts_liters=0,
        dispense_liters=0,
        capacity_liters=10000,
    )
    assert too_soon is None
