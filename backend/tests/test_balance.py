"""Unit tests for balance reconciliation (no DB required)."""

from app.models.event import DiscrepancyType
from app.services.balance import calculate_remainder, classify_discrepancy


def test_calculate_remainder():
    assert calculate_remainder(10000, 5000, 3000) == 12000


def test_ok_within_tolerance():
    r = classify_discrepancy(10000, 10030, tolerance=50)
    assert r.status == "ok"
    assert r.discrepancy_type is None


def test_shortage():
    r = classify_discrepancy(10000, 9700, tolerance=50, measurement_band=150)
    assert r.status == "shortage"
    assert r.discrepancy_type == DiscrepancyType.shortage


def test_surplus():
    r = classify_discrepancy(10000, 10300, tolerance=50, measurement_band=150)
    assert r.status == "surplus"
    assert r.discrepancy_type == DiscrepancyType.surplus


def test_measurement_error_band():
    r = classify_discrepancy(10000, 9910, tolerance=50, measurement_band=150)
    assert r.status == "measurement_error"
    assert r.discrepancy_type == DiscrepancyType.measurement_error
