"""Память партий. Цепочка подписей живёт в trail, хранение и события — здесь."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.domain.errors import ConflictError, NotFoundError
from app.models.batch import TrailNodeType
from app.services.account_helpers import (
    batch_status_node_value,
    batch_status_title,
    parse_iso_utc,
)
from app.services.memory_state import persist, register_store
from app.services.trail import make_trail_event_payload

_lock = threading.Lock()
_BATCHES: dict[UUID, dict] = {}


def reset_batches() -> None:
    with _lock:
        _BATCHES.clear()


def list_batches() -> list[dict]:
    with _lock:
        rows = sorted(_BATCHES.values(), key=lambda row: row["created_at"], reverse=True)
        return [_public(row) for row in rows]


def create_batch(
    *,
    trail_code: str,
    supplier_id: UUID | None,
    factory_id: UUID | None,
    product_grade: str | None,
    density_kg_per_liter: float | None,
    volume_liters: float,
    mass_kg: float | None,
    notes: str | None,
) -> dict:
    cleaned_code = trail_code.strip()
    batch_id = uuid4()
    now = datetime.now(timezone.utc)
    init_event = make_trail_event_payload(
        node_type=TrailNodeType.batch,
        title=f"Зарегистрирована партия {cleaned_code}",
        description=notes or f"Марка: {product_grade or 'ПБТ'}",
        ref_entity_type="batch",
        ref_entity_id=batch_id,
        volume_liters=volume_liters,
        occurred_at=now,
    )
    init_event["id"] = uuid4()
    init_event["node_type"] = TrailNodeType.batch.value

    record = {
        "id": batch_id,
        "trail_code": cleaned_code,
        "supplier_id": supplier_id,
        "factory_id": factory_id,
        "product_grade": product_grade,
        "density_kg_per_liter": density_kg_per_liter,
        "volume_liters": volume_liters,
        "mass_kg": mass_kg,
        "status": "formed",
        "formed_at": now,
        "notes": notes,
        "created_at": now,
        "events": [init_event],
    }
    with _lock:
        if any(row["trail_code"].lower() == cleaned_code.lower() for row in _BATCHES.values()):
            raise ConflictError("партия с таким кодом уже зарегистрирована")
        _BATCHES[batch_id] = record
    persist()
    return _public(record)


def add_batch_event(
    batch_id: UUID,
    *,
    node_type: str,
    title: str,
    description: str | None = None,
    ref_entity_type: str | None = None,
    ref_entity_id: UUID | None = None,
    volume_liters: float | None = None,
    status: str | None = None,
) -> dict:
    node = TrailNodeType(node_type)
    now = datetime.now(timezone.utc)
    payload = make_trail_event_payload(
        node_type=node,
        title=title.strip(),
        description=description.strip() if description else None,
        ref_entity_type=ref_entity_type,
        ref_entity_id=ref_entity_id,
        volume_liters=volume_liters,
        occurred_at=now,
    )
    payload["id"] = uuid4()
    payload["node_type"] = node.value
    with _lock:
        record = _BATCHES.get(batch_id)
        if record is None:
            raise NotFoundError("Batch not found")
        record["events"].append(payload)
        if status is not None:
            record["status"] = status
        copy = _copy_record(record)
    persist()
    return copy


def update_batch_status(batch_id: UUID, status: str, note: str | None = None) -> dict:
    node = TrailNodeType(batch_status_node_value(status))
    now = datetime.now(timezone.utc)
    payload = make_trail_event_payload(
        node_type=node,
        title=batch_status_title(status),
        description=note.strip() if note else None,
        ref_entity_type="batch",
        ref_entity_id=batch_id,
        occurred_at=now,
    )
    payload["id"] = uuid4()
    payload["node_type"] = node.value
    with _lock:
        record = _BATCHES.get(batch_id)
        if record is None:
            raise NotFoundError("Batch not found")
        record["status"] = status
        record["events"].append(payload)
        out = _public(record)
    persist()
    return out


def by_code(trail_code: str) -> dict | None:
    cleaned = trail_code.strip().lower()
    with _lock:
        for row in _BATCHES.values():
            if row["trail_code"].lower() == cleaned:
                return _copy_record(row)
    return None


def by_id(batch_id: UUID) -> dict | None:
    with _lock:
        row = _BATCHES.get(batch_id)
        return None if row is None else _copy_record(row)


def _public(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "events"}


def _copy_record(row: dict) -> dict:
    return {
        **row,
        "events": [dict(ev) for ev in row.get("events", [])],
    }


def snapshot() -> list[dict]:
    with _lock:
        out: list[dict] = []
        for row in _BATCHES.values():
            out.append(
                {
                    "id": str(row["id"]),
                    "trail_code": row["trail_code"],
                    "supplier_id": None if row["supplier_id"] is None else str(row["supplier_id"]),
                    "factory_id": None if row["factory_id"] is None else str(row["factory_id"]),
                    "product_grade": row["product_grade"],
                    "density_kg_per_liter": row["density_kg_per_liter"],
                    "volume_liters": row["volume_liters"],
                    "mass_kg": row["mass_kg"],
                    "status": row["status"],
                    "formed_at": None if row["formed_at"] is None else row["formed_at"].isoformat(),
                    "notes": row["notes"],
                    "created_at": row["created_at"].isoformat(),
                    "events": [
                        {
                            "id": str(ev["id"]),
                            "node_type": str(ev["node_type"]),
                            "occurred_at": ev["occurred_at"].isoformat(),
                            "title": ev["title"],
                            "description": ev.get("description"),
                            "ref_entity_type": ev.get("ref_entity_type"),
                            "ref_entity_id": None
                            if ev.get("ref_entity_id") is None
                            else str(ev["ref_entity_id"]),
                            "volume_liters": ev.get("volume_liters"),
                            "lat": ev.get("lat"),
                            "lon": ev.get("lon"),
                        }
                        for ev in row.get("events", [])
                    ],
                }
            )
        return out


def restore_snapshot(rows: object) -> None:
    if not isinstance(rows, list):
        return
    restored: dict[UUID, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        batch_id = UUID(str(row["id"]))
        created_at = parse_iso_utc(row.get("created_at")) or datetime.now(timezone.utc)
        formed_at = parse_iso_utc(row.get("formed_at"))
        events = []
        for ev in row.get("events") or []:
            if not isinstance(ev, dict):
                continue
            events.append(
                {
                    "id": UUID(str(ev["id"])),
                    "node_type": str(ev["node_type"]),
                    "occurred_at": parse_iso_utc(ev.get("occurred_at")) or created_at,
                    "title": str(ev["title"]),
                    "description": ev.get("description"),
                    "ref_entity_type": ev.get("ref_entity_type"),
                    "ref_entity_id": None
                    if not ev.get("ref_entity_id")
                    else UUID(str(ev["ref_entity_id"])),
                    "volume_liters": ev.get("volume_liters"),
                    "lat": ev.get("lat"),
                    "lon": ev.get("lon"),
                }
            )
        restored[batch_id] = {
            "id": batch_id,
            "trail_code": str(row["trail_code"]),
            "supplier_id": None if not row.get("supplier_id") else UUID(str(row["supplier_id"])),
            "factory_id": None if not row.get("factory_id") else UUID(str(row["factory_id"])),
            "product_grade": row.get("product_grade"),
            "density_kg_per_liter": row.get("density_kg_per_liter"),
            "volume_liters": float(row["volume_liters"]),
            "mass_kg": row.get("mass_kg"),
            "status": str(row.get("status") or "formed"),
            "formed_at": formed_at,
            "notes": row.get("notes"),
            "created_at": created_at,
            "events": events,
        }
    with _lock:
        _BATCHES.clear()
        _BATCHES.update(restored)


register_store("batches", snapshot, restore_snapshot)
