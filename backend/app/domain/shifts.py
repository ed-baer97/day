"""Чистая доменная логика кассовой смены АГЗС и расчёта отчёта по колонкам и резервуарам."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities import ShiftColumnSummary

_MAX_COLUMNS = 8


@dataclass(frozen=True)
class ShiftDispenseSample:
    pump_address: int
    volume_liters: float
    price_kzt_per_liter: float | None
    occurred_at: datetime


def summarize_shift_columns(
    dispenses: list[ShiftDispenseSample],
    columns_count: int,
) -> tuple[list[ShiftColumnSummary], float, int, float | None]:
    """Агрегирует отпуски за смену по номерам колонок (ТРК-1..ТРК-N)."""
    max_addr = max((sample.pump_address for sample in dispenses if 1 <= sample.pump_address <= _MAX_COLUMNS), default=0)
    capped_config = max(0, min(_MAX_COLUMNS, int(columns_count)))
    active_count = max(capped_config, max_addr)
    if active_count == 0:
        return [], 0.0, 0, None

    buckets: dict[int, dict[str, object]] = {
        addr: {
            "volume": 0.0,
            "ops": 0,
            "amount": 0.0,
            "has_price": False,
            "last_liters": None,
            "last_at": None,
        }
        for addr in range(1, active_count + 1)
    }

    ordered = sorted(dispenses, key=lambda item: item.occurred_at)
    total_liters = 0.0
    total_ops = 0
    total_amount = 0.0
    any_price = False

    for sample in ordered:
        vol = float(sample.volume_liters)
        if vol <= 0:
            continue
        addr = sample.pump_address if 1 <= sample.pump_address <= active_count else 1
        bucket = buckets[addr]
        bucket["volume"] = float(bucket["volume"]) + vol
        bucket["ops"] = int(bucket["ops"]) + 1
        bucket["last_liters"] = round(vol, 3)
        bucket["last_at"] = sample.occurred_at

        total_liters += vol
        total_ops += 1

        if sample.price_kzt_per_liter is not None and sample.price_kzt_per_liter > 0:
            amount = vol * float(sample.price_kzt_per_liter)
            bucket["amount"] = float(bucket["amount"]) + amount
            bucket["has_price"] = True
            total_amount += amount
            any_price = True

    columns = [
        ShiftColumnSummary(
            pump_address=addr,
            code=f"ТРК-{addr}",
            name=f"Колонка {addr}",
            volume_liters=round(float(buckets[addr]["volume"]), 3),
            ops_count=int(buckets[addr]["ops"]),
            amount_kzt=round(float(buckets[addr]["amount"]), 2) if buckets[addr]["has_price"] else None,
            last_liters=buckets[addr]["last_liters"],  # type: ignore[arg-type]
            last_at=buckets[addr]["last_at"],  # type: ignore[arg-type]
        )
        for addr in range(1, active_count + 1)
    ]

    return (
        columns,
        round(total_liters, 3),
        total_ops,
        round(total_amount, 2) if any_price else None,
    )


def compute_shift_balance(
    opening_tank_liters: float | None,
    closing_tank_liters: float | None,
    receipts_liters: float,
    dispensed_liters: float,
) -> tuple[float | None, float | None]:
    """Возвращает (уход по цистерне, разница между ТРК и уходом по цистерне)."""
    if opening_tank_liters is None or closing_tank_liters is None:
        return None, None
    tank_delta = round(opening_tank_liters + receipts_liters - closing_tank_liters, 3)
    discrepancy = round(dispensed_liters - tank_delta, 3)
    return tank_delta, discrepancy
