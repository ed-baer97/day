"""Потокобезопасный кэш открытой витрины. Без зависимостей от адаптеров и сервисов."""

from __future__ import annotations

import threading
import time
from typing import TypeVar

T = TypeVar("T")

_cache_lock = threading.Lock()
_cached_rows: list | None = None
_cached_at: float = 0.0
_CACHE_TTL_SEC: float = 2.5


def get_cached_board() -> list | None:
    now_mono = time.monotonic()
    with _cache_lock:
        if _cached_rows is not None and (now_mono - _cached_at) < _CACHE_TTL_SEC:
            return _cached_rows
    return None


def set_cached_board(rows: list) -> None:
    global _cached_rows, _cached_at
    with _cache_lock:
        _cached_rows = rows
        _cached_at = time.monotonic()


def invalidate_public_board_cache() -> None:
    """Сбрасывает кэш витрины при поступлении свежих замеров и изменениях каталога."""
    global _cached_rows, _cached_at
    with _cache_lock:
        _cached_rows = None
        _cached_at = 0.0
