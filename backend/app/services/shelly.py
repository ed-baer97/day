"""Чтение Shelly Plus Uni по локальному RPC.

Вольтметр на прошивке 1.3.3 появляется в статусе только после перезагрузки.
Пока датчик не подключён, открытый вход всё равно отдаёт напряжение.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

_APP_NAMES = {"PlusUni": "Plus Uni"}
_REBOOT_COOLDOWN_SECONDS = 120.0
_rebooted_at: dict[str, float] = {}


class ShellyError(Exception):
    pass


class ShellyRpc(Protocol):
    def call(self, host: str, method: str, params: dict | None = None) -> dict: ...


@dataclass(frozen=True)
class ShellySnapshot:
    mac: str | None
    model: str | None
    firmware: str | None
    rssi: int | None
    sensor_ready: bool
    volts: float | None
    measured_at: datetime


def reset_shelly_runtime() -> None:
    _rebooted_at.clear()


def parse_rpc_payload(payload: object) -> dict:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ShellyError("непонятный ответ Shelly")
    error = payload.get("error")
    if isinstance(error, dict):
        raise ShellyError(str(error.get("message") or "ошибка Shelly"))
    if "result" in payload and ("src" in payload or "id" in payload):
        result = payload["result"]
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise ShellyError("непонятный ответ Shelly")
        return result
    if "code" in payload and "message" in payload and "mac" not in payload and "wifi" not in payload:
        raise ShellyError(str(payload["message"]))
    return payload


def voltmeter_ready(peripherals: dict) -> bool:
    voltmeter = peripherals.get("voltmeter")
    return isinstance(voltmeter, dict) and bool(voltmeter)


def volts_of(status: dict) -> float | None:
    for key, value in status.items():
        if not isinstance(key, str) or not key.startswith("voltmeter:"):
            continue
        if not isinstance(value, dict):
            continue
        voltage = value.get("voltage")
        if isinstance(voltage, (int, float)) and not isinstance(voltage, bool):
            return float(voltage)
    return None


def snapshot_from(info: dict, status: dict, peripherals: dict) -> ShellySnapshot:
    volts = volts_of(status)
    return ShellySnapshot(
        mac=_text(info.get("mac")),
        model=_model(info),
        firmware=_text(info.get("ver")),
        rssi=_rssi(status),
        sensor_ready=voltmeter_ready(peripherals) or volts is not None,
        volts=volts,
        measured_at=_measured_at(status),
    )


def read_snapshot(
    host: str,
    rpc: ShellyRpc,
    pause: Callable[[float], None] = time.sleep,
) -> ShellySnapshot:
    info = rpc.call(host, "Shelly.GetDeviceInfo")
    peripherals = rpc.call(host, "Uni.GetPeripherals")
    status = rpc.call(host, "Shelly.GetStatus")
    ready = voltmeter_ready(peripherals)
    if volts_of(status) is None and not ready:
        rpc.call(host, "Uni.AddPeripheral", {"type": "voltmeter"})
        peripherals = rpc.call(host, "Uni.GetPeripherals")
        status = rpc.call(host, "Shelly.GetStatus")
        if volts_of(status) is None and _reboot_once(host, rpc):
            status = _wait_status(host, rpc, pause)
            peripherals = rpc.call(host, "Uni.GetPeripherals")
    elif volts_of(status) is None and ready and _restart_required(status) and _reboot_once(host, rpc):
        status = _wait_status(host, rpc, pause)
    return snapshot_from(info, status, peripherals)


class HttpShelly:
    def __init__(self, timeout: float = 4.0) -> None:
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, host: str, method: str, params: dict | None = None) -> dict:
        body = json.dumps({"id": 1, "method": method, "params": params or {}}).encode()
        request = urllib.request.Request(
            f"http://{host}/rpc",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise ShellyError("на Shelly включён пароль") from error
            raw = error.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ShellyError("нет связи с Shelly") from error
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError as error:
            raise ShellyError("непонятный ответ Shelly") from error
        return parse_rpc_payload(payload)


def _reboot_once(host: str, rpc: ShellyRpc) -> bool:
    now = time.monotonic()
    previous = _rebooted_at.get(host)
    if previous is not None and now - previous < _REBOOT_COOLDOWN_SECONDS:
        return False
    _rebooted_at[host] = now
    try:
        rpc.call(host, "Shelly.Reboot")
    except ShellyError as error:
        if str(error) != "нет связи с Shelly":
            raise
    return True


def _wait_status(host: str, rpc: ShellyRpc, pause: Callable[[float], None]) -> dict:
    last: dict | None = None
    for attempt in range(20):
        try:
            status = rpc.call(host, "Shelly.GetStatus")
        except ShellyError:
            status = None
        if status is not None:
            last = status
            if volts_of(status) is not None or not _restart_required(status):
                return status
        if attempt < 19:
            pause(1.5)
    if last is not None:
        return last
    raise ShellyError("Shelly перезагружается")


def _restart_required(status: dict) -> bool:
    sys = status.get("sys")
    return isinstance(sys, dict) and bool(sys.get("restart_required"))


def _measured_at(status: dict) -> datetime:
    sys = status.get("sys")
    if isinstance(sys, dict):
        stamp = sys.get("unixtime")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and stamp > 0:
            return datetime.fromtimestamp(float(stamp), timezone.utc)
    return datetime.now(timezone.utc)


def _rssi(status: dict) -> int | None:
    wifi = status.get("wifi")
    if not isinstance(wifi, dict):
        return None
    value = wifi.get("rssi")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return None


def _model(info: dict) -> str | None:
    app = info.get("app")
    if isinstance(app, str) and app:
        return _APP_NAMES.get(app, app)
    return _text(info.get("model"))


def _text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
