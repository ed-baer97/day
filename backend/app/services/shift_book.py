"""Хранилище кассовых смен АГЗС в памяти процесса."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.entities import ShiftColumnSummary, ShiftTankSnapshot, StationShift
from app.domain.errors import ConflictError, NotFoundError
from app.services.account_helpers import (
    clean_optional_text,
    dump_shift_columns,
    dump_shift_tanks,
    load_shift_columns,
    load_shift_tanks,
    parse_iso_utc,
)
from app.services.memory_state import persist, register_store

_lock = threading.Lock()
_shifts: dict[UUID, StationShift] = {}


def _copy_tank(item: ShiftTankSnapshot) -> ShiftTankSnapshot:
    return ShiftTankSnapshot(
        tank_id=item.tank_id,
        code=item.code,
        capacity_liters=item.capacity_liters,
        remainder_liters=item.remainder_liters,
        fill_percent=item.fill_percent,
        measured_at=item.measured_at,
    )


def _copy_column(item: ShiftColumnSummary) -> ShiftColumnSummary:
    return ShiftColumnSummary(
        pump_address=item.pump_address,
        code=item.code,
        name=item.name,
        volume_liters=item.volume_liters,
        ops_count=item.ops_count,
        amount_kzt=item.amount_kzt,
        last_liters=item.last_liters,
        last_at=item.last_at,
    )


def _copy_shift(shift: StationShift) -> StationShift:
    return StationShift(
        id=shift.id,
        station_id=shift.station_id,
        status=shift.status,
        opened_by=shift.opened_by,
        opened_at=shift.opened_at,
        closed_by=shift.closed_by,
        closed_at=shift.closed_at,
        opening_tank_liters=shift.opening_tank_liters,
        closing_tank_liters=shift.closing_tank_liters,
        opening_tanks=[_copy_tank(item) for item in shift.opening_tanks],
        closing_tanks=[_copy_tank(item) for item in shift.closing_tanks],
        receipts_liters=shift.receipts_liters,
        dispensed_liters=shift.dispensed_liters,
        dispense_count=shift.dispense_count,
        total_amount_kzt=shift.total_amount_kzt,
        columns=[_copy_column(item) for item in shift.columns],
        tank_delta_liters=shift.tank_delta_liters,
        discrepancy_liters=shift.discrepancy_liters,
        note=shift.note,
    )


def reset_shifts() -> None:
    with _lock:
        _shifts.clear()


def list_shifts(station_id: UUID, *, limit: int = 50) -> list[StationShift]:
    with _lock:
        rows = [_copy_shift(row) for row in _shifts.values() if row.station_id == station_id]
    rows.sort(key=lambda row: row.opened_at, reverse=True)
    return rows[: max(1, limit)]


def get_shift(station_id: UUID, shift_id: UUID) -> StationShift:
    with _lock:
        shift = _shifts.get(shift_id)
        if shift is None or shift.station_id != station_id:
            raise NotFoundError("смена не найдена")
        return _copy_shift(shift)


def get_open_shift(station_id: UUID) -> StationShift | None:
    with _lock:
        found = [
            row
            for row in _shifts.values()
            if row.station_id == station_id and row.status == "open"
        ]
        if not found:
            return None
        found.sort(key=lambda row: row.opened_at, reverse=True)
        return _copy_shift(found[0])


def open_shift(
    station_id: UUID,
    *,
    opened_by: str,
    opened_at: datetime,
    opening_tank_liters: float | None,
    opening_tanks: list[ShiftTankSnapshot],
    note: str | None = None,
) -> StationShift:
    cleaned_note = clean_optional_text(note)
    with _lock:
        if any(row.station_id == station_id and row.status == "open" for row in _shifts.values()):
            raise ConflictError("на этой АГЗС уже открыта смена")
        shift = StationShift(
            id=uuid4(),
            station_id=station_id,
            status="open",
            opened_by=opened_by,
            opened_at=opened_at,
            opening_tank_liters=opening_tank_liters,
            opening_tanks=[_copy_tank(item) for item in opening_tanks],
            note=cleaned_note,
        )
        _shifts[shift.id] = shift
        result = _copy_shift(shift)
    persist()
    return result


def close_shift(
    station_id: UUID,
    shift_id: UUID,
    *,
    closed_by: str,
    closed_at: datetime,
    closing_tank_liters: float | None,
    closing_tanks: list[ShiftTankSnapshot],
    receipts_liters: float,
    dispensed_liters: float,
    dispense_count: int,
    total_amount_kzt: float | None,
    columns: list[ShiftColumnSummary],
    tank_delta_liters: float | None,
    discrepancy_liters: float | None,
    note: str | None = None,
) -> StationShift:
    cleaned_note = clean_optional_text(note)
    with _lock:
        shift = _shifts.get(shift_id)
        if shift is None or shift.station_id != station_id:
            raise NotFoundError("смена не найдена")
        if shift.status != "open":
            raise ConflictError("смена уже закрыта")
        shift.status = "closed"
        shift.closed_by = closed_by
        shift.closed_at = closed_at
        shift.closing_tank_liters = closing_tank_liters
        shift.closing_tanks = [_copy_tank(item) for item in closing_tanks]
        shift.receipts_liters = receipts_liters
        shift.dispensed_liters = dispensed_liters
        shift.dispense_count = dispense_count
        shift.total_amount_kzt = total_amount_kzt
        shift.columns = [_copy_column(item) for item in columns]
        shift.tank_delta_liters = tank_delta_liters
        shift.discrepancy_liters = discrepancy_liters
        if cleaned_note is not None:
            shift.note = cleaned_note
        result = _copy_shift(shift)
    persist()
    return result


def delete_station_shifts(station_id: UUID) -> None:
    changed = False
    with _lock:
        to_remove = [sid for sid, row in _shifts.items() if row.station_id == station_id]
        for sid in to_remove:
            _shifts.pop(sid, None)
            changed = True
    if changed:
        persist()


def snapshot() -> list[dict]:
    with _lock:
        rows = sorted(_shifts.values(), key=lambda row: row.opened_at)
        return [
            {
                "id": str(row.id),
                "station_id": str(row.station_id),
                "status": row.status,
                "opened_by": row.opened_by,
                "closed_by": row.closed_by,
                "opened_at": row.opened_at.isoformat(),
                "closed_at": None if row.closed_at is None else row.closed_at.isoformat(),
                "opening_tank_liters": row.opening_tank_liters,
                "opening_tanks": json.loads(dump_shift_tanks(row.opening_tanks)),
                "closing_tank_liters": row.closing_tank_liters,
                "closing_tanks": json.loads(dump_shift_tanks(row.closing_tanks)),
                "receipts_liters": row.receipts_liters,
                "dispensed_liters": row.dispensed_liters,
                "dispense_count": row.dispense_count,
                "total_amount_kzt": row.total_amount_kzt,
                "columns": json.loads(dump_shift_columns(row.columns)),
                "tank_delta_liters": row.tank_delta_liters,
                "discrepancy_liters": row.discrepancy_liters,
                "note": row.note,
            }
            for row in rows
        ]


def restore_snapshot(rows: object) -> None:
    if not isinstance(rows, list):
        return
    restored: dict[UUID, StationShift] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        opened_at = parse_iso_utc(row.get("opened_at"))
        if opened_at is None:
            continue
        shift = StationShift(
            id=UUID(str(row["id"])),
            station_id=UUID(str(row["station_id"])),
            status=str(row.get("status") or "open"),
            opened_by=str(row.get("opened_by") or ""),
            closed_by=None if row.get("closed_by") is None else str(row["closed_by"]),
            opened_at=opened_at,
            closed_at=parse_iso_utc(row.get("closed_at")),
            opening_tank_liters=None
            if row.get("opening_tank_liters") is None
            else float(row["opening_tank_liters"]),
            opening_tanks=load_shift_tanks(row.get("opening_tanks")),
            closing_tank_liters=None
            if row.get("closing_tank_liters") is None
            else float(row["closing_tank_liters"]),
            closing_tanks=load_shift_tanks(row.get("closing_tanks")),
            receipts_liters=float(row.get("receipts_liters") or 0.0),
            dispensed_liters=float(row.get("dispensed_liters") or 0.0),
            dispense_count=int(row.get("dispense_count") or 0),
            total_amount_kzt=None
            if row.get("total_amount_kzt") is None
            else float(row["total_amount_kzt"]),
            columns=load_shift_columns(row.get("columns")),
            tank_delta_liters=None
            if row.get("tank_delta_liters") is None
            else float(row["tank_delta_liters"]),
            discrepancy_liters=None
            if row.get("discrepancy_liters") is None
            else float(row["discrepancy_liters"]),
            note=None if row.get("note") is None else str(row["note"]),
        )
        restored[shift.id] = shift
    with _lock:
        _shifts.clear()
        _shifts.update(restored)


register_store("shifts", snapshot, restore_snapshot)

__all__ = [
    "close_shift",
    "delete_station_shifts",
    "get_open_shift",
    "get_shift",
    "list_shifts",
    "open_shift",
    "reset_shifts",
    "restore_snapshot",
    "snapshot",
]
