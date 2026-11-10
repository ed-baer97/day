"""Тесты ходят в учёт без пароля. Боевой запуск этот флаг не включает."""

import os

os.environ["TESTING"] = "true"
os.environ["AUTH_DISABLED"] = "true"
os.environ["STATE_PATH"] = ""
os.environ["ACCOUNT_STORE"] = "memory"

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _auth_open_for_tests():
    os.environ["AUTH_DISABLED"] = "true"
    os.environ["STATE_PATH"] = ""
    os.environ["ACCOUNT_STORE"] = "memory"
    get_settings.cache_clear()
    yield
    os.environ["AUTH_DISABLED"] = "true"
    os.environ["STATE_PATH"] = ""
    os.environ["ACCOUNT_STORE"] = "memory"
    get_settings.cache_clear()
