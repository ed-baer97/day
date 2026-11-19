"""Тесты консольного монитора смены и вывода статистики на /dev/tty1."""

import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import build_test_response_frame, parse_iskra_frame
from agzs_edge.main import main
from agzs_edge.monitor import (
    build_shift_snapshot,
    install_kiosk_signal_handlers,
    render_shift_dashboard,
    resolve_shift_window,
)
from agzs_edge.storage import EdgeDatabase
from agzs_edge.tracker import CompletedDispense


def _tz_plus_5() -> timezone:
    return timezone(timedelta(hours=5))


def test_resolve_shift_window_day_night_and_24h() -> None:
    tz = _tz_plus_5()

    # Дневная смена: 08:00 - 20:00
    day_now = datetime(2026, 11, 18, 14, 25, 0, tzinfo=tz)
    day_win = resolve_shift_window(day_now, shift_start_hour=8, shift_hours=12)
    assert day_win.label == "Дневная смена"
    assert day_win.start == datetime(2026, 11, 18, 8, 0, 0, tzinfo=tz)
    assert day_win.end == datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz)

    # Ночная смена вечером: 20:00 - 08:00 следующего дня
    night_evening = datetime(2026, 11, 18, 22, 10, 0, tzinfo=tz)
    evening_win = resolve_shift_window(night_evening, shift_start_hour=8, shift_hours=12)
    assert evening_win.label == "Ночная смена"
    assert evening_win.start == datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz)
    assert evening_win.end == datetime(2026, 11, 19, 8, 0, 0, tzinfo=tz)

    # Ночная смена после полуночи (03:45 19-го относится к ночной смене с 18-го 20:00)
    night_morning = datetime(2026, 11, 19, 3, 45, 0, tzinfo=tz)
    morning_win = resolve_shift_window(night_morning, shift_start_hour=8, shift_hours=12)
    assert morning_win.label == "Ночная смена"
    assert morning_win.start == datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz)
    assert morning_win.end == datetime(2026, 11, 19, 8, 0, 0, tzinfo=tz)

    # Суточная смена: 24 часа
    full_win = resolve_shift_window(night_morning, shift_start_hour=8, shift_hours=24)
    assert full_win.label == "Суточная смена"
    assert full_win.start == datetime(2026, 11, 18, 8, 0, 0, tzinfo=tz)
    assert full_win.end == datetime(2026, 11, 19, 8, 0, 0, tzinfo=tz)


def test_shift_snapshot_filters_previous_shift_and_calculates_totals(tmp_path: Path) -> None:
    tz = _tz_plus_5()
    db_path = tmp_path / "station_edge.db"
    db = EdgeDatabase(db_path)

    # Обновляем живое состояние колонки #2 (цена 75.00), чтобы проверить fallback цены при 0.0 в кадре завершения
    frame_p2 = parse_iskra_frame(
        build_test_response_frame(address=2, state_code="05", price_digits=7500, volume_ml=0)
    )
    db.update_live_state(frame_p2, observed_at=datetime(2026, 11, 18, 12, 0, 0, tzinfo=tz))

    # Заправка из прошлой ночной смены (не должна попасть в дневную смену 08:00..20:00)
    prev_disp = CompletedDispense(
        external_txn_id="txn-prev-shift",
        pump_address=1,
        mode="dose",
        preset_ml=10000,
        dispensed_ml=10000,
        volume_liters=10.0,
        price_kzt_per_liter=70.0,
        final_state_code="07",
        error_code="00",
        started_at=datetime(2026, 11, 18, 7, 50, 0, tzinfo=tz),
        finished_at=datetime(2026, 11, 18, 7, 55, 0, tzinfo=tz),
        last_raw_frame_hex="01 31 34",
    )
    # Заправка колонки #1 в текущей дневной смене
    cur_disp_1 = CompletedDispense(
        external_txn_id="txn-cur-1",
        pump_address=1,
        mode="dose",
        preset_ml=20000,
        dispensed_ml=20000,
        volume_liters=20.0,
        price_kzt_per_liter=72.5,
        final_state_code="07",
        error_code="00",
        started_at=datetime(2026, 11, 18, 10, 14, 0, tzinfo=tz),
        finished_at=datetime(2026, 11, 18, 10, 15, 30, tzinfo=tz),
        last_raw_frame_hex="01 31 34",
    )
    # Заправка колонки #2 в текущей смене с price=0.0 -> подставится цена из pump_live_state (75.0)
    cur_disp_2 = CompletedDispense(
        external_txn_id="txn-cur-2",
        pump_address=2,
        mode="full_tank",
        preset_ml=None,
        dispensed_ml=12000,
        volume_liters=12.0,
        price_kzt_per_liter=0.0,
        final_state_code="07",
        error_code="00",
        started_at=datetime(2026, 11, 18, 11, 40, 0, tzinfo=tz),
        finished_at=datetime(2026, 11, 18, 11, 42, 10, tzinfo=tz),
        last_raw_frame_hex="01 32 34",
    )

    for item in (prev_disp, cur_disp_1, cur_disp_2):
        db.record_completed_dispense(
            item,
            station_id="a2222222-2222-2222-2222-222222222201",
            dispenser_id=f"d2222222-2222-2222-2222-22222222220{item.pump_address}",
            tank_id="b2222222-2222-2222-2222-222222222201",
        )

    settings = EdgeSettings(
        db_path=db_path,
        pump_addresses=(1, 2),
        station_code="AKT-12MKR",
        shift_start_hour=8,
        shift_hours=12,
        currency_symbol="₸",
    )
    ro_db = EdgeDatabase(db_path, read_only=True)
    now = datetime(2026, 11, 18, 12, 30, 0, tzinfo=tz)

    between = ro_db.list_dispenses_between(
        datetime(2026, 11, 18, 8, 0, 0, tzinfo=tz),
        datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz),
    )
    assert [row.external_txn_id for row in between] == ["txn-cur-2", "txn-cur-1"]

    snapshot = build_shift_snapshot(ro_db, settings, now=now)
    assert snapshot.total_dispenses == 2
    assert snapshot.total_volume_liters == 32.0
    # 20 * 72.5 = 1450.0, 12 * 75.0 = 900.0 -> итого 2350.0
    assert snapshot.total_amount == 2350.0

    p1, p2 = snapshot.pumps
    assert p1.pump_address == 1
    assert p1.dispense_count == 1
    assert p1.total_volume_liters == 20.0
    assert p1.total_amount == 1450.0
    assert p1.last_time_str == "10:15:30"

    assert p2.pump_address == 2
    assert p2.dispense_count == 1
    assert p2.total_volume_liters == 12.0
    assert p2.total_amount == 900.0
    assert p2.last_time_str == "11:42:10"

    rendered = render_shift_dashboard(snapshot, kiosk=True)
    assert "AKT-12MKR" in rendered
    assert "#1" in rendered and "#2" in rendered
    assert "10:15:30" in rendered and "11:42:10" in rendered
    assert "20.00" in rendered and "12.00" in rendered
    assert "1 450.00 ₸" in rendered and "900.00 ₸" in rendered
    assert "ИТОГО ЗА СМЕНУ" in rendered
    assert "2 350.00 ₸" in rendered
    assert "Режим киоска tty1" in rendered
    for line in rendered.splitlines():
        assert len(line) <= 80, f"Строка превышает 80 символов ({len(line)}): {line}"


def test_read_only_missing_db_and_cli_monitor_once(tmp_path: Path, monkeypatch, capsys) -> None:
    missing_db = tmp_path / "not_created_yet.db"
    ro_db = EdgeDatabase(missing_db, read_only=True)

    # Read-only обращение не создаёт файл БД и не падает
    assert ro_db.list_dispenses() == []
    assert ro_db.list_dispenses_between(datetime.now(timezone.utc) - timedelta(hours=12)) == []
    assert ro_db.summary()["total_dispenses"] == 0
    assert not missing_db.exists()

    env_file = tmp_path / ".env"
    env_file.write_text(
        f"AGZS_DB_PATH={missing_db}\nAGZS_STATION_CODE=TEST-AZS\nAGZS_PUMP_ADDRESSES=1,2\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AGZS_DB_PATH", raising=False)
    monkeypatch.delenv("AGZS_STATION_CODE", raising=False)
    monkeypatch.delenv("AGZS_PUMP_ADDRESSES", raising=False)

    rc = main(["--env-file", str(env_file), "monitor", "--once", "--currency", "₽"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "TEST-AZS" in out
    assert "ИТОГО ЗА СМЕНУ" in out
    assert "0.00 ₽" in out
    assert not missing_db.exists()


def test_install_kiosk_signal_handlers(monkeypatch) -> None:
    recorded: list[tuple[int, object]] = []
    monkeypatch.setattr(signal, "signal", lambda sig, handler: recorded.append((sig, handler)))

    install_kiosk_signal_handlers()

    sigs = {sig for sig, _ in recorded}
    assert signal.SIGINT in sigs
    assert all(handler == signal.SIG_IGN for _, handler in recorded)


def test_monitor_loop_and_edge_formatting(monkeypatch, tmp_path: Path, capsys) -> None:
    """Живой цикл run_monitor_loop(once=False), пустой список колонок и сжатие больших сумм."""
    from agzs_edge.monitor import _format_money, _format_price, run_monitor_loop

    assert _format_money(12_345_678.90, "₸", width=12) == "12 345 679 ₸"
    assert _format_price(1234.56, "₸", width=8) == "1234.56"

    empty_settings = EdgeSettings(
        db_path=tmp_path / "empty.db",
        pump_addresses=(),
        station_code="EMPTY",
        monitor_refresh_sec=0.1,
    )
    snap = build_shift_snapshot(EdgeDatabase(empty_settings.db_path, read_only=True), empty_settings)
    rendered = render_shift_dashboard(snap)
    assert "Нет настроенных колонок" in rendered

    sleep_calls = 0

    def _fake_sleep(_sec: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise KeyboardInterrupt()

    monkeypatch.setattr("agzs_edge.monitor.time.sleep", _fake_sleep)
    rc = run_monitor_loop(empty_settings, once=False, refresh_sec=0.05, kiosk=True)
    assert rc == 0
    assert sleep_calls == 2
    out = capsys.readouterr().out
    assert "EMPTY" in out


def test_config_case_insensitive_booleans_and_validations(monkeypatch, tmp_path: Path) -> None:
    """Регистронезависимые булевы флаги, EdgeSettings.__post_init__ и валидации в config.py."""
    import pytest

    monkeypatch.setenv("AGZS_SAVE_RAW_FRAMES", "TRUE")
    monkeypatch.setenv("AGZS_SYNC_ENABLED", "False")
    monkeypatch.setenv("AGZS_READ_ONLY", "FALSE")
    monkeypatch.setenv("AGZS_MONITOR_KIOSK", "Yes")
    monkeypatch.setenv("AGZS_DB_PATH", str(tmp_path / "cfg.db"))
    settings = EdgeSettings.from_env(tmp_path / "missing.env")
    assert settings.save_raw_frames is True
    assert settings.sync_enabled is False
    assert settings.read_only is False
    assert settings.monitor_kiosk is True

    direct = EdgeSettings(auto_reset_on_stop=True, read_only=True)
    assert direct.read_only is False

    monkeypatch.setenv("AGZS_DISPENSER_MAP", "9:a2222222-2222-2222-2222-222222222201")
    with pytest.raises(ValueError, match="1..8"):
        EdgeSettings.from_env(tmp_path / "missing.env")
    monkeypatch.delenv("AGZS_DISPENSER_MAP", raising=False)

    monkeypatch.setenv("AGZS_POLL_INTERVAL_SEC", "-1")
    with pytest.raises(ValueError, match="AGZS_POLL_INTERVAL_SEC"):
        EdgeSettings.from_env(tmp_path / "missing.env")
    monkeypatch.setenv("AGZS_POLL_INTERVAL_SEC", "0.5")

    for bad_key, bad_val in [
        ("AGZS_PUMP_ADDRESSES", "0"),
        ("AGZS_PUMP_ADDRESSES", " , "),
        ("AGZS_SERIAL_BAUDRATE", "0"),
        ("AGZS_SERIAL_TIMEOUT_SEC", "0"),
        ("AGZS_SOURCE_MODE", "unknown"),
        ("AGZS_AUTO_RESET_DELAY_SEC", "-1"),
        ("AGZS_ISKRA_CHECKSUM_MODE", "crc"),
        ("AGZS_SYNC_INTERVAL_SEC", "-1"),
        ("AGZS_SHIFT_START_HOUR", "25"),
        ("AGZS_SHIFT_HOURS", "0"),
        ("AGZS_MONITOR_REFRESH_SEC", "0"),
    ]:
        monkeypatch.setenv(bad_key, bad_val)
        with pytest.raises(ValueError):
            EdgeSettings.from_env(tmp_path / "missing.env")
        monkeypatch.delenv(bad_key, raising=False)

    assert len(settings.dispenser_uuid(5)) == 36
    assert len(settings.dispenser_uuid(99)) == 36


def test_cli_commands_end_to_end(monkeypatch, tmp_path: Path, capsys) -> None:
    """Проверка CLI-команд main.py: diagnose, listen, watch-fill, buttons, set-dose, start, stop, set-price, console, status, flush."""
    db_path = tmp_path / "cli_all.db"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"AGZS_DB_PATH={db_path}\nAGZS_POLL_INTERVAL_SEC=0\nAGZS_SYNC_ENABLED=1\n",
        encoding="utf-8",
    )
    for k in (
        "AGZS_DB_PATH",
        "AGZS_POLL_INTERVAL_SEC",
        "AGZS_SYNC_ENABLED",
        "AGZS_SOURCE_MODE",
        "AGZS_SERIAL_PORT",
    ):
        monkeypatch.delenv(k, raising=False)

    # 1. Управление УЗСГ-01 на имитаторе
    assert main(["--env-file", str(env_file), "buttons", "--emulator", "--addr", "1", "--mode", "enable"]) == 0
    assert main(["--env-file", str(env_file), "set-price", "--emulator", "--addr", "1", "--price", "78.50"]) == 0
    assert main(["--env-file", str(env_file), "set-dose", "--emulator", "--addr", "1"]) == 2
    assert main(["--env-file", str(env_file), "set-dose", "--emulator", "--addr", "1", "--liters", "10"]) == 0
    assert main(["--env-file", str(env_file), "start", "--emulator", "--addr", "1", "--liters", "10"]) == 0
    assert main(["--env-file", str(env_file), "stop", "--emulator", "--addr", "1", "--force"]) == 0

    # 2. Интерактивный пульт оператора
    cmds = iter(["t", "r", "df", "s", "x", "r", "p 74.00", "b lock", "c", "unknown", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(cmds))
    assert main(["--env-file", str(env_file), "console", "--emulator", "--addr", "1"]) == 0

    # 3. listen, watch-fill и diagnose (+ невалидный --addr -> 2)
    assert main(["--env-file", str(env_file), "listen", "--emulator", "--addr", "1", "--count", "2"]) == 0
    assert main(["--env-file", str(env_file), "listen", "--emulator", "--addr", "9"]) == 2
    assert main(["--env-file", str(env_file), "watch-fill", "--emulator", "--addr", "1", "--seconds", "0.02", "--idle", "0.01"]) == 0
    assert main(["--env-file", str(env_file), "watch-fill", "--emulator", "--addr", "9"]) == 2
    assert main(["--env-file", str(env_file), "diagnose", "--addr", "9"]) == 2

    from agzs_edge.diagnose import DiagnoseReport

    monkeypatch.setattr("agzs_edge.diagnose.run_diagnose", lambda s, address=1: DiagnoseReport(status="CONNECTED"))
    assert main(["--env-file", str(env_file), "diagnose", "--port", "COM7", "--addr", "1"]) == 0

    # 4. serve -> status --json -> flush
    assert main(["--env-file", str(env_file), "serve", "--emulator", "--no-sync", "--cycles", "8"]) == 0
    assert main(["--env-file", str(env_file), "status", "--json", "--limit", "5"]) == 0
    status_out = capsys.readouterr().out
    assert '"total_dispenses": 2' in status_out

    monkeypatch.setattr("agzs_edge.sync.OutboxSyncWorker.flush_due", lambda self, limit=50: (2, 0))
    assert main(["--env-file", str(env_file), "flush", "--limit", "50"]) == 0
