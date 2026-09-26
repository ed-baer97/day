"""Pydantic schemas package."""

from app.schemas.balance import BalanceReconcileRequest, BalanceSnapshotOut, ConsumptionSummary
from app.schemas.batch import BatchCreate, BatchOut, BatchTrailEventOut, BatchTrailOut
from app.schemas.common import HealthOut, MapOverviewOut, MapPoint
from app.schemas.event import DiscrepancyEventOut, DiscrepancyResolveRequest
from app.schemas.ingest import (
    DispenseIngest,
    GpsIngest,
    LevelIngest,
    IngestAck,
)
from app.schemas.station import StationDetailOut, StationOut, TankOut
from app.schemas.truck import TruckDetailOut, TruckOut, TruckTripOut

__all__ = [
    "HealthOut",
    "MapOverviewOut",
    "MapPoint",
    "StationOut",
    "StationDetailOut",
    "TankOut",
    "TruckOut",
    "TruckDetailOut",
    "TruckTripOut",
    "BatchCreate",
    "BatchOut",
    "BatchTrailEventOut",
    "BatchTrailOut",
    "BalanceSnapshotOut",
    "BalanceReconcileRequest",
    "ConsumptionSummary",
    "DiscrepancyEventOut",
    "DiscrepancyResolveRequest",
    "GpsIngest",
    "LevelIngest",
    "DispenseIngest",
    "IngestAck",
]
