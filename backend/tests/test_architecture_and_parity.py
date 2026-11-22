"""AST-проверки границ слоёв, отсутствия циклов и паритета адаптеров Memory vs PostgreSQL."""

from __future__ import annotations

import ast
import contextlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.entities import StationCard, TankDevice
from app.domain.errors import NotFoundError, ValidationError
from app.schemas.ingest import CalibrationIn, DispenseIngest, LevelIngest, ReceiptIngest
from app.services import account, boot, catalog, device_ingest, shelly_link
from app.services.board_cache import get_cached_board, invalidate_public_board_cache, set_cached_board
from app.services.shelly import ShellyError

BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _imported_modules(path: Path) -> list[tuple[str, bool]]:
    """Возвращает [(module_name, inside_function)] по AST файла."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, bool]] = []

    def _walk(node: ast.AST, in_func: bool) -> None:
        next_in_func = in_func or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, in_func))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, in_func))
        for child in ast.iter_child_nodes(node):
            _walk(child, next_in_func)

    _walk(tree, False)
    return found


def test_domain_layer_has_no_framework_schema_or_service_imports():
    forbidden = ("fastapi", "sqlalchemy", "app.schemas", "app.services", "app.models", "app.routers", "app.config")
    for path in sorted((BACKEND_APP / "domain").glob("*.py")):
        for mod, _ in _imported_modules(path):
            assert not mod.startswith(forbidden), f"{path.name} импортирует запрещённый модуль {mod}"


def test_services_do_not_import_fastapi():
    for path in sorted((BACKEND_APP / "services").glob("*.py")):
        for mod, _ in _imported_modules(path):
            assert not mod.startswith("fastapi"), f"{path.name} импортирует {mod}"


def test_postgres_adapter_does_not_import_memory_adapters_or_shelly():
    forbidden = (
        "app.services.batch_book",
        "app.services.catalog",
        "app.services.device_ingest",
        "app.services.station_accounts",
        "app.services.shift_book",
        "app.services.memory_account",
        "app.services.shelly_link",
    )
    pg_path = BACKEND_APP / "services" / "postgres_account.py"
    for mod, _ in _imported_modules(pg_path):
        assert not mod.startswith(forbidden), f"postgres_account.py импортирует {mod}"


def test_device_ingest_has_no_deferred_in_function_imports():
    di_path = BACKEND_APP / "services" / "device_ingest.py"
    deferred = [mod for mod, in_func in _imported_modules(di_path) if in_func]
    assert deferred == []


def test_routers_do_not_import_other_routers_except_deps():
    for path in sorted((BACKEND_APP / "routers").glob("*.py")):
        if path.name in ("__init__.py", "deps.py"):
            continue
        for mod, _ in _imported_modules(path):
            if mod.startswith("app.routers."):
                assert mod == "app.routers.deps", f"{path.name} импортирует другой роутер {mod}"


def test_boot_restore_memory_state_registers_all_stores(tmp_path, monkeypatch):
    from app.config import get_settings

    state_file = tmp_path / "boot_state.json"
    monkeypatch.setenv("STATE_PATH", str(state_file))
    monkeypatch.setenv("ACCOUNT_STORE", "memory")
    get_settings.cache_clear()
    catalog.reset_catalog()
    device_ingest.reset_device_ingest()
    shelly_link.reset_shelly_links()

    catalog.create_station(
        code="AGZS-BOOT",
        name="Boot",
        address=None,
        lat=43.6,
        lon=51.2,
        is_active=True,
    )
    assert state_file.is_file()

    catalog.reset_catalog()
    assert not any(row.code == "AGZS-BOOT" for row in catalog.list_stations())
    boot.restore_memory_state()
    assert any(row.code == "AGZS-BOOT" for row in catalog.list_stations())


def _offline_shelly():
    class _Offline:
        def call(self, host: str, method: str, params: dict | None = None) -> dict:
            raise ShellyError("offline")

    return _Offline()


@pytest.mark.parametrize("use_pg", [False, True])
def test_memory_and_postgres_adapter_parity(monkeypatch, use_pg):
    """Паритет: register_tank 404, accept_receipt 422, отвязка Shelly и сброс кэша витрины."""
    catalog.reset_catalog()
    device_ingest.reset_device_ingest()
    shelly_link.reset_shelly_links()
    invalidate_public_board_cache()

    fake_station_id = uuid4()
    fake_tank_id = uuid4()

    if not use_pg:
        monkeypatch.setattr("app.services.account_mode.use_postgres", lambda: False)
        real_station = catalog.create_station(
            code="AGZS-PAR",
            name="Parity",
            address=None,
            lat=43.6,
            lon=51.2,
            is_active=True,
        )
        sid = real_station.id
    else:
        monkeypatch.setattr("app.services.account_mode.use_postgres", lambda: True)
        sid = fake_station_id
        from app.services import postgres_account

        state_store = {"tanks": {fake_tank_id: sid}}

        def _get_station(target_id):
            if target_id != sid:
                raise NotFoundError("Station not found")
            return StationCard(sid, "AGZS-PAR", "Parity", None, 43.6, 51.2, True)

        def _get_tank(st_id, t_id):
            if state_store["tanks"].get(t_id) != st_id:
                raise NotFoundError("резервуар не найден")
            return TankDevice(st_id, t_id, "R-1", 10000.0, "tok")

        def _delete_tank(st_id, t_id):
            if state_store["tanks"].pop(t_id, None) != st_id:
                raise NotFoundError("резервуар не найден")

        def _delete_station(st_id):
            if st_id != sid:
                raise NotFoundError("Station not found")
            removed = [tid for tid, owner_sid in list(state_store["tanks"].items()) if owner_sid == st_id]
            for tid in removed:
                state_store["tanks"].pop(tid, None)
            return removed

        monkeypatch.setattr(postgres_account, "get_station", _get_station)
        monkeypatch.setattr(postgres_account, "get_tank_device", _get_tank)
        monkeypatch.setattr(postgres_account, "delete_tank_device", _delete_tank)
        monkeypatch.setattr(postgres_account, "delete_station", _delete_station)
        monkeypatch.setattr(
            postgres_account,
            "register_tank",
            lambda st_id, code, cap: TankDevice(st_id, fake_tank_id, code, cap, "tok"),
        )
        monkeypatch.setattr(
            postgres_account,
            "set_calibration",
            lambda body: SimpleNamespace(tank_id=body.tank_id, calibrated=True),
        )
        monkeypatch.setattr(
            postgres_account,
            "tank_state",
            lambda t_id: SimpleNamespace(tank_id=t_id, calibrated=True),
        )
        monkeypatch.setattr(
            postgres_account,
            "accept_level",
            lambda body: SimpleNamespace(duplicate=False, message="level accepted"),
        )
        monkeypatch.setattr(
            postgres_account,
            "accept_dispense",
            lambda body: SimpleNamespace(duplicate=False, message="dispense accepted"),
        )
        monkeypatch.setattr(
            postgres_account,
            "accept_receipt",
            lambda body: SimpleNamespace(duplicate=False, message="receipt accepted"),
        )

    # 1. register_tank на несуществующей станции -> 404 (NotFoundError)
    with pytest.raises(NotFoundError) as exc_404:
        account.register_tank(uuid4(), "R-X", 10000.0)
    assert exc_404.value.status_code == 404

    # 2. accept_receipt без station_id или tank_id -> 422 (ValidationError)
    bad_receipt = ReceiptIngest.model_construct(
        station_id=None,
        tank_id=None,
        volume_liters=100.0,
        recorded_at=datetime.now(timezone.utc),
        source_event_id="r-none",
    )
    with pytest.raises(ValidationError) as exc_422:
        account.accept_receipt(bad_receipt)
    assert exc_422.value.status_code == 422

    # 3. accept_level / accept_dispense / accept_receipt / set_calibration сбрасывают кэш витрины
    dev = account.register_tank(sid, "R-1", 10000.0)
    now = datetime.now(timezone.utc)

    for call in (
        lambda: account.set_calibration(
            CalibrationIn(
                station_id=sid,
                tank_id=dev.tank_id,
                capacity_liters=10000.0,
                low_volts=1.0,
                low_percent=0.0,
                high_volts=5.0,
                high_percent=100.0,
            )
        ),
        lambda: account.accept_level(
            LevelIngest(
                station_id=sid,
                tank_id=dev.tank_id,
                actual_remainder_liters=4000.0,
                recorded_at=now,
                source_event_id=f"lvl-{use_pg}",
            )
        ),
        lambda: account.accept_dispense(
            DispenseIngest(
                station_id=sid,
                tank_id=dev.tank_id,
                dispenser_id=uuid4(),
                volume_liters=25.0,
                started_at=now,
                external_txn_id=f"disp-{use_pg}",
            )
        ),
        lambda: account.accept_receipt(
            ReceiptIngest(
                station_id=sid,
                tank_id=dev.tank_id,
                volume_liters=500.0,
                recorded_at=now,
                source_event_id=f"rec-{use_pg}",
            )
        ),
    ):
        set_cached_board(["stale"])
        assert get_cached_board() == ["stale"]
        call()
        assert get_cached_board() is None

    # 4. delete_tank_device отвязывает Shelly и сбрасывает кэш витрины
    shelly_link.set_shelly_rpc(_offline_shelly())
    shelly_link.connect_shelly(sid, dev.tank_id, "192.168.0.104")
    assert shelly_link.shelly_view(dev.tank_id) is not None
    set_cached_board(["stale"])
    account.delete_tank_device(sid, dev.tank_id)
    assert shelly_link.shelly_view(dev.tank_id) is None
    assert get_cached_board() is None

    # 5. delete_station отвязывает Shelly со всех резервуаров станции и сбрасывает кэш
    if use_pg:
        state_store["tanks"][dev.tank_id] = sid
    else:
        dev = account.register_tank(sid, "R-2", 10000.0)
    shelly_link.connect_shelly(sid, dev.tank_id, "192.168.0.105")
    assert shelly_link.shelly_view(dev.tank_id) is not None
    set_cached_board(["stale"])
    account.delete_station(sid)
    assert shelly_link.shelly_view(dev.tank_id) is None
    assert get_cached_board() is None


def test_known_divergence_unregistered_tank_404_vs_memory_autocreate(monkeypatch):
    """KNOWN_PARITY_DIVERGENCE: явная фиксация единственного допустимого отличия Memory vs PostgreSQL.

    В режиме памяти приём телеметрии/наливов/приёмок для незарегистрированного tank_id
    автоматически создаёт TankBook для совместимости со старыми тестами, тогда как PostgreSQL
    строго возвращает NotFoundError (404). Удалить исключение после перевода тестов на общую
    фикстуру register_tank в conftest.py.
    """
    from app.services import postgres_account

    catalog.reset_catalog()
    device_ingest.reset_device_ingest()
    shelly_link.reset_shelly_links()
    invalidate_public_board_cache()

    sid = uuid4()
    unregistered_tank = uuid4()
    now = datetime.now(timezone.utc)

    level_payload = LevelIngest(
        station_id=sid,
        tank_id=unregistered_tank,
        actual_remainder_liters=4000.0,
        recorded_at=now,
        source_event_id="div-lvl",
    )
    dispense_payload = DispenseIngest(
        station_id=sid,
        tank_id=unregistered_tank,
        dispenser_id=uuid4(),
        volume_liters=25.0,
        started_at=now,
        external_txn_id="div-disp",
    )
    receipt_payload = ReceiptIngest(
        station_id=sid,
        tank_id=unregistered_tank,
        volume_liters=500.0,
        recorded_at=now,
        source_event_id="div-rec",
    )

    # 1. Режим памяти: автосоздаёт TankBook и принимает события
    monkeypatch.setattr("app.services.account_mode.use_postgres", lambda: False)
    assert account.accept_level(level_payload).accepted is True
    assert account.accept_dispense(dispense_payload).accepted is True
    assert account.accept_receipt(receipt_payload).accepted is True

    # 2. Режим PostgreSQL: строго 404 (NotFoundError) для незарегистрированного резервуара
    @contextlib.contextmanager
    def _empty_session():
        class _DummySession:
            def scalar(self, *args, **kwargs):
                return None

            def rollback(self) -> None:
                pass

        yield _DummySession()

    monkeypatch.setattr("app.services.account_mode.use_postgres", lambda: True)
    monkeypatch.setattr(postgres_account, "session", _empty_session)

    for call in (
        lambda: account.accept_level(level_payload),
        lambda: account.accept_dispense(dispense_payload),
        lambda: account.accept_receipt(receipt_payload),
    ):
        with pytest.raises(NotFoundError) as exc:
            call()
        assert exc.value.status_code == 404


def test_deploy_hardening_guards():
    """Проверяет защитные флаги деплоя: --workers 1, fail-closed подпись OTA и проброс ключа на VPS."""
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert '"--workers", "1"' in dockerfile

    edge_env = (REPO_ROOT / "station-edge" / ".env.example").read_text(encoding="utf-8")
    assert "AGZS_REQUIRE_RELEASE_SIGNATURE=1" in edge_env

    updater_unit = (REPO_ROOT / "station-edge" / "station-edge-updater.service").read_text(encoding="utf-8")
    assert "Environment=AGZS_REQUIRE_RELEASE_SIGNATURE=1" in updater_unit

    ansible_playbook = (REPO_ROOT / "deploy" / "fleet" / "update-stations.yml").read_text(encoding="utf-8")
    assert "require_release_signature: true" in ansible_playbook
    assert "AGZS_REQUIRE_RELEASE_SIGNATURE" in ansible_playbook
    assert "station-edge-updater" in ansible_playbook
    assert "/var/lib/station-edge" in ansible_playbook
    assert "station_edge.db" in ansible_playbook
    assert "cryptography>=42.0" in ansible_playbook
    assert "station-edge-monitor.service" in ansible_playbook

    compose = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    deploy_env = (REPO_ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    assert "EDGE_RELEASE_SIGNING_KEY" in compose
    assert "EDGE_RELEASE_SIGNING_KEY" in deploy_env
    assert "EDGE_RELEASE_PRIVATE_KEY" in compose
    assert "EDGE_RELEASE_PUBLIC_KEY" in compose


def test_edge_release_signing_module_in_sync():
    """Контракт канонической строки и Ed25519/HMAC подписи совпадает побайтово в backend и station-edge."""
    backend_signing = (BACKEND_APP / "domain" / "edge_release.py").read_text(encoding="utf-8")
    edge_signing = (REPO_ROOT / "station-edge" / "agzs_edge" / "release_signing.py").read_text(
        encoding="utf-8"
    )
    assert backend_signing == edge_signing
