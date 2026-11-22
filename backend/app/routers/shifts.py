"""Роутер кассовых смен АГЗС (/api/v1/stations/{station_id}/shifts)."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth import Principal, require_principal, require_station_cashier
from app.domain.entities import StationCard, StationShift
from app.routers.deps import require_existing_station_access
from app.schemas.shift import (
    ShiftCloseIn,
    ShiftColumnSummaryOut,
    ShiftDetailOut,
    ShiftOpenIn,
    ShiftOut,
    ShiftTankSnapshotOut,
)
from app.schemas.station import DispenseReadingOut
from app.services.account import (
    close_station_shift,
    get_current_station_shift,
    get_station,
    get_station_shift_detail,
    list_station_shifts,
    open_station_shift,
)

router = APIRouter(prefix="/stations/{station_id}/shifts", tags=["shifts"])


def _shift_to_out(shift: StationShift, station: StationCard) -> ShiftOut:
    return ShiftOut(
        id=shift.id,
        station_id=shift.station_id,
        station_name=station.name,
        station_code=station.code,
        status=shift.status,
        opened_by=shift.opened_by,
        closed_by=shift.closed_by,
        opened_at=shift.opened_at.isoformat(),
        closed_at=None if shift.closed_at is None else shift.closed_at.isoformat(),
        opening_tank_liters=shift.opening_tank_liters,
        closing_tank_liters=shift.closing_tank_liters,
        opening_tanks=[
            ShiftTankSnapshotOut(
                tank_id=item.tank_id,
                code=item.code,
                capacity_liters=item.capacity_liters,
                remainder_liters=item.remainder_liters,
                fill_percent=item.fill_percent,
                measured_at=None if item.measured_at is None else item.measured_at.isoformat(),
            )
            for item in shift.opening_tanks
        ],
        closing_tanks=[
            ShiftTankSnapshotOut(
                tank_id=item.tank_id,
                code=item.code,
                capacity_liters=item.capacity_liters,
                remainder_liters=item.remainder_liters,
                fill_percent=item.fill_percent,
                measured_at=None if item.measured_at is None else item.measured_at.isoformat(),
            )
            for item in shift.closing_tanks
        ],
        receipts_liters=shift.receipts_liters,
        dispensed_liters=shift.dispensed_liters,
        dispense_count=shift.dispense_count,
        total_amount_kzt=shift.total_amount_kzt,
        columns=[
            ShiftColumnSummaryOut(
                pump_address=col.pump_address,
                code=col.code,
                name=col.name,
                volume_liters=col.volume_liters,
                ops_count=col.ops_count,
                amount_kzt=col.amount_kzt,
                last_liters=col.last_liters,
                last_at=None if col.last_at is None else col.last_at.isoformat(),
            )
            for col in shift.columns
        ],
        tank_delta_liters=shift.tank_delta_liters,
        discrepancy_liters=shift.discrepancy_liters,
        note=shift.note,
    )


def _shift_to_detail(
    shift: StationShift,
    dispenses: list[DispenseReadingOut],
    station: StationCard,
) -> ShiftDetailOut:
    return ShiftDetailOut(
        **_shift_to_out(shift, station).model_dump(),
        dispenses=dispenses,
    )


@router.get("", response_model=list[ShiftOut])
def list_shifts_endpoint(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
    limit: int = 50,
) -> list[ShiftOut]:
    station = require_existing_station_access(station_id, principal)
    capped = max(1, min(limit, 200))
    return [_shift_to_out(row, station) for row in list_station_shifts(station_id, limit=capped)]


@router.get("/current", response_model=ShiftDetailOut | None)
def get_current_shift_endpoint(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
) -> ShiftDetailOut | None:
    station = require_existing_station_access(station_id, principal)
    current = get_current_station_shift(station_id)
    if current is None:
        return None
    shift, dispenses = current
    return _shift_to_detail(shift, dispenses, station)


@router.post("/open", response_model=ShiftDetailOut, status_code=201)
def open_shift_endpoint(
    station_id: UUID,
    body: ShiftOpenIn | None = None,
    principal: Principal = Depends(require_principal),
) -> ShiftDetailOut:
    require_station_cashier(station_id, principal)
    station = get_station(station_id)
    shift, dispenses = open_station_shift(
        station_id,
        username=principal.username,
        note=None if body is None else body.note,
    )
    return _shift_to_detail(shift, dispenses, station)


@router.get("/{shift_id}", response_model=ShiftDetailOut)
def get_shift_detail_endpoint(
    station_id: UUID,
    shift_id: UUID,
    principal: Principal = Depends(require_principal),
) -> ShiftDetailOut:
    station = require_existing_station_access(station_id, principal)
    shift, dispenses = get_station_shift_detail(station_id, shift_id)
    return _shift_to_detail(shift, dispenses, station)


@router.post("/{shift_id}/close", response_model=ShiftDetailOut)
def close_shift_endpoint(
    station_id: UUID,
    shift_id: UUID,
    body: ShiftCloseIn | None = None,
    principal: Principal = Depends(require_principal),
) -> ShiftDetailOut:
    require_station_cashier(station_id, principal)
    station = get_station(station_id)
    shift, dispenses = close_station_shift(
        station_id,
        shift_id,
        username=principal.username,
        note=None if body is None else body.note,
    )
    return _shift_to_detail(shift, dispenses, station)
