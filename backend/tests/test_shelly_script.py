"""Подстановка адреса и ключа в скрипт Shelly."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "install_shelly_level.py"
_SPEC = importlib.util.spec_from_file_location("install_shelly_level", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)

SOURCE = installer.SCRIPT_PATH.read_text(encoding="utf-8")


def test_script_posts_voltage_with_token():
    rendered = installer.render_script(
        SOURCE,
        "http://192.168.0.106:8000/api/v1/ingest/level",
        "tank-token",
    )
    assert 'let SERVER_URL = "http://192.168.0.106:8000/api/v1/ingest/level";' in rendered
    assert 'let DEVICE_TOKEN = "tank-token";' in rendered
    assert "voltmeter:100" in rendered
    assert "X-Device-Token" in rendered
    assert "%%SERVER_URL%%" not in rendered
    assert "%%DEVICE_TOKEN%%" not in rendered


def test_quotes_in_token_are_escaped():
    rendered = installer.render_script(SOURCE, "http://host/level", 'a"b')
    assert r'let DEVICE_TOKEN = "a\"b";' in rendered


def test_template_without_placeholders_is_rejected():
    with pytest.raises(ValueError):
        installer.render_script("let x = 1;", "http://host", "token")
