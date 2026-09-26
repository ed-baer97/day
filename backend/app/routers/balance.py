"""Balance reconciliation endpoints."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter

from app.schemas.balance import BalanceReconcileRequest, BalanceSnapshotOut, ConsumptionSummary
from app.schemas.event import DiscrepancyEventOut
from app.services.balance import calculate_remainder, classify_discrepancy

router = APIRouter(prefix="/balance", tags=["balance"])

_SNAPSHOTS: list[dict] = []
_EVENTS: list[dict] = []


@router.post("/reconcile", response_model=BalanceSnapshotOut)
def reconcile(body: BalanceReconcileRequest) -> BalanceSnapshotOut:
    calculated = calculate_remainder(
        body.previous_remainder_liters, body.receipts_liters, body.dispense_liters
    )
    result = classify_discrepancy(calculated, body.actual_remainder_liters)
    now = datetime.now(timezone.utc)
    snapshot = {
        "id": uuid4(),
        "station_id": body.station_id,
        "tank_id": body.tank_id,
        "period_start": body.period_start,
        "period_end": body.period_end,
        "previous_remainder_liters": body.previous_remainder_liters,
        "receipts_liters": body.receipts_liters,
        "dispense_liters": body.dispense_liters,
        "calculated_remainder_liters": result.calculated_remainder_liters,
        "actual_remainder_liters": body.actual_remainder_liters,
        "delta_liters": result.delta_liters,
        "status": result.status,
        "created_at": now,
    }
    _SNAPSHOTS.append(snapshot)

    if result.discrepancy_type is not None:
        _EVENTS.append(
            {
                "id": uuid4(),
                "station_id": body.station_id,
                "tank_id": body.tank_id,
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

    return BalanceSnapshotOut(**snapshot)


@router.get("/stations/{station_id}/snapshots", response_model=list[BalanceSnapshotOut])
def list_snapshots(station_id: str) -> list[BalanceSnapshotOut]:
    return [
        BalanceSnapshotOut(**s)
        for s in _SNAPSHOTS
        if str(s["station_id"]) == station_id
    ]


@router.get("/stations/{station_id}/consumption", response_model=ConsumptionSummary)
def consumption_summary(station_id: str) -> ConsumptionSummary:
    from uuid import UUID

    return ConsumptionSummary(
        station_id=UUID(station_id),
        day_liters=3100,
        week_liters=21400,
        month_liters=86500,
        sales_day_count=142,
        movement_history=[
            {"kind": "receipt", "volume_liters": 8200, "at": datetime.now(timezone.utc).isoformat()},
            {"kind": "dispense", "volume_liters": 45.2, "at": datetime.now(timezone.utc).isoformat()},
        ],
    )


def get_generated_events() -> list[dict]:
    return _EVENTS
