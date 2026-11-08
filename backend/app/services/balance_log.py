"""Память сверки. Роутер только принимает запрос и отдаёт ответ."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.services.balance import calculate_remainder, classify_discrepancy

_MAX_RECORDS = 5000
_SNAPSHOTS: list[dict] = []
_EVENTS: list[dict] = []


def record_reconcile(
    *,
    station_id: UUID,
    tank_id: UUID,
    period_start: datetime,
    period_end: datetime,
    previous_remainder_liters: float,
    receipts_liters: float,
    dispense_liters: float,
    actual_remainder_liters: float | None,
) -> dict:
    calculated = calculate_remainder(previous_remainder_liters, receipts_liters, dispense_liters)
    result = classify_discrepancy(calculated, actual_remainder_liters)
    now = datetime.now(timezone.utc)
    snapshot = {
        "id": uuid4(),
        "station_id": station_id,
        "tank_id": tank_id,
        "period_start": period_start,
        "period_end": period_end,
        "previous_remainder_liters": previous_remainder_liters,
        "receipts_liters": receipts_liters,
        "dispense_liters": dispense_liters,
        "calculated_remainder_liters": result.calculated_remainder_liters,
        "actual_remainder_liters": actual_remainder_liters,
        "delta_liters": result.delta_liters,
        "status": result.status,
        "created_at": now,
    }
    if len(_SNAPSHOTS) >= _MAX_RECORDS:
        _SNAPSHOTS.pop(0)
    _SNAPSHOTS.append(snapshot)

    if result.discrepancy_type is not None:
        if len(_EVENTS) >= _MAX_RECORDS:
            _EVENTS.pop(0)
        _EVENTS.append(
            {
                "id": uuid4(),
                "station_id": station_id,
                "tank_id": tank_id,
                "balance_snapshot_id": snapshot["id"],
                "event_type": result.discrepancy_type.value,
                "severity": result.severity.value,
                "delta_liters": result.delta_liters,
                "title": result.title or result.discrepancy_type.value,
                "description": result.description,
                "is_resolved": False,
                "detected_at": now,
                "resolved_at": None,
            }
        )
    return snapshot


def snapshots_for(station_id: str) -> list[dict]:
    return [row for row in _SNAPSHOTS if str(row["station_id"]) == station_id]


def generated_events() -> list[dict]:
    return _EVENTS


def demo_consumption(station_id: UUID) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "station_id": station_id,
        "day_liters": 3100,
        "week_liters": 21400,
        "month_liters": 86500,
        "sales_day_count": 142,
        "movement_history": [
            {"kind": "receipt", "volume_liters": 8200, "at": now},
            {"kind": "dispense", "volume_liters": 45.2, "at": now},
        ],
    }
