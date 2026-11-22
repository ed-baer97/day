"""Тесты ходят в учёт без пароля. Боевой запуск этот флаг не включает."""

import os

os.environ["TESTING"] = "true"
os.environ["AUTH_DISABLED"] = "true"
os.environ["ALLOW_ANONYMOUS_INGEST"] = "true"
os.environ["STATE_PATH"] = ""
os.environ["ACCOUNT_STORE"] = "memory"

import pytest

from app.config import get_settings
from app.services.balance_log import reset_generated_events


@pytest.fixture(autouse=True)
def _auth_open_for_tests():
    os.environ["AUTH_DISABLED"] = "true"
    os.environ["ALLOW_ANONYMOUS_INGEST"] = "true"
    os.environ["STATE_PATH"] = ""
    os.environ["ACCOUNT_STORE"] = "memory"
    get_settings.cache_clear()
    reset_generated_events()
    yield
    os.environ["AUTH_DISABLED"] = "true"
    os.environ["ALLOW_ANONYMOUS_INGEST"] = "true"
    os.environ["STATE_PATH"] = ""
    os.environ["ACCOUNT_STORE"] = "memory"
    get_settings.cache_clear()
