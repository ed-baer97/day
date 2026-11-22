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

    assert link.sent[1] == build_reset_command(1)
    from agzs_edge.iskra import build_param_command
    assert link.sent[2] == build_param_command(1, "0.16")
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


def test_env_defaults_to_power_supply_cycle(monkeypatch, tmp_path: Path) -> None:
    """Без явных флагов служба с блоком питания сама возвращает колонку из '07' и не шлёт 0x38."""
    for key in (
        "AGZS_READ_ONLY",
        "AGZS_AUTO_RESET",
        "AGZS_AUTO_RESET_STOPPED_DELAY_SEC",
        "AGZS_LOCK_BUTTONS_ON_UPDATE",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = EdgeSettings.from_env(tmp_path / "missing.env")
    assert settings.auto_reset_on_stop is True
    assert settings.read_only is False
    assert settings.auto_reset_delay_sec == 15.0
    assert settings.auto_reset_stopped_delay_sec == 0.0
    assert settings.lock_buttons_on_update is False


def test_read_only_overrides_auto_reset_and_blocks_0x37(monkeypatch, tmp_path: Path) -> None:
    """AGZS_READ_ONLY=1 / read_only=True выключает автосброс 0x37 и блокирует его в _maybe_auto_reset."""
    direct = EdgeSettings(read_only=True)
    assert direct.read_only is True
    assert direct.auto_reset_on_stop is False

    monkeypatch.setenv("AGZS_READ_ONLY", "1")
    monkeypatch.delenv("AGZS_AUTO_RESET", raising=False)
    env_only_ro = EdgeSettings.from_env(tmp_path / "ro_default_reset.env")
    assert env_only_ro.read_only is True
    assert env_only_ro.auto_reset_on_stop is False

    monkeypatch.setenv("AGZS_AUTO_RESET", "1")
    env_conflict = EdgeSettings.from_env(tmp_path / "ro_with_reset.env")
    assert env_conflict.read_only is True
    assert env_conflict.auto_reset_on_stop is False

    captured_stop07 = bytes.fromhex("01 30 31 34 02 30 39 30 30 30 30 30 30 30 30 30 30 50 8A 30 37 03 E0")

    class _ReadOnlySpyLink:
        def __init__(self) -> None:
            self.poll_calls = 0
            self.send_command_calls: list[bytes] = []

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            from agzs_edge.iskra import build_test_command

            self.poll_calls += 1
            return PollRawResult(
                address=address,
                request_bytes=build_test_command(address, checksum_mode=checksum_mode or "xor"),
                response_bytes=captured_stop07,
            )

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.send_command_calls.append(request)
            return PollRawResult(address=address, request_bytes=request, response_bytes=b"")

    link = _ReadOnlySpyLink()
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "read_only_service.db",
        sync_enabled=False,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=0.0,
    )
    settings.read_only = True
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=link, db=db)

    svc.poll_cycle_once(observed_at=datetime.now(timezone.utc))

    assert link.poll_calls == 1
    assert link.send_command_calls == []
    assert svc._stop_07_since == {}  # noqa: SLF001


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


def test_set_buttons_refuses_while_dispensing_and_read_counters_mass_mode() -> None:
    """set_buttons_mode запрещён во время налива '03'; read_counters сбрасывает '07' и читает массу/плотность."""
    link = EmulatorAskaLink(price_digits=7200)
    ctrl = Uzsg01PsuController(link)

    ctrl.start_pump(1, liters=1.5)
    with pytest.raises(PsuControlError, match="налива"):
        ctrl.set_buttons_mode(1, "enable")

    # Имитатор завершает дозу 1.5 л (1500 мл): первый опрос в set_buttons_mode -> 500, затем 1000 и 1500 ('07')
    f1 = ctrl.get_status(1)
    assert f1.state_code == STATE_DISPENSING
    assert f1.volume_ml == 1000
    f2 = ctrl.get_status(1)
    assert f2.state_code == STATE_COMPLETED
    assert f2.volume_ml == 1500
    assert f2.valve_open is False

    # read_counters сам сбрасывает '07' -> '05' и читает показания в килограммах
    mass_report = ctrl.read_counters(1, mass=True)
    assert mass_report.mass_mode is True
    assert mass_report.density_kg_m3 == pytest.approx(0.54)
    assert mass_report.final_status.state_code == STATE_IDLE
    assert "кг" in mass_report.render()


def test_psu_controller_protocol_and_port_errors() -> None:
    """Проверка ошибок COM-порта, пустого RX, битого кадра и чужого адреса в Uzsg01PsuController."""
    from agzs_edge.iskra import build_test_response_frame

    class _ErrLink:
        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            return self.send_command(address, b"")

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            return PollRawResult(address=address, request_bytes=request, response_bytes=b"", error_message="COM error")

    with pytest.raises(PsuControlError, match="Ошибка COM-порта"):
        Uzsg01PsuController(_ErrLink()).get_status(1)

    with pytest.raises(PsuControlError, match="RX=0 байт"):
        Uzsg01PsuController(_ScriptedLink([b""])).get_status(1)

    with pytest.raises(PsuControlError, match="Некорректный кадр"):
        Uzsg01PsuController(_ScriptedLink([b"\x01BAD"])).get_status(1)

    wrong_addr_reply = build_test_response_frame(address=2, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)
    with pytest.raises(PsuControlError, match="ожидалась #1"):
        Uzsg01PsuController(_ScriptedLink([wrong_addr_reply])).get_status(1)


def test_emulator_auto_reset_continues_across_multiple_cycles(tmp_path: Path) -> None:
    """При serve с --auto-reset имитатор продолжает цикл наливов и после первого авто-сброса."""
    settings = EdgeSettings(
        source_mode="emulator",
        pump_addresses=(1,),
        poll_interval_sec=0.0,
        db_path=tmp_path / "multi_cycles.db",
        sync_enabled=False,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=0.0,
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, db=db)
    svc.serve(max_cycles=16)

    info = db.summary()
    assert info["total_dispenses"] == 2
    assert info["total_dispensed_ml"] == 40000


def test_psu_controller_guards_and_edge_cases() -> None:
    """Граничные проверки Uzsg01PsuController: неверные параметры, запреты при наливе, старт из '07'."""
    link = EmulatorAskaLink(price_digits=7200, initial_locked=True)
    ctrl = Uzsg01PsuController(link)

    with pytest.raises(ValueError, match="режим кнопок"):
        ctrl.set_buttons_mode(1, "bad-mode")
    with pytest.raises(ValueError, match="положительный"):
        ctrl.preset_dose(1, liters=0)
    with pytest.raises(ValueError, match="1..999999"):
        ctrl.preset_dose(1, liters=1500)
    with pytest.raises(ValueError, match="больше 0"):
        ctrl.set_price(1, 0)
    with pytest.raises(ValueError, match="вне диапазона"):
        ctrl.set_price(1, 10000)

    # Старт из блокировки '07' без параметров сам сбрасывает в '05', задаёт 999 л и запускает
    started = ctrl.start_pump(1)
    assert started.state_code == STATE_DISPENSING

    # Запреты во время активного налива
    with pytest.raises(PsuControlError):
        ctrl.preset_dose(1, liters=5)
    with pytest.raises(PsuControlError):
        ctrl.set_price(1, 75.0)
    with pytest.raises(PsuControlError):
        ctrl.read_counters(1)

    stopped = ctrl.stop_pump(1)
    assert stopped.state_code == STATE_STOPPED
    with pytest.raises(PsuControlError, match="невозможен"):
        ctrl.stop_pump(1)


def test_set_price_handshake_retries_cancel_and_read_counters_reset_retry() -> None:
    """set_price проверяет 0x16/0x30 с повтором и отменяет через 0x37 при отказе; read_counters повторяет 0x37 до 0x10."""
    from agzs_edge.iskra import (
        CMD_PARAMS_ASCII,
        CMD_RESET_ASCII,
        CMD_STOP_ASCII,
        CMD_TEST_ASCII,
        ETX,
        SOH,
        STX,
        compute_bcc,
    )
    from agzs_edge.psu_controller import send_buttons_param_to_pumps

    def _raw(cmd: int, price: bytes, vol: bytes, b17: int, b18: int, state: str = "05") -> bytes:
        body = b"01" + bytes([cmd, STX]) + price + vol + bytes([b17, b18]) + state.encode("ascii") + bytes([ETX])
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    idle_05 = _raw(CMD_TEST_ASCII, b"007200", b"000000", 0x50, 0x8A)
    not_ready_yet = _raw(CMD_TEST_ASCII, b"007200", b"000000", 0x50, 0x8A)
    ready_16 = _raw(CMD_TEST_ASCII, b"007200", b"000000", 0x16, 0x8A)
    stop_not_30 = _raw(CMD_STOP_ASCII, b"007200", b"000000", 0x16, 0x8A)
    stop_30 = _raw(CMD_STOP_ASCII, b"007200", b"000000", 0x30, 0x8A)
    idle_new_price = _raw(CMD_TEST_ASCII, b"000670", b"000000", 0x50, 0x8A)

    # 1. set_price с повтором на шаге 2 (0x16) и шаге 3 (0x30) + цена < 10.00 (6.70)
    link_retry = _ScriptedLink([idle_05, b"", not_ready_yet, ready_16, stop_not_30, stop_30, idle_new_price])
    ctrl_retry = Uzsg01PsuController(link_retry)
    res_price = ctrl_retry.set_price(1, 6.70, max_retries=3, retry_delay_sec=0.0)
    assert res_price.price_kzt_per_liter == pytest.approx(6.70)
    assert [req[3] for req in link_retry.sent] == [
        CMD_TEST_ASCII,
        CMD_PARAMS_ASCII,
        CMD_TEST_ASCII,
        CMD_TEST_ASCII,
        CMD_STOP_ASCII,
        CMD_STOP_ASCII,
        CMD_TEST_ASCII,
    ]

    # 2. Если 0x16 не пришёл — отправляется СБРОС (0x37) и выбрасывается PsuControlError
    link_fail = _ScriptedLink([idle_05, b"", not_ready_yet, not_ready_yet, idle_05])
    ctrl_fail = Uzsg01PsuController(link_fail)
    with pytest.raises(PsuControlError, match="0x16"):
        ctrl_fail.set_price(1, 75.0, max_retries=2, retry_delay_sec=0.0)
    assert link_fail.sent[-1][3] == CMD_RESET_ASCII

    # 3. _reset_to_idle_bits повторяет 0x37, пока биты 0..4 байта 17 не станут 0x10
    not_idle_bits = _raw(CMD_RESET_ASCII, b"007200", b"000000", 0x5A, 0x8A)
    idle_bits = _raw(CMD_RESET_ASCII, b"007200", b"000000", 0x50, 0x8A)
    link_rst = _ScriptedLink([not_idle_bits, idle_bits])
    ctrl_rst = Uzsg01PsuController(link_rst)
    reply = ctrl_rst._reset_to_idle_bits(1, max_retries=3, retry_delay_sec=0.0)  # noqa: SLF001
    assert reply is not None and reply.dose_type_bits == 0x10
    assert len(link_rst.sent) == 2

    # 4. send_buttons_param_to_pumps(..., last_frames=None) опрашивает колонку и отказывает при '03'
    disp_03 = _raw(CMD_TEST_ASCII, b"090000", b"001000", 0xD0, 0x8F, state="03")
    link_busy = _ScriptedLink([disp_03])
    ok_addrs, errs = send_buttons_param_to_pumps(
        link_busy,
        (1,),
        "0.17",
        checksum_mode="xor",
        last_frames=None,
    )
    assert ok_addrs == []
    assert len(errs) == 1 and "налив" in errs[0][1]
    assert len(link_busy.sent) == 1 and link_busy.sent[0][3] == CMD_TEST_ASCII


def test_column_start_and_stop_are_repeated_once_from_the_computer(tmp_path: Path) -> None:
    """Пуск колонки и набор дозы не вызывают 0x35. Без шага дозы и без закрытия клапана 0x36 нет."""
    from agzs_edge.iskra import CMD_SET_DOSE_ASCII, CMD_START_ASCII, CMD_STOP_ASCII, ETX, SOH, STX, compute_bcc

    def _frame(state: str, price: bytes, volume: bytes, status: int) -> bytes:
        body = b"01" + bytes([0x34, STX]) + price + volume + bytes([status, 0x8D]) + state.encode("ascii") + bytes([ETX])
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    frame_01_empty = _frame("01", b"000000", b"000000", 0x51)
    frame_01 = _frame("01", b"001000", b"000000", 0x51)
    frame_03 = _frame("03", b"001000", b"000000", 0x51)
    frame_03_flow = _frame("03", b"001000", b"000000", 0xD1)
    frame_05 = _frame("05", b"007200", b"000000", 0x50)
    frame_07 = _frame("07", b"001000", b"000000", 0x51)
    link = _ScriptedLink(
        [
            frame_01_empty,
            frame_01,
            frame_01,
            frame_03,
            frame_03_flow,
            frame_07,
            frame_05,
            frame_03,
        ]
    )
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "mirror.db",
        sync_enabled=False,
        read_only=True,
        trace_frames=True,
    )
    svc = StationEdgeService(settings, link=link, db=EdgeDatabase(settings.db_path))
    now = datetime.now(timezone.utc)
    for _ in range(8):
        svc.poll_cycle_once(observed_at=now)

    commands = [req[3] for req in link.sent]
    assert commands.count(CMD_START_ASCII) == 0
    assert commands.count(CMD_STOP_ASCII) == 0
    assert commands.count(CMD_SET_DOSE_ASCII) == 0


def test_column_stop_while_running_sends_one_stop(tmp_path: Path) -> None:
    """Из пуска '03' кнопка «Стоп» (шаг дозы) шлёт один 0x36. Набор в '01' и повтор кадра — нет."""
    from agzs_edge.iskra import CMD_START_ASCII, CMD_STOP_ASCII, CMD_TEST_ASCII, ETX, SOH, STX, compute_bcc
    from agzs_edge.serial_link import PollRawResult

    def _frame(state: str, price: bytes, status: int) -> bytes:
        body = b"01" + bytes([0x34, STX]) + price + b"000000" + bytes([status, 0x8D]) + state.encode("ascii") + bytes([ETX])
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    polls = [
        _frame("01", b"000000", 0x51),
        _frame("01", b"001000", 0x51),
        _frame("03", b"001000", 0x51),
        _frame("03", b"001000", 0xD1),
        _frame("03", b"002000", 0xD1),
        _frame("03", b"003000", 0xD1),
    ]

    class _Link:
        def __init__(self) -> None:
            self.sent: list[bytes] = []
            self._polls = list(polls)

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            from agzs_edge.iskra import build_test_command

            req = build_test_command(address, checksum_mode=checksum_mode or "xor")
            self.sent.append(req)
            resp = self._polls.pop(0)
            return PollRawResult(address=address, request_bytes=req, response_bytes=resp)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.sent.append(request)
            return PollRawResult(address=address, request_bytes=request, response_bytes=b"")

    link = _Link()
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "stop-button.db",
        sync_enabled=False,
        read_only=True,
        trace_frames=True,
    )
    svc = StationEdgeService(settings, link=link, db=EdgeDatabase(settings.db_path))
    now = datetime.now(timezone.utc)
    for _ in range(len(polls)):
        svc.poll_cycle_once(observed_at=now)

    commands = [req[3] for req in link.sent]
    assert commands.count(CMD_TEST_ASCII) == len(polls)
    assert commands.count(CMD_START_ASCII) == 0
    assert commands.count(CMD_STOP_ASCII) == 1


def test_column_stop_when_open_valve_closes_sends_one_stop(tmp_path: Path) -> None:
    """Клапан, открытый в пуске, закрылся, а состояние ещё '03' — один 0x36 и не больше."""
    from agzs_edge.iskra import CMD_STOP_ASCII, ETX, SOH, STX, compute_bcc
    from agzs_edge.serial_link import PollRawResult

    def _frame(status: int) -> bytes:
        body = b"01" + bytes([0x34, STX]) + b"001000" + b"000000" + bytes([status, 0x8D]) + b"03" + bytes([ETX])
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    polls = [_frame(0xD1), _frame(0x51), _frame(0x51)]

    class _Link:
        def __init__(self) -> None:
            self.sent: list[bytes] = []
            self._polls = list(polls)

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            from agzs_edge.iskra import build_test_command

            req = build_test_command(address, checksum_mode=checksum_mode or "xor")
            self.sent.append(req)
            resp = self._polls.pop(0)
            return PollRawResult(address=address, request_bytes=req, response_bytes=resp)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.sent.append(request)
            return PollRawResult(address=address, request_bytes=request, response_bytes=b"")

    link = _Link()
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "valve-stop.db",
        sync_enabled=False,
        read_only=True,
        trace_frames=True,
    )
    svc = StationEdgeService(settings, link=link, db=EdgeDatabase(settings.db_path))
    now = datetime.now(timezone.utc)
    for _ in range(len(polls)):
        svc.poll_cycle_once(observed_at=now)

    assert [req[3] for req in link.sent].count(CMD_STOP_ASCII) == 1
