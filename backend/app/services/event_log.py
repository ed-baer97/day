"""Журнал расхождений: демо-строка и события, которые породила сверка."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.services.balance_log import generated_events

_SEED: list[dict] = []


def all_events() -> list[dict]:
    return _SEED + generated_events()


def list_events(station_id: UUID | None = None, unresolved_only: bool = False) -> list[dict]:
    items = all_events()
    if station_id is not None:
        items = [row for row in items if row["station_id"] == station_id]
    if unresolved_only:
        items = [row for row in items if not row["is_resolved"]]
    return items


def get_event(event_id: UUID) -> dict | None:
    for row in all_events():
        if row["id"] == event_id:
            return row
    return None


def resolve_event(event_id: UUID, note: str | None) -> dict | None:
    row = get_event(event_id)
    if row is None:
        return None
    row["is_resolved"] = True
    row["resolved_at"] = datetime.now(timezone.utc)
    if note:
        row["description"] = (row.get("description") or "") + f" | resolved: {note}"
    return row
