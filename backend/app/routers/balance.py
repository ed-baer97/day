"""Balance reconciliation endpoints."""

from uuid import UUID

from fastapi import APIRouter

from app.schemas.balance import BalanceReconcileRequest, BalanceSnapshotOut, ConsumptionSummary
from app.services.balance_log import demo_consumption, record_reconcile, snapshots_for

router = APIRouter(prefix="/balance", tags=["balance"])


@router.post("/reconcile", response_model=BalanceSnapshotOut)
def reconcile(body: BalanceReconcileRequest) -> BalanceSnapshotOut:
    snapshot = record_reconcile(
        station_id=body.station_id,
        tank_id=body.tank_id,
        period_start=body.period_start,
        period_end=body.period_end,
        previous_remainder_liters=body.previous_remainder_liters,
        receipts_liters=body.receipts_liters,
        dispense_liters=body.dispense_liters,
        actual_remainder_liters=body.actual_remainder_liters,
    )
    return BalanceSnapshotOut(**snapshot)


@router.get("/stations/{station_id}/snapshots", response_model=list[BalanceSnapshotOut])
def list_snapshots(station_id: str) -> list[BalanceSnapshotOut]:
    return [BalanceSnapshotOut(**row) for row in snapshots_for(station_id)]


@router.get("/stations/{station_id}/consumption", response_model=ConsumptionSummary)
def consumption_summary(station_id: str) -> ConsumptionSummary:
    return ConsumptionSummary(**demo_consumption(UUID(station_id)))
