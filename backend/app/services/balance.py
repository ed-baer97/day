"""Сервисная обёртка сверки. Пороги датчика живут в app.domain.balance."""

from __future__ import annotations

from app.domain.balance import (
    DiscrepancySeverity,
    DiscrepancyType,
    ReconcileResult,
    SensorAlert,
    calculate_remainder,
    classify_discrepancy as _domain_classify_discrepancy,
    classify_sensor_watch as _domain_classify_sensor_watch,
)


def classify_discrepancy(
    calculated: float,
    actual: float | None,
    *,
    capacity_liters: float | None = None,
) -> ReconcileResult:
    return _domain_classify_discrepancy(
        calculated,
        actual,
        capacity_liters=capacity_liters,
    )


def classify_sensor_watch(**kwargs):
    return _domain_classify_sensor_watch(**kwargs)


__all__ = [
    "DiscrepancySeverity",
    "DiscrepancyType",
    "ReconcileResult",
    "SensorAlert",
    "calculate_remainder",
    "classify_discrepancy",
    "classify_sensor_watch",
]
