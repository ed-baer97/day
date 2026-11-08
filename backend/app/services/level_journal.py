"""Журнал замеров: какая строка — смена уровня, а какая — шум.

Порог вольт и литров один и тот же, что у приёма Shelly: level_policy.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.policy import LITER_NOISE
from app.services.calibration import round_percent, same_published_level


class ReadingRow(Protocol):
    id: UUID
    tank_id: UUID
    volts: float | None
    remainder_liters: float
    fill_percent: float | None
    recorded_at: datetime


@dataclass(frozen=True)
class PublishedLevel:
    id: UUID
    tank_id: UUID
    volts: float | None
    remainder_liters: float
    fill_percent: float | None
    recorded_at: datetime
    delta_liters: float | None


def published_levels(rows: list[ReadingRow], *, changes_only: bool) -> list[PublishedLevel]:
    """Строки от старых к новым. На выходе — от новых к старым, как в кабинете."""

    out: list[PublishedLevel] = []
    previous: float | None = None
    previous_volts: float | None = None
    previous_step: float | None = None
    for row in rows:
        volts = None if row.volts is None else float(row.volts)
        step = None if row.fill_percent is None else float(row.fill_percent)
        liters = float(row.remainder_liters)
        delta = None if previous is None else liters - previous
        if changes_only and previous is not None and same_published_level(previous_volts, volts, previous_step, step):
            continue
        if changes_only and previous is not None and volts is None and step is None and abs(delta) < LITER_NOISE:
            continue
        out.append(
            PublishedLevel(
                id=row.id,
                tank_id=row.tank_id,
                volts=volts,
                remainder_liters=liters,
                fill_percent=None if step is None else float(round_percent(step)),
                recorded_at=row.recorded_at,
                delta_liters=delta,
            )
        )
        previous = liters
        previous_volts = volts
        previous_step = step
    out.reverse()
    return out
