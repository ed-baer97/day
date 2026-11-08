"""Шкала и путь приёма читаются из одного места."""

import json

from app.config import Settings, get_settings
from app.domain.policy import (
    DIAL_MAX_PERCENT,
    DIAL_MIN_PERCENT,
    LEVEL_STEP_VOLTS,
    LITER_NOISE,
    POLICY_PATH,
    POLL_SECONDS,
    SENSOR_STALE_SECONDS,
)
from app.services.calibration import LEVEL_STEP_VOLTS as calibration_step
from app.services.calibration import remainder_fill_percent
from app.services.level_journal import published_levels


def test_policy_file_is_the_only_copy():
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert DIAL_MIN_PERCENT == raw["dial_min_percent"]
    assert DIAL_MAX_PERCENT == raw["dial_max_percent"]
    assert LEVEL_STEP_VOLTS == raw["level_step_volts"]
    assert calibration_step == LEVEL_STEP_VOLTS
    assert LITER_NOISE == raw["liter_noise"]
    assert POLL_SECONDS == raw["poll_seconds"]
    assert SENSOR_STALE_SECONDS == raw["sensor_stale_seconds"]
    assert Settings.model_fields["sensor_stale_seconds"].default == SENSOR_STALE_SECONDS
    assert Settings.model_fields["shelly_poll_seconds"].default == POLL_SECONDS


def test_ingest_path_follows_api_prefix(monkeypatch):
    monkeypatch.setenv("API_PREFIX", "/api/v2")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.ingest_level_path == "/api/v2/ingest/level"
        assert settings.ingest_level_url == "http://localhost:8000/api/v2/ingest/level"
    finally:
        get_settings.cache_clear()


def test_same_percent_rounding_on_board_and_in_journal():
    assert remainder_fill_percent(6550, 10000) == 66

    class Row:
        def __init__(self, liters, percent):
            self.id = "1"
            self.tank_id = "2"
            self.volts = None
            self.remainder_liters = liters
            self.fill_percent = percent
            self.recorded_at = None

    kept = published_levels(
        [Row(6500, 65), Row(6540, 65.4), Row(6600, 66)],
        changes_only=True,
    )
    assert [row.remainder_liters for row in kept] == [6600, 6500]
    assert kept[0].fill_percent == 66


def test_liter_noise_hides_substep_without_volts():
    class Row:
        def __init__(self, liters):
            self.id = liters
            self.tank_id = "t"
            self.volts = None
            self.remainder_liters = liters
            self.fill_percent = None
            self.recorded_at = None

    kept = published_levels([Row(1000), Row(1000 + LITER_NOISE / 2), Row(1000 + LITER_NOISE)], changes_only=True)
    assert [row.remainder_liters for row in kept] == [1000 + LITER_NOISE, 1000]
