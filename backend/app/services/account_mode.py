"""Режим учёта: memory (тесты/стенд) или postgres (площадка)."""

from __future__ import annotations

from app.config import get_settings


def use_postgres() -> bool:
    return get_settings().use_postgres
