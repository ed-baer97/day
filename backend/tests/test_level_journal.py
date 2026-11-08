"""Порог журнала совпадает с порогом приёма."""

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.policy import LITER_NOISE
from app.services.level_journal import published_levels


class _Row:
    def __init__(self, liters: float, volts: float | None, percent: float | None):
        self.id = uuid4()
        self.tank_id = uuid4()
        self.volts = volts
        self.remainder_liters = liters
        self.fill_percent = percent
        self.recorded_at = datetime.now(timezone.utc)


def test_half_noise_is_not_a_new_row():
    rows = published_levels(
        [_Row(1000, None, None), _Row(1000 + LITER_NOISE / 2, None, None)],
        changes_only=True,
    )
    assert len(rows) == 1
    assert rows[0].remainder_liters == 1000
