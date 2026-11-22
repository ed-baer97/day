"""Память сверки. Роутер только принимает запрос и отдаёт ответ."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.domain.balance import SensorAlert, as_utc, classify_sensor_watch
from app.domain.tank_book import take_sensor_alert
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
    alert = None
    if actual_remainder_liters is not None:
        elapsed = as_utc(period_end) - as_utc(period_start)
        if elapsed.total_seconds() < 0:
            elapsed = timedelta(0)
        alert = classify_sensor_watch(
            previous_liters=previous_remainder_liters,
            current_liters=actual_remainder_liters,
            elapsed=elapsed,
            receipts_liters=receipts_liters,
            dispense_liters=dispense_liters,
            capacity_liters=None,
        )
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

    if alert is not None:
        _append_event(
            station_id=station_id,
            tank_id=tank_id,
            balance_snapshot_id=snapshot["id"],
            alert=alert,
            detected_at=now,
        )
    return snapshot


def _append_event(
    *,
    station_id: UUID,
    tank_id: UUID,
    alert: SensorAlert,
    detected_at: datetime,
    balance_snapshot_id: UUID | None = None,
) -> None:
    if len(_EVENTS) >= _MAX_RECORDS:
        _EVENTS.pop(0)
    _EVENTS.append(
        {
            "id": uuid4(),
            "station_id": station_id,
            "tank_id": tank_id,
            "balance_snapshot_id": balance_snapshot_id,
            "event_type": alert.event_type.value,
            "severity": alert.severity.value,
            "delta_liters": alert.delta_liters,
            "title": alert.title,
            "description": alert.description,
            "is_resolved": False,
            "detected_at": detected_at,
            "resolved_at": None,
        }
    )


def publish_pending_sensor_alert(target: object, *, station_id: UUID, tank_id: UUID) -> None:
    alert = take_sensor_alert(target)
    if alert is None:
        return
    _append_event(
        station_id=station_id,
        tank_id=tank_id,
        alert=alert,
        detected_at=datetime.now(timezone.utc),
    )


def reset_generated_events() -> None:
    _EVENTS.clear()


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
