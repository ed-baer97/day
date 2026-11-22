"""Книжный остаток ведёт колонка. Датчик резервуара — ориентир с полосой."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Полоса ориентира: погрешность Холла и температурный ход СУГ.
SENSOR_BAND_FLOOR_LITERS = 100.0
SENSOR_BAND_CAPACITY_FRACTION = 0.02
# Уход мимо колонки: крупнее суточного хода температуры.
UNMETERED_DROP_FLOOR_LITERS = 300.0
UNMETERED_DROP_CAPACITY_FRACTION = 0.03
UNREGISTERED_RISE_LITERS = 1000.0
DISPENSE_NEAR_ZERO_LITERS = 20.0
UNMETERED_WINDOW = timedelta(hours=3)
SENSOR_WATCH_SLIDE = timedelta(hours=4)
# Дыра в телеметрии длиннее окна: новое окно без оценки пропущенного промежутка.
SENSOR_WATCH_GAP = timedelta(hours=6)

# Старые имена. Сверка больше не режет недостачу по фиксированным 50/150 л.
DEFAULT_BALANCE_TOLERANCE_LITERS = SENSOR_BAND_FLOOR_LITERS
DEFAULT_MEASUREMENT_ERROR_BAND_LITERS = SENSOR_BAND_FLOOR_LITERS


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


@dataclass(frozen=True)
class SensorAlert:
    event_type: DiscrepancyType
    severity: DiscrepancySeverity
    delta_liters: float
    title: str
    description: str


def sensor_band_liters(capacity_liters: float | None) -> float:
    """Полоса, внутри которой датчик не спорит с книгой: max(100 л, 2% ёмкости)."""
    if capacity_liters is None or capacity_liters <= 0:
        return SENSOR_BAND_FLOOR_LITERS
    return max(SENSOR_BAND_FLOOR_LITERS, capacity_liters * SENSOR_BAND_CAPACITY_FRACTION)


def unmetered_drop_liters(capacity_liters: float | None) -> float:
    """Порог ухода без колонки: max(300 л, 3% ёмкости)."""
    if capacity_liters is None or capacity_liters <= 0:
        return UNMETERED_DROP_FLOOR_LITERS
    return max(UNMETERED_DROP_FLOOR_LITERS, capacity_liters * UNMETERED_DROP_CAPACITY_FRACTION)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_remainder(previous: float, receipts: float, dispense: float) -> float:
    """остаток = предыдущий + приёмки − отпуски колонок"""
    return previous + receipts - dispense


def classify_discrepancy(
    calculated: float,
    actual: float | None,
    *,
    capacity_liters: float | None = None,
) -> ReconcileResult:
    """Сравнивает книгу с датчиком. Не открывает недостачу и излишек.

    Внутри полосы статус ok. Дальше полосы — outside_band, без инцидента:
    продажа уже учтена колонкой, датчик только ориентир.
    """
    if actual is None:
        return ReconcileResult(
            calculated_remainder_liters=calculated,
            delta_liters=None,
            status="unknown",
            discrepancy_type=None,
            severity=DiscrepancySeverity.info,
            title=None,
            description="Датчик недоступен",
        )

    band = sensor_band_liters(capacity_liters)
    delta = actual - calculated
    abs_delta = abs(delta)
    if abs_delta <= band:
        return ReconcileResult(
            calculated_remainder_liters=calculated,
            delta_liters=delta,
            status="ok",
            discrepancy_type=None,
            severity=DiscrepancySeverity.info,
            title=None,
            description=f"В полосе датчика ±{band:.0f} л",
        )

    return ReconcileResult(
        calculated_remainder_liters=calculated,
        delta_liters=delta,
        status="outside_band",
        discrepancy_type=None,
        severity=DiscrepancySeverity.info,
        title="Датчик вне полосы",
        description=(
            f"Датчик отошёл от книжного остатка на {delta:.0f} л. "
            f"Полоса ±{band:.0f} л. Продажа считается по колонкам."
        ),
    )


def classify_sensor_watch(
    *,
    previous_liters: float,
    current_liters: float,
    elapsed: timedelta,
    receipts_liters: float,
    dispense_liters: float,
    capacity_liters: float | None,
) -> SensorAlert | None:
    """Два сигнала крупнее шума датчика и температуры.

    Рост на тысячи литров без прихода — слив без документа.
    Падение больше порога за 3 часа при почти нулевых наливах — уход без колонки.
    """
    unexplained = (current_liters - previous_liters) - receipts_liters + dispense_liters
    if unexplained >= UNREGISTERED_RISE_LITERS:
        return SensorAlert(
            event_type=DiscrepancyType.unregistered_receipt,
            severity=DiscrepancySeverity.warning,
            delta_liters=round(unexplained, 3),
            title="Слив без документа",
            description=f"Датчик вырос на {unexplained:.0f} л без прихода в книге",
        )

    drop = -unexplained
    if (
        elapsed >= UNMETERED_WINDOW
        and dispense_liters <= DISPENSE_NEAR_ZERO_LITERS
        and drop >= unmetered_drop_liters(capacity_liters)
    ):
        return SensorAlert(
            event_type=DiscrepancyType.unregistered_dispense,
            severity=DiscrepancySeverity.warning,
            delta_liters=round(-drop, 3),
            title="Уход без колонки",
            description=(
                f"За {elapsed.total_seconds() / 3600:.1f} ч датчик упал на {drop:.0f} л, "
                "наливов почти не было"
            ),
        )
    return None
