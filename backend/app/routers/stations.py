"""Station endpoints."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from app.schemas.station import StationDetailOut, StationOut, TankOut

router = APIRouter(prefix="/stations", tags=["stations"])

# In-memory demo fixtures until DB wiring (MVP-1)
_DEMO_STATIONS: list[dict] = [
    {
        "id": UUID("a1111111-1111-1111-1111-111111111101"),
        "code": "AGZS-MSK-01",
        "name": "АГЗС Север",
        "address": "Москва, Дмитровское ш.",
        "lat": 55.8701,
        "lon": 37.5450,
        "is_active": True,
        "tanks": [
            {
                "id": UUID("b1111111-1111-1111-1111-111111111101"),
                "code": "R-1",
                "capacity_liters": 25000,
                "has_electronic_sensor": True,
                "actual_remainder_liters": 14200,
                "calculated_remainder_liters": 14350,
                "level_source": "electronic",
                "last_measured_at": datetime.now(timezone.utc),
            }
        ],
    },
    {
        "id": UUID("a1111111-1111-1111-1111-111111111102"),
        "code": "AGZS-MSK-02",
        "name": "АГЗС Юг",
        "address": "Москва, Варшавское ш.",
        "lat": 55.6200,
        "lon": 37.6200,
        "is_active": True,
        "tanks": [
            {
                "id": UUID("b1111111-1111-1111-1111-111111111102"),
                "code": "R-1",
                "capacity_liters": 20000,
                "has_electronic_sensor": False,
                "actual_remainder_liters": 9800,
                "calculated_remainder_liters": 9800,
                "level_source": "manual",
                "last_measured_at": datetime.now(timezone.utc),
            }
        ],
    },
]


@router.get("", response_model=list[StationOut])
def list_stations() -> list[StationOut]:
    return [StationOut(**{k: v for k, v in s.items() if k != "tanks"}) for s in _DEMO_STATIONS]


@router.get("/{station_id}", response_model=StationDetailOut)
def get_station(station_id: UUID) -> StationDetailOut:
    for s in _DEMO_STATIONS:
        if s["id"] == station_id:
            tanks = [TankOut(**t) for t in s["tanks"]]
            capacity = sum(t.capacity_liters for t in tanks)
            actual = sum(t.actual_remainder_liters or 0 for t in tanks)
            calculated = sum(t.calculated_remainder_liters or 0 for t in tanks)
            delta = actual - calculated
            status = "ok" if abs(delta) < 50 else ("shortage" if delta < 0 else "surplus")
            return StationDetailOut(
                **{k: v for k, v in s.items() if k != "tanks"},
                tanks=tanks,
                remainder_liters=actual,
                capacity_liters=capacity,
                receipts_day_liters=8200,
                consumption_day_liters=3100,
                consumption_week_liters=21400,
                consumption_month_liters=86500,
                sales_day_count=142,
                active_trucks=[{"plate": "А123ВС77", "status": "arrived"}],
                balance_status=status,
                calculated_vs_actual_delta=delta,
            )
    raise HTTPException(status_code=404, detail="Station not found")


@router.get("/{station_id}/tanks", response_model=list[TankOut])
def list_tanks(station_id: UUID) -> list[TankOut]:
    for s in _DEMO_STATIONS:
        if s["id"] == station_id:
            return [TankOut(**t) for t in s["tanks"]]
    raise HTTPException(status_code=404, detail="Station not found")
