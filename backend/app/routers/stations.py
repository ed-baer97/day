"""Station endpoints."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.schemas.station import StationDetailOut, StationOut, TankOut

router = APIRouter(prefix="/stations", tags=["stations"])

# In-memory demo fixtures — Мангистауская обл., отгрузка с КазГаз (Жанаозен)
_DEMO_STATIONS: list[dict] = [
    {
        "id": UUID("a1111111-1111-1111-1111-111111111101"),
        "code": "AGZS-AKT-12",
        "name": "АГЗС Актау · 12 мкр",
        "address": "Актау, 12 микрорайон",
        "lat": 43.6479,
        "lon": 51.2480,
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
        "code": "AGZS-ZHB-01",
        "name": "АГЗС Жетыбай",
        "address": "Жетыбай, Мангистауская обл.",
        "lat": 43.5920,
        "lon": 52.0780,
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
    {
        "id": UUID("a1111111-1111-1111-1111-111111111103"),
        "code": "AGZS-ZHO-01",
        "name": "АГЗС Жанаозен · центр",
        "address": "Жанаозен",
        "lat": 43.3427,
        "lon": 52.8431,
        "is_active": True,
        "tanks": [],
    },
    {
        "id": UUID("a1111111-1111-1111-1111-111111111104"),
        "code": "AGZS-KUR-01",
        "name": "АГЗС Курык",
        "address": "Курык",
        "lat": 43.1862,
        "lon": 51.6966,
        "is_active": True,
        "tanks": [],
    },
    {
        "id": UUID("a1111111-1111-1111-1111-111111111105"),
        "code": "AGZS-FSH-01",
        "name": "АГЗС Форт-Шевченко",
        "address": "Форт-Шевченко",
        "lat": 44.5244,
        "lon": 50.3254,
        "is_active": True,
        "tanks": [],
    },
    {
        "id": UUID("a1111111-1111-1111-1111-111111111106"),
        "code": "AGZS-AKT-28",
        "name": "АГЗС Актау · 28 мкр",
        "address": "Актау, 28 микрорайон",
        "lat": 43.6620,
        "lon": 51.2050,
        "is_active": True,
        "tanks": [],
    },
    {
        "id": UUID("a1111111-1111-1111-1111-111111111107"),
        "code": "AGZS-SHP-01",
        "name": "АГЗС Шетпе",
        "address": "Шетпе",
        "lat": 44.1385,
        "lon": 52.1640,
        "is_active": True,
        "tanks": [],
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
            capacity = sum(t.capacity_liters for t in tanks) or 15000
            actual = sum(t.actual_remainder_liters or 0 for t in tanks) or 5000
            calculated = sum(t.calculated_remainder_liters or 0 for t in tanks) or actual
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
                active_trucks=[{"plate": "705 ABA 12", "status": "arrived"}],
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
