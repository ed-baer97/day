"""Тесты контроллера «Компьютер — АСКА-02 — БП — УЗСГ-01», автосброса и закрытия SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import (
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_STOPPED,
    build_reset_command,
    parse_iskra_frame,
)
from agzs_edge.main import main
from agzs_edge.psu_controller import (
    PsuControlError,
    Uzsg01PsuController,
    format_detailed_status,
)
from agzs_edge.serial_link import EmulatorAskaLink, PollRawResult
from agzs_edge.service import StationEdgeService
from agzs_edge.storage import EdgeDatabase


class _ScriptedLink:
    """Подмена AskaLink с заданной очередью байтовых ответов на каждый TX."""

    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self.sent: list[bytes] = []

    def open(self) -> None:
        return

    def close(self) -> None:
        return

    def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
        from agzs_edge.iskra import build_test_command

        req = build_test_command(address, checksum_mode=checksum_mode or "xor")
        return self.send_command(address, req)

    def send_command(self, address: int, request: bytes) -> PollRawResult:
        self.sent.append(request)
        resp = self._responses.pop(0) if self._responses else b""
        return PollRawResult(address=address, request_bytes=request, response_bytes=resp)


def test_unlock_from_captured_stop07_frame() -> None:
    """Перехваченный кадр блокировки 07 (50 8A) разблокируется командой 0x37 в состояние 05 (007200)."""
    captured_stop07 = bytes.fromhex("01 30 31 34 02 30 39 30 30 30 30 30 30 30 30 30 30 50 8A 30 37 03 E0")
    captured_reset_reply = bytes.fromhex("01 30 31 37 02 30 30 37 32 30 30 30 30 30 30 30 30 50 8A 30 35 03 ED")
    captured_confirm_05 = bytes.fromhex("01 30 31 34 02 30 30 37 32 30 30 30 30 30 30 30 30 50 8A 30 35 03 EE")

    parsed_before = parse_iskra_frame(captured_stop07)
    assert parsed_before.is_locked_in_stop is True
    assert parsed_before.start_stop_buttons_enabled is True
    assert parsed_before.reset_button_enabled is False
    assert parsed_before.valve_open is False

    details = format_detailed_status(parsed_before)
    assert "ЗАБЛОКИРОВАНА" in details
    assert "0x37" in details

    link = _ScriptedLink([captured_stop07, captured_reset_reply, captured_confirm_05])
    ctrl = Uzsg01PsuController(link)
    res = ctrl.reset_column(1)

    assert res.reset_sent is True
    assert res.unlocked is True
    assert res.before.state_code == STATE_COMPLETED
    assert res.after.state_code == STATE_IDLE
    assert res.after.price_kzt_per_liter == 72.0
    assert link.sent[1] == build_reset_command(1)
    assert len(link.sent) == 3


def test_full_pc_control_cycle_without_console() -> None:
    """Полный цикл управления без ПУ: Сброс(0x37) -> Доза(0x39) -> Пуск(0x35) -> Тест(0x34) -> Стоп(0x36) -> Сброс(0x37)."""
    link = EmulatorAskaLink(price_digits=7200, initial_locked=True)
    ctrl = Uzsg01PsuController(link)

    # 1. Колонка заблокирована в '07' — сбрасываем в '05'
    reset1 = ctrl.reset_column(1)
    assert reset1.unlocked is True
    assert reset1.after.state_code == STATE_IDLE

    # 2. Задаём дозу 20 л (20000 мл) -> состояние '01'
    dose_frame = ctrl.preset_dose(1, liters=20.0)
    assert dose_frame.state_code == STATE_DOSE_SET
    assert dose_frame.dose_type_bits == 0x11

    # 3. Пуск -> состояние '03', клапан открыт
    start_frame = ctrl.start_pump(1)
    assert start_frame.state_code == STATE_DISPENSING
    assert start_frame.valve_open is True

    # 4. Опрос во время налива -> объём растёт
    poll_frame = ctrl.get_status(1)
    assert poll_frame.state_code == STATE_DISPENSING
    assert poll_frame.volume_ml == 500

    # 5. Останов -> состояние '04', клапан закрыт
    stop_frame = ctrl.stop_pump(1)
    assert stop_frame.state_code == STATE_STOPPED
    assert stop_frame.valve_open is False

    # 6. Финальный сброс -> состояние '05'
    reset2 = ctrl.reset_column(1)
    assert reset2.unlocked is True
    assert reset2.after.state_code == STATE_IDLE


def test_buttons_price_and_counters_commands() -> None:
    """Управление кнопками колонки (0.16/0.17/0.18), установка цены (0.15) и чтение счётчиков (0.11/0.12/0.14)."""
    link = EmulatorAskaLink(price_digits=7200)
    ctrl = Uzsg01PsuController(link)

    # Включение всех кнопок на колонке (включая СБРОС)
    f_en = ctrl.set_buttons_mode(1, "enable")
    assert f_en.start_stop_buttons_enabled is True
    assert f_en.reset_button_enabled is True

    # Выключение кнопок на колонке
    f_dis = ctrl.set_buttons_mode(1, "disable")
    assert f_dis.start_stop_buttons_enabled is False
    assert f_dis.reset_button_enabled is False

    # Блокировка только СБРОС (0.18)
    f_lock = ctrl.set_buttons_mode(1, "lock-reset")
    assert f_lock.start_stop_buttons_enabled is True
    assert f_lock.reset_button_enabled is False

    # Установка цены 85.50
    f_price = ctrl.set_price(1, 85.50)
    assert f_price.state_code == STATE_IDLE
    assert f_price.price_kzt_per_liter == 85.50

    # Чтение счётчиков и возврат в '05'
    report = ctrl.read_counters(1)
    assert report.total_counter_1_value == 1234.56
    assert report.total_counter_2_value == 1234.56
    assert report.daily_counter_value == 45.00
    assert report.temperature_c == 21.5
    assert report.propane_percent == 65
    assert report.tpr_liters_per_pulse == pytest.approx(0.001234)
    assert report.final_status.state_code == STATE_IDLE
    assert "1234.56" in report.render()


def test_reset_refuses_while_dispensing_without_force() -> None:
    link = EmulatorAskaLink(price_digits=7200)
    ctrl = Uzsg01PsuController(link)
    ctrl.start_pump(1, full_tank=True)
    with pytest.raises(PsuControlError, match="налив"):
        ctrl.reset_column(1)


def test_auto_reset_on_stop_in_service_poll_cycle(tmp_path: Path) -> None:
    """При auto_reset_on_stop=True сервис автоматически шлёт 0x37 при блокировке колонки в '07'."""
    captured_stop07 = bytes.fromhex("01 30 31 34 02 30 39 30 30 30 30 30 30 30 30 30 30 50 8A 30 37 03 E0")
    captured_reset_reply = bytes.fromhex("01 30 31 37 02 30 30 37 32 30 30 30 30 30 30 30 30 50 8A 30 35 03 ED")

    link = _ScriptedLink([captured_stop07, captured_reset_reply])
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "auto_reset.db",
        sync_enabled=False,
        read_only=False,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=0.0,
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=link, db=db)

    svc.poll_cycle_once(observed_at=datetime.now(timezone.utc))

    assert len(link.sent) == 2
    assert link.sent[1] == build_reset_command(1)
    pumps = db.summary()["pumps"]
    assert isinstance(pumps, list) and len(pumps) == 1
    assert pumps[0]["state_code"] == STATE_IDLE


def test_sqlite_connections_are_closed_on_every_operation(monkeypatch, tmp_path: Path) -> None:
    """Каждое обращение к EdgeDatabase должно закрывать sqlite3.Connection без утечки дескрипторов."""
    opened = 0
    closed = 0
    real_connect = sqlite3.connect

    class _TrackedConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_conn", conn)

        def close(self) -> None:
            nonlocal closed
            closed += 1
            self._conn.close()

        def __enter__(self):
            self._conn.__enter__()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._conn.__exit__(exc_type, exc_val, exc_tb)

        def __getattr__(self, name: str):
            return getattr(self._conn, name)

        def __setattr__(self, name: str, value) -> None:
            setattr(self._conn, name, value)

    def _tracked_connect(*args, **kwargs):
        nonlocal opened
        opened += 1
        return _TrackedConn(real_connect(*args, **kwargs))

    monkeypatch.setattr("agzs_edge.storage.sqlite3.connect", _tracked_connect)

    db = EdgeDatabase(tmp_path / "leak_check.db")
    frame = parse_iskra_frame(
        bytes.fromhex("01 30 31 34 02 30 30 37 32 30 30 30 30 30 30 30 30 50 8E 30 35 03 EA")
    )
    for _ in range(100):
        db.update_live_state(frame)
    summary = db.summary()
    assert summary["pumps"][0]["state_code"] == "05"
    assert opened >= 102
    assert closed == opened


def test_env_allows_read_only_zero_and_auto_reset(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGZS_READ_ONLY", "0")
    monkeypatch.setenv("AGZS_AUTO_RESET", "1")
    monkeypatch.setenv("AGZS_AUTO_RESET_DELAY_SEC", "1.5")
    settings = EdgeSettings.from_env(tmp_path / "missing.env")
    assert settings.read_only is False
    assert settings.auto_reset_on_stop is True
    assert settings.auto_reset_delay_sec == 1.5


def test_cli_emulator_commands_run_cleanly(capsys, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGZS_DB_PATH", str(tmp_path / "cli_emu.db"))
    assert main(["unlock", "--emulator", "--addr", "1"]) == 0
    out_unlock = capsys.readouterr().out
    assert "05" in out_unlock

    assert main(["counters", "--emulator", "--addr", "1"]) == 0
    out_cnt = capsys.readouterr().out
    assert "1234.56" in out_cnt

    assert main(["serve", "--emulator", "--auto-reset", "--cycles", "8", "--no-sync"]) == 0
