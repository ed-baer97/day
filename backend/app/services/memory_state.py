"""Снимок учёта на диск.

Один процесс API. Несколько реплик затрут один и тот же файл.
Пустой STATE_PATH оставляет данные только в памяти.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_file_lock = threading.Lock()
_VERSION = 1


def _path() -> Path | None:
    raw = get_settings().state_path.strip()
    if not raw:
        return None
    return Path(raw)


def persist() -> None:
    path = _path()
    if path is None:
        return
    from app.services.account_mode import use_postgres

    if use_postgres():
        return
    from app.services import catalog, device_ingest
    from app.services import shelly_link

    with _file_lock:
        payload = {
            "version": _VERSION,
            "catalog": catalog.snapshot(),
            "devices": device_ingest.snapshot(),
            "shelly": shelly_link.snapshot_bindings(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def restore() -> None:
    from app.services.account_mode import use_postgres

    if use_postgres():
        return
    path = _path()
    if path is None or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("файл состояния не прочитан: %s", path)
        return
    if not isinstance(data, dict) or data.get("version") != _VERSION:
        logger.error("файл состояния пропущен: %s", path)
        return
    from app.services import catalog, device_ingest
    from app.services import shelly_link

    with _file_lock:
        catalog.restore_snapshot(data.get("catalog") or {})
        device_ingest.restore_snapshot(data.get("devices") or {})
        if "shelly" in data and isinstance(data["shelly"], list):
            shelly_link.restore_bindings(data["shelly"])
