"""Сервисная обёртка сверки баланса (подставляет пороги из настроек, логика в app.domain.balance)."""

from __future__ import annotations

from app.config import get_settings
from app.domain.balance import (
    DiscrepancySeverity,
    DiscrepancyType,
    ReconcileResult,
    calculate_remainder,
    classify_discrepancy as _domain_classify_discrepancy,
)


def classify_discrepancy(
    calculated: float,
    actual: float | None,
    *,
    tolerance: float | None = None,
    measurement_band: float | None = None,
) -> ReconcileResult:
    settings = get_settings()
    tol = tolerance if tolerance is not None else settings.balance_tolerance_liters
    band = measurement_band if measurement_band is not None else settings.measurement_error_band_liters
    return _domain_classify_discrepancy(
        calculated,
        actual,
        tolerance=tol,
        measurement_band=band,
    )


__all__ = [
    "DiscrepancySeverity",
    "DiscrepancyType",
    "ReconcileResult",
    "calculate_remainder",
    "classify_discrepancy",
]
