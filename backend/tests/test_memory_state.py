"""Файл состояния переживает очистку памяти процесса."""

from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.schemas.ingest import CalibrationIn, LevelIngest
from app.services.catalog import create_station, list_stations, reset_catalog
from app.services.device_ingest import (
    accept_level,
    register_tank,
    reset_device_ingest,
    set_calibration,
    tank_by_token,
    tank_state,
)
from app.services.memory_state import restore
from app.services.shelly_link import connect_shelly, reset_shelly_links, set_shelly_rpc, shelly_view


class _Shelly:
    def __init__(self, volts: float) -> None:
        self.volts = volts

    def call(self, host: str, method: str, params: dict | None = None) -> dict:
        if method == "Shelly.GetDeviceInfo":
            return {"mac": "F8B3B7FD62F8", "app": "PlusUni", "ver": "1.3.3", "model": "SNSN-0043X"}
        if method == "Uni.GetPeripherals":
            return {"voltmeter": {"voltmeter:100": {}}}
        if method == "Shelly.GetStatus":
            return {
                "sys": {"unixtime": 1792270287, "restart_required": False},
                "wifi": {"rssi": -52},
                "voltmeter:100": {"id": 100, "voltage": self.volts},
            }
        raise AssertionError(method)


def test_restart_keeps_tank_token_scale_and_shelly(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    get_settings.cache_clear()
    reset_catalog()
    reset_device_ingest()
    reset_shelly_links()
    set_shelly_rpc(_Shelly(3.0))

    station = create_station(
        code="AGZS-FILE",
        name="Файл",
        address=None,
        lat=43.6,
        lon=51.2,
        is_active=True,
    )
    device = register_tank(station.id, "R-1", 10000)
    set_calibration(
        CalibrationIn(
            station_id=device.station_id,
            tank_id=device.tank_id,
            low_volts=1.0,
            low_percent=0,
            high_volts=5.0,
            high_percent=100,
        )
    )
    accept_level(
        LevelIngest(
            station_id=device.station_id,
            tank_id=device.tank_id,
            volts=3.0,
            recorded_at=datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc),
            source_event_id="persist-level",
        )
    )
    connect_shelly(device.station_id, device.tank_id, "192.168.0.104")

    token = device.token
    tank_id = device.tank_id
    reset_catalog()
    reset_device_ingest()
    reset_shelly_links()
    assert tank_by_token(token) is None

    restore()
    revived = tank_by_token(token)
    assert revived is not None
    assert revived.tank_id == tank_id
    state = tank_state(tank_id)
    assert state.calibrated is True
    assert state.actual_remainder_liters == pytest.approx(5000)
    assert state.last_volts == pytest.approx(3.0)
    assert {row.code for row in list_stations()} >= {"AGZS-AKT-12", "AGZS-FILE"}
    linked = shelly_view(tank_id)
    assert linked is not None
    assert linked.host == "192.168.0.104"

    duplicate = accept_level(
        LevelIngest(
            station_id=revived.station_id,
            tank_id=tank_id,
            volts=3.0,
            recorded_at=datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc),
            source_event_id="persist-level",
        )
    )
    assert duplicate.duplicate is True
