"""Чистый доменный расчёт книжного остатка и классификация расхождений."""

from __future__ import annotations

import enum
from dataclasses import dataclass

DEFAULT_BALANCE_TOLERANCE_LITERS = 50.0
DEFAULT_MEASUREMENT_ERROR_BAND_LITERS = 150.0


class DiscrepancyType(str, enum.Enum):
    shortage = "shortage"
    surplus = "surplus"
    measurement_error = "measurement_error"
    unregistered_receipt = "unregistered_receipt"
    unregistered_dispense = "unregistered_dispense"


class DiscrepancySeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


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
    tolerance: float = DEFAULT_BALANCE_TOLERANCE_LITERS,
    measurement_band: float = DEFAULT_MEASUREMENT_ERROR_BAND_LITERS,
) -> ReconcileResult:
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

    if abs_delta <= tolerance:
        return ReconcileResult(
            calculated_remainder_liters=calculated,
            delta_liters=delta,
            status="ok",
            discrepancy_type=None,
            severity=DiscrepancySeverity.info,
            title=None,
            description=None,
        )

    if abs_delta <= measurement_band:
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
