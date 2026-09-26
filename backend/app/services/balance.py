"""Balance reconciliation service."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.models.event import DiscrepancyType, DiscrepancySeverity


@dataclass
class ReconcileResult:
    calculated_remainder_liters: float
    delta_liters: float | None
    status: str
    discrepancy_type: DiscrepancyType | None
    severity: DiscrepancySeverity
    title: str | None
    description: str | None


def calculate_remainder(previous: float, receipts: float, dispense: float) -> float:
    """остаток = предыдущий + приёмки − отпуски"""
    return previous + receipts - dispense


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

    if actual is None:
        return ReconcileResult(
            calculated_remainder_liters=calculated,
            delta_liters=None,
            status="unknown",
            discrepancy_type=None,
            severity=DiscrepancySeverity.info,
            title=None,
            description="Фактический уровень не передан",
        )

    delta = actual - calculated
    abs_delta = abs(delta)

    if abs_delta <= tol:
        return ReconcileResult(
            calculated_remainder_liters=calculated,
            delta_liters=delta,
            status="ok",
            discrepancy_type=None,
            severity=DiscrepancySeverity.info,
            title=None,
            description=None,
        )

    if abs_delta <= band:
        return ReconcileResult(
            calculated_remainder_liters=calculated,
            delta_liters=delta,
            status="measurement_error",
            discrepancy_type=DiscrepancyType.measurement_error,
            severity=DiscrepancySeverity.warning,
            title="Возможная ошибка измерения",
            description=f"Отклонение {delta:.1f} л в зоне допуска датчика",
        )

    if delta < 0:
        return ReconcileResult(
            calculated_remainder_liters=calculated,
            delta_liters=delta,
            status="shortage",
            discrepancy_type=DiscrepancyType.shortage,
            severity=DiscrepancySeverity.critical,
            title="Недостача",
            description=f"Факт ниже расчёта на {abs_delta:.1f} л",
        )

    return ReconcileResult(
        calculated_remainder_liters=calculated,
        delta_liters=delta,
        status="surplus",
        discrepancy_type=DiscrepancyType.surplus,
        severity=DiscrepancySeverity.critical,
        title="Излишек",
        description=f"Факт выше расчёта на {abs_delta:.1f} л",
    )
