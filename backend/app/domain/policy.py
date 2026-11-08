"""Одна шкала для сервера, витрины и скрипта Shelly.

Числа лежат в level_policy.json рядом с этим модулем.
Образ API копирует каталог app целиком, поэтому файл есть и на площадке.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

POLICY_PATH = Path(__file__).with_name("level_policy.json")


def load_policy() -> dict:
    with POLICY_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise RuntimeError("level_policy.json должен быть объектом")
    return data


_POLICY = load_policy()


def _number(name: str) -> float:
    value = _POLICY[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{name} в level_policy.json должно быть числом")
    return float(value)


def _quantum(name: str) -> Decimal:
    """Целое 1 остаётся шагом 1, а не 1.0. Иначе 65,5 округляется не туда."""

    value = _POLICY[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{name} в level_policy.json должно быть числом")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def _text(name: str) -> str:
    value = _POLICY[name]
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{name} в level_policy.json должно быть непустой строкой")
    return value


DIAL_MIN_PERCENT = _number("dial_min_percent")
DIAL_MAX_PERCENT = _number("dial_max_percent")
LEVEL_STEP_VOLTS = _number("level_step_volts")
VOLT_QUANTUM = _quantum("volt_quantum")
PERCENT_QUANTUM = _quantum("percent_quantum")
LITER_NOISE = _number("liter_noise")
LOW_FILL_PERCENT = _number("low_fill_percent")
POLL_SECONDS = _number("poll_seconds")
SENSOR_STALE_SECONDS = _number("sensor_stale_seconds")
ROLE_ADMIN = _text("role_admin")
ROLE_STATION = _text("role_station")
