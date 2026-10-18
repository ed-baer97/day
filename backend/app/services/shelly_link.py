"""Привязка Shelly к резервуару и опрос по IP.

Сервер сам ходит на прибор. Датчик может быть ещё не подключён:
напряжение показываем сразу, в книгу остатка пишем только после калибровки.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.config import get_settings
from app.schemas.ingest import LevelIngest
from app.schemas.station import ShellyLinkOut
from app.services.device_ingest import accept_level, get_tank_device, has_calibration
from app.services.shelly import HttpShelly, ShellyError, ShellyRpc, ShellySnapshot, read_snapshot, reset_shelly_runtime

logger = logging.getLogger(__name__)

_HOST = re.compile(
    r"^(?:(?:\d{1,3}\.){3}\d{1,3}|localhost|"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    r"(?::\d{1,5})?$"
)

_lock = threading.Lock()
_gate = threading.Lock()
_links: dict[UUID, "ShellyLink"] = {}
_rpc: ShellyRpc = HttpShelly()


@dataclass
class ShellyLink:
    station_id: UUID
    tank_id: UUID
    host: str
    online: bool = False
    mac: str | None = None
    model: str | None = None
    firmware: str | None = None
    rssi: int | None = None
    sensor_ready: bool = False
    volts: float | None = None
    applied: bool = False
    last_polled_at: datetime | None = None
    last_error: str | None = None


def reset_shelly_links() -> None:
    global _rpc
    with _lock:
        _links.clear()
    _rpc = HttpShelly()
    reset_shelly_runtime()


def set_shelly_rpc(rpc: ShellyRpc) -> None:
    global _rpc
    _rpc = rpc


def normalize_host(raw: str) -> str:
    text = raw.strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/")[0].strip()
    if not _HOST.fullmatch(text):
        raise HTTPException(status_code=422, detail="укажите IP-адрес Shelly, например 192.168.0.104")
    ip, sep, port = text.rpartition(":")
    if sep:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise HTTPException(status_code=422, detail="укажите IP-адрес Shelly, например 192.168.0.104")
        text_ip = ip
    else:
        text_ip = text
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text_ip):
        if any(int(part) > 255 for part in text_ip.split(".")):
            raise HTTPException(status_code=422, detail="укажите IP-адрес Shelly, например 192.168.0.104")
    return text


def shelly_view(tank_id: UUID) -> ShellyLinkOut | None:
    with _lock:
        link = _links.get(tank_id)
        if link is None:
            return None
        return _view(link)


def connect_shelly(station_id: UUID, tank_id: UUID, host: str) -> None:
    device = get_tank_device(station_id, tank_id)
    normalized = normalize_host(host)
    with _lock:
        for link in _links.values():
            if link.host == normalized and link.tank_id != device.tank_id:
                raise HTTPException(status_code=409, detail="этот Shelly уже привязан к другому резервуару")
        current = _links.get(device.tank_id)
        if current is None:
            _links[device.tank_id] = ShellyLink(
                station_id=device.station_id,
                tank_id=device.tank_id,
                host=normalized,
            )
        else:
            current.host = normalized
            current.online = False
            current.volts = None
            current.applied = False
            current.last_error = None
    poll_one(device.tank_id)


def disconnect_shelly(station_id: UUID, tank_id: UUID) -> None:
    get_tank_device(station_id, tank_id)
    with _lock:
        link = _links.get(tank_id)
        if link is None or link.station_id != station_id:
            raise HTTPException(status_code=404, detail="Shelly не привязан")
        del _links[tank_id]


def poll_one(tank_id: UUID) -> None:
    with _gate:
        with _lock:
            link = _links.get(tank_id)
            if link is None:
                return
            host = link.host
            station_id = link.station_id
        _poll_host(tank_id, station_id, host)


def poll_all() -> None:
    with _lock:
        tank_ids = list(_links)
    for tank_id in tank_ids:
        poll_one(tank_id)


def _poll_host(tank_id: UUID, station_id: UUID, host: str) -> None:
    now = datetime.now(timezone.utc)
    try:
        snapshot = read_snapshot(host, _rpc)
    except ShellyError as error:
        _remember(tank_id, host, online=False, error=str(error), polled_at=now)
        return
    except Exception:
        logger.exception("опрос Shelly %s", host)
        _remember(tank_id, host, online=False, error="не удалось опросить Shelly", polled_at=now)
        return
    error_text, applied = _apply(station_id, tank_id, snapshot)
    _remember(
        tank_id,
        host,
        online=True,
        error=error_text,
        polled_at=now,
        snapshot=snapshot,
        applied=applied,
    )


def _apply(station_id: UUID, tank_id: UUID, snapshot: ShellySnapshot) -> tuple[str | None, bool]:
    if snapshot.volts is None or not has_calibration(station_id, tank_id):
        return None, False
    body = LevelIngest(
        station_id=station_id,
        tank_id=tank_id,
        volts=snapshot.volts,
        recorded_at=snapshot.measured_at,
        source_event_id=f"shelly-{uuid4()}",
        level_source="electronic",
    )
    try:
        accept_level(body)
    except HTTPException as error:
        detail = error.detail
        return detail if isinstance(detail, str) else "не удалось записать уровень", False
    return None, True


def _remember(
    tank_id: UUID,
    host: str,
    *,
    online: bool,
    error: str | None,
    polled_at: datetime,
    snapshot: ShellySnapshot | None = None,
    applied: bool = False,
) -> None:
    with _lock:
        link = _links.get(tank_id)
        if link is None or link.host != host:
            return
        link.online = online
        link.last_error = error
        link.last_polled_at = polled_at
        link.applied = applied
        if not online or snapshot is None:
            link.volts = None
            link.applied = False
            return
        link.mac = snapshot.mac
        link.model = snapshot.model
        link.firmware = snapshot.firmware
        link.rssi = snapshot.rssi
        link.sensor_ready = snapshot.sensor_ready
        link.volts = snapshot.volts


def _view(link: ShellyLink) -> ShellyLinkOut:
    return ShellyLinkOut(
        host=link.host,
        online=link.online,
        mac=link.mac,
        model=link.model,
        firmware=link.firmware,
        rssi=link.rssi,
        sensor_ready=link.sensor_ready,
        volts=link.volts,
        applied=link.applied,
        last_polled_at=link.last_polled_at,
        last_error=link.last_error,
    )


class ShellyPoller:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._users = 0
        self._life = threading.Lock()

    def start(self) -> None:
        with self._life:
            self._users += 1
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="shelly-poll", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        thread: threading.Thread | None = None
        with self._life:
            self._users = max(0, self._users - 1)
            if self._users:
                return
            self._stop.set()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                poll_all()
            except Exception:
                logger.exception("опрос Shelly")
            if self._stop.wait(_poll_seconds()):
                return


def _poll_seconds() -> float:
    seconds = get_settings().shelly_poll_seconds
    if seconds < 5:
        return 5.0
    return seconds


shelly_poller = ShellyPoller()
