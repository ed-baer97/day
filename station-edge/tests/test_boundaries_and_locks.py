"""Тесты архитектурных границ 4 владельцев, ExclusivePortLock и защиты CLI на живом порту."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agzs_edge.config import EdgeSettings
from agzs_edge.main import main
from agzs_edge.port_lock import ExclusivePortLock, PortBusyError

AGZS_PKG = Path(__file__).resolve().parents[1] / "agzs_edge"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_four_owners_import_boundaries() -> None:
    """Проверка границ слоёв: журнал (storage) без HTTP/serial; sync/updater без serial/psu/service."""
    storage_mods = _imported_modules(AGZS_PKG / "storage.py")
    forbidden_storage = ("serial", "urllib", "agzs_edge.serial_link", "agzs_edge.psu_controller", "agzs_edge.sync", "agzs_edge.updater", "agzs_edge.service")
    for mod in storage_mods:
        assert not mod.startswith(forbidden_storage), f"storage.py импортирует запрещённый модуль {mod}"

    forbidden_vps_client = ("serial", "agzs_edge.serial_link", "agzs_edge.psu_controller", "agzs_edge.service")
    for filename in ("sync.py", "updater.py"):
        for mod in _imported_modules(AGZS_PKG / filename):
            assert not mod.startswith(forbidden_vps_client), f"{filename} импортирует запрещённый модуль {mod}"


def test_release_signing_byte_for_byte_sync_with_backend() -> None:
    backend_file = REPO_ROOT / "backend" / "app" / "domain" / "edge_release.py"
    if not backend_file.is_file():
        pytest.skip("backend отсутствует рядом в рабочей копии")
    edge_file = AGZS_PKG / "release_signing.py"
    assert edge_file.read_text(encoding="utf-8") == backend_file.read_text(encoding="utf-8")


def test_exclusive_port_lock_rejects_second_holder(tmp_path: Path) -> None:
    lock1 = ExclusivePortLock("/dev/ttyUSB0", lock_dir=tmp_path)
    lock2 = ExclusivePortLock("/dev/ttyUSB0", lock_dir=tmp_path)
    lock1.acquire()
    try:
        with pytest.raises(PortBusyError):
            lock2.acquire()
    finally:
        lock1.release()

    # После освобождения второй владелец может захватить порт
    with lock2:
        pass


def test_edge_settings_no_hardcoded_station_and_cli_guards(tmp_path: Path, monkeypatch) -> None:
    for key in (
        "AGZS_VPS_BASE_URL",
        "AGZS_DEVICE_TOKEN",
        "AGZS_STATION_CODE",
        "AGZS_STATION_ID",
        "AGZS_TANK_ID",
        "AGZS_ALLOW_INSECURE_HTTP",
        "AGZS_REQUIRE_RELEASE_SIGNATURE",
        "AGZS_ALLOW_CLI_CONTROL",
    ):
        monkeypatch.delenv(key, raising=False)

    empty_env = tmp_path / "empty.env"
    empty_env.write_text(f"AGZS_DB_PATH={tmp_path / 'cli.db'}\n", encoding="utf-8")
    cfg = EdgeSettings.from_env(empty_env)
    assert cfg.station_code == ""
    assert cfg.station_id == ""
    assert cfg.tank_id == ""
    assert cfg.vps_base_url == ""
    assert cfg.require_release_signature is True

    # flush, serve (c sync=1) и update без явного .env завершаются кодом 2
    assert main(["--env-file", str(empty_env), "flush"]) == 2
    assert main(["--env-file", str(empty_env), "serve"]) == 2
    assert main(["--env-file", str(empty_env), "update", "--check"]) == 2

    # Команда управления на живом порту без --allow-control отклоняется (rc=2)
    assert main(["--env-file", str(empty_env), "start", "--addr", "1", "--liters", "10"]) == 2
    assert main(["--env-file", str(empty_env), "unlock", "--addr", "1"]) == 2


def test_systemd_units_separate_edge_and_updater_privileges() -> None:
    root = REPO_ROOT / "station-edge"
    edge_unit = (root / "station-edge.service").read_text(encoding="utf-8")
    upd_unit = (root / "station-edge-updater.service").read_text(encoding="utf-8")
    monitor_unit = (root / "station-edge-monitor.service").read_text(encoding="utf-8")

    assert "ProtectSystem=strict" in edge_unit
    assert "DevicePolicy=closed" in edge_unit
    assert "SupplementaryGroups=tty station-edge" in edge_unit
    assert "User=station-edge-updater" in upd_unit
    assert "SupplementaryGroups=station-edge" in upd_unit
    assert "dialout" not in upd_unit
    assert "NoNewPrivileges=true" in upd_unit
    assert "DevicePolicy=closed" in upd_unit
    assert "WorkingDirectory=/var/lib/station-edge" in monitor_unit
    assert "SupplementaryGroups=station-edge" in monitor_unit
    assert "ReadWritePaths=/var/lib/station-edge" in monitor_unit
