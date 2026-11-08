"""Память партий. Цепочка подписей живёт в trail, хранение — здесь."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4


_BATCHES: dict[UUID, dict] = {}


def list_batches() -> list[dict]:
    return [_public(row) for row in _BATCHES.values()]


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
    batch_id = uuid4()
    now = datetime.now(timezone.utc)
    record = {
        "id": batch_id,
        "trail_code": trail_code,
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
        "events": [],
    }
    _BATCHES[batch_id] = record
    return _public(record)


def by_code(trail_code: str) -> dict | None:
    for row in _BATCHES.values():
        if row["trail_code"] == trail_code:
            return row
    return None


def by_id(batch_id: UUID) -> dict | None:
    return _BATCHES.get(batch_id)


def _public(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "events"}
