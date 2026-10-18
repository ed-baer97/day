"""Опрос Shelly Plus Uni и запись напряжения в резервуар."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.device_ingest import reset_device_ingest
from app.services.shelly import ShellyError, parse_rpc_payload, read_snapshot, snapshot_from
from app.services.shelly_link import reset_shelly_links, set_shelly_rpc

client = TestClient(create_app())
STATION = "a1111111-1111-1111-1111-111111111101"


class MemoryShelly:
    def __init__(
        self,
        volts: float | None = 0.06,
        configured: bool = True,
        restart: bool = False,
    ) -> None:
        self.volts = volts
        self.configured = configured
        self.restart = restart
        self.calls: list[str] = []

    def call(self, host: str, method: str, params: dict | None = None) -> dict:
        self.calls.append(method)
        if method == "Shelly.GetDeviceInfo":
            return {"mac": "F8B3B7FD62F8", "app": "PlusUni", "ver": "1.3.3", "model": "SNSN-0043X"}
        if method == "Uni.GetPeripherals":
            if self.configured:
                return {"voltmeter": {"voltmeter:100": {}}}
            return {"voltmeter": {}}
        if method == "Uni.AddPeripheral":
            assert params == {"type": "voltmeter"}
            self.configured = True
            self.restart = True
            return {"voltmeter:100": {}}
        if method == "Shelly.Reboot":
            self.configured = True
            self.restart = False
            return {}
        if method == "Shelly.GetStatus":
            status: dict = {
                "sys": {"unixtime": 1792270287, "restart_required": self.restart},
                "wifi": {"rssi": -52},
            }
            if self.configured and not self.restart and self.volts is not None:
                status["voltmeter:100"] = {"id": 100, "voltage": self.volts}
            return status
        raise AssertionError(method)


class OfflineShelly:
    def call(self, host: str, method: str, params: dict | None = None) -> dict:
        raise ShellyError("нет связи с Shelly")


@pytest.fixture(autouse=True)
def _clean():
    reset_device_ingest()
    reset_shelly_links()
    yield
    reset_device_ingest()
    reset_shelly_links()


def test_snapshot_reads_open_input_voltage():
    snap = snapshot_from(
        {"mac": "F8B3B7FD62F8", "app": "PlusUni", "ver": "1.3.3"},
        {
            "voltmeter:100": {"id": 100, "voltage": 0.06},
            "wifi": {"rssi": -52},
            "sys": {"unixtime": 1792270287},
        },
        {"voltmeter": {"voltmeter:100": {}}},
    )
    assert snap.volts == pytest.approx(0.06)
    assert snap.model == "Plus Uni"
    assert snap.firmware == "1.3.3"
    assert snap.rssi == -52
    assert snap.sensor_ready is True
    assert snap.mac == "F8B3B7FD62F8"


def test_rpc_envelope_unwraps_result_and_error():
    assert parse_rpc_payload(
        {"id": 1, "src": "shellyplusuni", "result": {"ver": "1.3.3"}}
    ) == {"ver": "1.3.3"}
    assert parse_rpc_payload({"id": 1, "src": "shellyplusuni", "result": None}) == {}
    with pytest.raises(ShellyError, match="bad argument"):
        parse_rpc_payload({"id": 1, "error": {"code": -103, "message": "bad argument"}})


def test_missing_voltmeter_is_enabled_once():
    device = MemoryShelly(configured=False, volts=0.06)
    snap = read_snapshot("192.168.0.104", device, pause=lambda _seconds: None)
    assert snap.volts == pytest.approx(0.06)
    assert device.calls.count("Uni.AddPeripheral") == 1
    assert device.calls.count("Shelly.Reboot") == 1

    read_snapshot("192.168.0.104", device, pause=lambda _seconds: None)
    assert device.calls.count("Shelly.Reboot") == 1
    assert device.calls.count("Uni.AddPeripheral") == 1


def test_configured_shelly_is_not_rebooted():
    device = MemoryShelly(volts=0.06, configured=True)
    snap = read_snapshot("192.168.0.104", device, pause=lambda _seconds: None)
    assert snap.volts == pytest.approx(0.06)
    assert "Uni.AddPeripheral" not in device.calls
    assert "Shelly.Reboot" not in device.calls


def test_link_shows_voltage_before_calibration():
    device = MemoryShelly(volts=0.06)
    set_shelly_rpc(device)
    tank_id = _tank()
    linked = client.put(
        f"/api/v1/stations/{STATION}/devices/{tank_id}/shelly",
        json={"host": "http://192.168.0.104/rpc"},
    )
    assert linked.status_code == 200
    shelly = linked.json()["shelly"]
    assert shelly["host"] == "192.168.0.104"
    assert shelly["online"] is True
    assert shelly["model"] == "Plus Uni"
    assert shelly["volts"] == pytest.approx(0.06)
    assert shelly["applied"] is False
    assert shelly["last_error"] is None
    assert client.get(f"/api/v1/ingest/tanks/{tank_id}").status_code == 404


def test_calibration_writes_shelly_voltage_into_the_book():
    device = MemoryShelly(volts=2.5)
    set_shelly_rpc(device)
    tank_id, token = _tank_with_token()
    client.put(
        f"/api/v1/stations/{STATION}/devices/{tank_id}/shelly",
        json={"host": "192.168.0.104"},
    )
    calibrated = client.put(
        "/api/v1/ingest/calibration",
        headers={"X-Device-Token": token},
        json={
            "low_volts": 1.2,
            "low_percent": 20,
            "high_volts": 3.8,
            "high_percent": 80,
        },
    )
    assert calibrated.status_code == 200
    assert calibrated.json()["actual_remainder_liters"] == pytest.approx(5000)
    assert calibrated.json()["last_volts"] == pytest.approx(2.5)

    listed = client.get(f"/api/v1/stations/{STATION}/devices")
    row = next(item for item in listed.json() if item["id"] == tank_id)
    assert row["shelly"]["applied"] is True


def test_offline_shelly_stays_linked():
    set_shelly_rpc(OfflineShelly())
    tank_id = _tank()
    linked = client.put(
        f"/api/v1/stations/{STATION}/devices/{tank_id}/shelly",
        json={"host": "192.168.0.104"},
    )
    assert linked.status_code == 200
    assert linked.json()["shelly"]["online"] is False
    assert linked.json()["shelly"]["last_error"] == "нет связи с Shelly"
    assert linked.json()["shelly"]["volts"] is None


def test_one_shelly_per_tank_and_disconnect():
    set_shelly_rpc(MemoryShelly())
    first = _tank("R-A")
    second = _tank("R-B")
    assert (
        client.put(
            f"/api/v1/stations/{STATION}/devices/{first}/shelly",
            json={"host": "192.168.0.104"},
        ).status_code
        == 200
    )
    conflict = client.put(
        f"/api/v1/stations/{STATION}/devices/{second}/shelly",
        json={"host": "192.168.0.104"},
    )
    assert conflict.status_code == 409

    removed = client.delete(f"/api/v1/stations/{STATION}/devices/{first}/shelly")
    assert removed.status_code == 200
    assert removed.json()["shelly"] is None
    assert client.delete(f"/api/v1/stations/{STATION}/devices/{first}/shelly").status_code == 404

    moved = client.put(
        f"/api/v1/stations/{STATION}/devices/{second}/shelly",
        json={"host": "192.168.0.104"},
    )
    assert moved.status_code == 200
    assert moved.json()["shelly"]["host"] == "192.168.0.104"


def test_bad_host_rejected():
    tank_id = _tank()
    rejected = client.put(
        f"/api/v1/stations/{STATION}/devices/{tank_id}/shelly",
        json={"host": "http://user:pass@192.168.0.104"},
    )
    assert rejected.status_code == 422
    assert client.get(f"/api/v1/stations/{STATION}/devices").json()[0]["shelly"] is None


def _tank(code: str | None = None) -> str:
    tank_id, _token = _tank_with_token(code)
    return tank_id


def _tank_with_token(code: str | None = None) -> tuple[str, str]:
    created = client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": code or f"R-{uuid4().hex[:8]}", "capacity_liters": 10000},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["shelly"] is None
    return body["id"], body["ingest_token"]
