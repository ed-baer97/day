"""Настройки пульта из окружения и файла .env в текущем каталоге."""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class Settings:
    def __init__(self) -> None:
        _load_dotenv(Path(".env"))
        self.env = os.environ.get("AGZS_ENV", "production").strip() or "production"
        self.pump_driver = os.environ.get("AGZS_PUMP_DRIVER", "aska02").strip() or "aska02"
        self.api_base = (
            os.environ.get("AGZS_API_BASE")
            or os.environ.get("LPG_API")
            or "http://127.0.0.1:5173/api/v1"
        ).strip().rstrip("/")
        self.station_code = (os.environ.get("AGZS_STATION_CODE") or "AGZS-TEST").strip()
        if self.env not in {"production", "emulator", "test"}:
            raise ValueError("AGZS_ENV должен быть production, emulator или test")
        if self.pump_driver not in {"emulator", "aska02"}:
            raise ValueError("AGZS_PUMP_DRIVER должен быть emulator или aska02")
