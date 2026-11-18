"""Снимок учёта на диск через реестр хранилищ (без циклических импортов).

Один процесс API. Несколько реплик затрут один и тот же файл.
Пустой STATE_PATH оставляет данные только в памяти.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from app.config import get_settings
from app.services import account_mode

logger = logging.getLogger(__name__)

_file_lock = threading.Lock()
_VERSION = 1

SnapshotFn = Callable[[], Any]
RestoreFn = Callable[[Any], None]
_STORES: dict[str, tuple[SnapshotFn, RestoreFn]] = {}


def register_store(name: str, snapshot_fn: SnapshotFn, restore_fn: RestoreFn) -> None:
    """Регистрирует модуль памяти для сохранения/восстановления снимка state.json."""
    _STORES[name] = (snapshot_fn, restore_fn)


def _path() -> Path | None:
    raw = get_settings().state_path.strip()
    if not raw:
        return None
    return Path(raw)


def persist() -> None:
    path = _path()
    if path is None or account_mode.use_postgres():
        return

    with _file_lock:
        payload: dict[str, Any] = {"version": _VERSION}
        for name, (snapshot_fn, _restore_fn) in _STORES.items():
            payload[name] = snapshot_fn()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def restore() -> None:
    if account_mode.use_postgres():
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

    with _file_lock:
        for name, (_snapshot_fn, restore_fn) in _STORES.items():
            if name in data and data[name] is not None:
                restore_fn(data[name])
