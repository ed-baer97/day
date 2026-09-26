"""Digital trail helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.models.batch import TrailNodeType


TRAIL_CHAIN = [
    TrailNodeType.supplier,
    TrailNodeType.factory,
    TrailNodeType.batch,
    TrailNodeType.truck,
    TrailNodeType.route,
    TrailNodeType.station,
    TrailNodeType.tank,
    TrailNodeType.dispense,
    TrailNodeType.sale,
]


def trail_chain_labels() -> list[str]:
    return [n.value for n in TRAIL_CHAIN]


def make_trail_event_payload(
    *,
    node_type: TrailNodeType,
    title: str,
    description: str | None = None,
    ref_entity_type: str | None = None,
    ref_entity_id: UUID | None = None,
    volume_liters: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    occurred_at: datetime | None = None,
) -> dict:
    return {
        "node_type": node_type,
        "title": title,
        "description": description,
        "ref_entity_type": ref_entity_type,
        "ref_entity_id": ref_entity_id,
        "volume_liters": volume_liters,
        "lat": lat,
        "lon": lon,
        "occurred_at": occurred_at or datetime.now(timezone.utc),
    }
