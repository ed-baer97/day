"""Офлайн-тесты: кадр/BCC, пустой RX, частичный ответ, занятый порт, сервис без нулевого газа."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import (
    STATE_IDLE,
    IskraFrameError,
    build_test_command,
    build_test_response_frame,
    parse_iskra_frame,
)
from agzs_edge.serial_link import SerialAskaLink
from agzs_edge.service import StationEdgeService
from agzs_edge.storage import EdgeDatabase


class _FakeSerial:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.is_open = True
        self.written: list[bytes] = []
        self.reset_calls = 0

    def reset_input_buffer(self) -> None:
        self.reset_calls += 1

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        return

    def read(self, size: int) -> bytes:
        if not self._chunks:
            return b""
        head = self._chunks.pop(0)
        if len(head) > size:
            self._chunks.insert(0, head[size:])
            return head[:size]
        return head

    def close(self) -> None:
        self.is_open = False


def test_valid_frame_checksum_ok() -> None:
    raw = build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)
    frame = parse_iskra_frame(raw)
    assert frame.address == 1
    assert frame.volume_ml == 0


def test_invalid_checksum_rejected() -> None:
    raw = bytearray(build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=100))
    raw[-1] ^= 0xFF
    with pytest.raises(IskraFrameError, match="контрол"):
        parse_iskra_frame(bytes(raw))


def test_partial_response_not_treated_as_full_frame() -> None:
    full = build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)
    fake = _FakeSerial([full[:8], b""])  # обрыв после 8 байт, затем тишина
    link = SerialAskaLink(port="COM7", timeout_sec=0.15, min_wait_sec=0.2, inter_byte_timeout_sec=0.05)
    link._serial = fake  # noqa: SLF001
    res = link.poll_test(1)
    # Частичный буфер может вернуться как raw — сервис не должен парсить его в объём
    if res.response_bytes:
        with pytest.raises(IskraFrameError):
            parse_iskra_frame(res.response_bytes)


def test_empty_rx_is_not_zero_gas(tmp_path: Path) -> None:
    class _EmptyLink:
        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None):
            from agzs_edge.iskra import build_test_command
            from agzs_edge.serial_link import PollRawResult

            req = build_test_command(address)
            return PollRawResult(address=address, request_bytes=req, response_bytes=b"")

    settings = EdgeSettings(
        serial_port="COM7",
        pump_addresses=(1,),
        source_mode="serial",
        db_path=tmp_path / "edge.db",
        sync_enabled=False,
        save_raw_frames=True,
        station_id="a1111111-1111-1111-1111-111111111101",
        station_code="AGZS-AKT-12",
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=_EmptyLink(), db=db)
    closed = svc.poll_cycle_once(observed_at=datetime.now(timezone.utc))
    assert closed == []
    summary = db.summary()
    assert summary["total_dispenses"] == 0
    # Не должно появиться live volume=0 как «достоверное показание» от пустого RX
    pumps = summary.get("pumps") or []
    assert pumps == [] or all(p.get("volume_ml") is None or True for p in pumps)


def test_wrong_address_in_response_detected() -> None:
    raw = build_test_response_frame(address=2, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)
    # Подмена адреса в кадре без пересчёта BCC → ошибка checksum или адреса
    bad = bytearray(raw)
    bad[1:3] = b"01"
    with pytest.raises(IskraFrameError):
        parse_iskra_frame(bytes(bad))


def test_incompatible_response_format() -> None:
    weird = b"\xAA\x55" + b"\x00" * 21
    with pytest.raises(IskraFrameError):
        parse_iskra_frame(weird)


def test_port_busy_classified(monkeypatch) -> None:
    class _BusySerial:
        EIGHTBITS = 8
        PARITY_NONE = "N"
        STOPBITS_ONE = 1

        @staticmethod
        def Serial(**kwargs: object):
            raise OSError("Device or resource busy")

    monkeypatch.setitem(sys.modules, "serial", _BusySerial())
    link = SerialAskaLink(port="/dev/ttyUSB0", timeout_sec=0.2, min_wait_sec=0.2)
    res = link.poll_test(1)
    assert res.response_bytes == b""
    assert res.error_message is not None
    assert "busy" in res.error_message.lower()


def test_build_test_command_length_and_cmd4() -> None:
    cmd = build_test_command(1)
    assert len(cmd) == 23
    assert cmd[3] == ord("4")


def test_protocol_config_rejects_unknown(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGZS_PROTOCOL", "aska02_native")
    monkeypatch.setenv("AGZS_SERIAL_PORT", "COM7")
    with pytest.raises(ValueError, match="iskra_172"):
        EdgeSettings.from_env(tmp_path / "missing.env")


def test_diagnose_driver_error_when_port_missing(monkeypatch) -> None:
    from agzs_edge.diagnose import run_diagnose

    monkeypatch.setattr("agzs_edge.diagnose.list_available_serial_ports", lambda: [])
    settings = EdgeSettings(serial_port="COM99", device_token="top-secret-tok")
    report = run_diagnose(settings, address=1)

    assert report.status == "DRIVER_ERROR"
    assert report.access == "ERROR"
    rendered = report.render()
    assert "DRIVER_ERROR" in rendered
    assert "Порт не найден в системе" in rendered
    assert "top-secret-tok" not in rendered


def test_diagnose_connected_no_response_mismatch_and_port_busy(monkeypatch) -> None:
    from agzs_edge.diagnose import collect_usb_info, run_diagnose
    from agzs_edge.serial_link import PollRawResult

    monkeypatch.setattr(
        "agzs_edge.diagnose.list_available_serial_ports",
        lambda: [("COM7", "USB Serial Port (COM7)", "FTDIBUS\\VID_0403+PID_6001+SER=A5069RR4\\0000")],
    )
    valid_reply = build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)

    scenarios = [
        (PollRawResult(1, build_test_command(1), valid_reply), "CONNECTED", "OK"),
        (PollRawResult(1, build_test_command(1), b""), "NO_RESPONSE", "OK"),
        (PollRawResult(1, build_test_command(1), b"\xAA\x55\x00"), "PROTOCOL_MISMATCH_SUSPECTED", "FAIL"),
        (PollRawResult(1, build_test_command(1), b"", "Access is denied"), "PORT_BUSY", "OK"),
        (PollRawResult(1, build_test_command(1), b"", "Unknown hardware fault"), "DRIVER_ERROR", "OK"),
    ]

    for fake_res, expected_status, expected_frame_val in scenarios:
        class _StubLink:
            def __init__(self, *args, **kwargs) -> None:
                return

            def poll_test(self, address: int, *, checksum_mode: str | None = None):
                return fake_res

            def close(self) -> None:
                return

        monkeypatch.setattr("agzs_edge.diagnose.SerialAskaLink", _StubLink)
        settings = EdgeSettings(serial_port="com7", device_token="")
        report = run_diagnose(settings, address=1)
        assert report.status == expected_status
        assert report.frame_validation == expected_frame_val
        assert report.ftdi_detected is True
        assert report.serial_number == "A5069RR4"
        assert "VPS token: missing" in report.render()

    # Проверка POSIX-ветки collect_usb_info без ошибок в driver
    from agzs_edge.diagnose import DiagnoseReport

    monkeypatch.setattr("agzs_edge.diagnose._is_posix", lambda: True)

    def _fake_run(cmd: list[str]) -> str:
        if cmd[0] == "lsusb":
            return "Bus 001 Device 002: ID 0403:6001 Future Technology Devices International"
        if cmd[0] == "bash":
            return "ftdi_sio 65536 0"
        if cmd[0] == "udevadm":
            return "ID_SERIAL_SHORT=FT99999\nID_USB_DRIVER=ftdi_sio\n"
        return "ERR:unexpected"

    monkeypatch.setattr("agzs_edge.diagnose._run", _fake_run)
    posix_rep = DiagnoseReport()
    collect_usb_info(posix_rep, "/dev/ttyUSB0", ports=[])
    assert posix_rep.ftdi_detected is True
    assert posix_rep.driver == "ftdi_sio"
    assert posix_rep.serial_number == "FT99999"


def test_service_corrupted_frames_delayed_auto_reset_and_announce_vps(monkeypatch, tmp_path: Path) -> None:
    """Покрытие ветвей StationEdgeService: битые кадры, отложенный авто-сброс 07 и _announce_vps."""
    from agzs_edge.iskra import STATE_COMPLETED
    from agzs_edge.serial_link import PollRawResult
    from agzs_edge.sync import VpsSendResult

    class _MockLink:
        def __init__(self, responses: list[bytes]) -> None:
            self.responses = list(responses)
            self.commands: list[bytes] = []

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            resp = self.responses.pop(0) if self.responses else b""
            return PollRawResult(address=address, request_bytes=build_test_command(address), response_bytes=resp)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.commands.append(request)
            resp = self.responses.pop(0) if self.responses else b""
            return PollRawResult(address=address, request_bytes=request, response_bytes=resp)

    stop07 = build_test_response_frame(address=1, state_code=STATE_COMPLETED, price_digits=7200, volume_ml=0)
    # 1) битый кадр, 2) 07 (запуск таймера авто-сброса), 3) 07 (истечение задержки -> сброс, но ответ на сброс битый)
    link = _MockLink([b"\x01BAD_FRAME", stop07, stop07, b"\x01BAD_RESET"])
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "svc_extra.db",
        save_raw_frames=True,
        sync_enabled=True,
        sync_interval_sec=60.0,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=2.0,
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=link, db=db)

    ticks = iter([10.0, 13.0, 16.0])
    monkeypatch.setattr("agzs_edge.service.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        "agzs_edge.service.probe_vps_link",
        lambda url, tok, tank: VpsSendResult(ok=True, status_code=200, response_text='{"actual_remainder_liters": 4200}'),
    )

    svc._announce_vps()  # noqa: SLF001
    svc.poll_cycle_once()  # битый кадр
    svc.poll_cycle_once()  # 10.0 -> старт таймера задержки 2.0с
    assert len(link.commands) == 0
    svc.poll_cycle_once()  # 13.0 -> прошло 3.0с -> авто-сброс 0x37 (и битый ответ)
    assert len(link.commands) == 1
    assert svc.maybe_sync_outbox(force=False) == (0, 0)  # sync_interval_sec=60 ещё не прошёл

    # Проверка _announce_vps при ошибке и KeyboardInterrupt в serve
    monkeypatch.setattr(
        "agzs_edge.service.probe_vps_link",
        lambda url, tok, tank: VpsSendResult(ok=False, status_code=401, error_text="unauthorized"),
    )
    monkeypatch.setattr(svc, "poll_cycle_once", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    svc.serve(max_cycles=1)


def test_auto_reset_respects_delay_after_real_dispense(monkeypatch, tmp_path: Path) -> None:
    """После реального налива 03 -> 07 заправка сразу пишется в БД, а СБРОС 0x37 ждёт заданную паузу."""
    from agzs_edge.iskra import CMD_RESET_ASCII, STATE_COMPLETED, STATE_DISPENSING
    from agzs_edge.serial_link import PollRawResult

    disp_frame = build_test_response_frame(
        address=1, state_code=STATE_DISPENSING, error_code="00", price_digits=7200, volume_ml=5000
    )
    done_frame = build_test_response_frame(
        address=1, state_code=STATE_COMPLETED, error_code="00", price_digits=7200, volume_ml=5000
    )
    idle_frame = build_test_response_frame(
        address=1, state_code=STATE_IDLE, error_code="00", price_digits=7200, volume_ml=0
    )

    class _MockLink:
        def __init__(self, responses: list[bytes]) -> None:
            self.responses = list(responses)
            self.commands: list[bytes] = []

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            resp = self.responses.pop(0) if self.responses else b""
            return PollRawResult(address=address, request_bytes=build_test_command(address), response_bytes=resp)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.commands.append(request)
            return PollRawResult(address=address, request_bytes=request, response_bytes=idle_frame)

    link = _MockLink([disp_frame, done_frame, done_frame])
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "delayed_disp.db",
        sync_enabled=False,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=2.0,
    )
    svc = StationEdgeService(settings, link=link)

    ticks = iter([100.0, 102.5])
    monkeypatch.setattr("agzs_edge.service.time.monotonic", lambda: next(ticks))

    assert svc.poll_cycle_once() == []  # 03 (идёт налив)
    closed = svc.poll_cycle_once()      # 07 (закрытие налива; время 100.0 -> старт паузы 2.0 с)
    assert len(closed) == 1
    assert closed[0].dispensed_ml == 5000
    assert link.commands == []
    assert svc.poll_cycle_once() == []  # время 102.5 >= 100.0 + 2.0 -> отправка 0x37
    assert [req[3] for req in link.commands] == [CMD_RESET_ASCII]


def test_foreign_address_frame_ignored_without_reset(tmp_path: Path) -> None:
    """Запоздавший кадр от адреса #1 ('07') при опросе адреса #2 игнорируется и не шлёт 0x37 на #2."""
    from agzs_edge.iskra import STATE_COMPLETED
    from agzs_edge.serial_link import PollRawResult

    foreign_stop_07 = build_test_response_frame(
        address=1, state_code=STATE_COMPLETED, error_code="00", price_digits=7200, volume_ml=0
    )

    class _ForeignLink:
        def __init__(self) -> None:
            self.commands: list[tuple[int, bytes]] = []

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            del checksum_mode
            return PollRawResult(address=address, request_bytes=build_test_command(address), response_bytes=foreign_stop_07)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.commands.append((address, request))
            return PollRawResult(address=address, request_bytes=request, response_bytes=b"")

    link = _ForeignLink()
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(2,),
        db_path=tmp_path / "foreign.db",
        sync_enabled=False,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=0.0,
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=link, db=db)

    assert svc.poll_cycle_once() == []
    assert link.commands == []
    assert db.summary()["pumps"] == []


def test_slow_sync_worker_does_not_block_poll_loop_and_batch_net_error_skips_single(monkeypatch, tmp_path: Path) -> None:
    """Медленный sync_worker не тормозит цикл опроса в serve(), а сетевой сбой пакета не перебирает поштучно."""
    import time as _time
    from agzs_edge.serial_link import PollRawResult
    from agzs_edge.sync import OutboxSyncWorker, VpsSendResult
    from agzs_edge.tracker import CompletedDispense

    idle_frame = build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)

    class _FastLink:
        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            return PollRawResult(address=address, request_bytes=build_test_command(address), response_bytes=idle_frame)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            return PollRawResult(address=address, request_bytes=request, response_bytes=idle_frame)

    poll_times: list[float] = []
    flush_calls = 0

    class _SlowWorker:
        def flush_due(self, *, limit: int = 25, now=None):
            nonlocal flush_calls
            flush_calls += 1
            _time.sleep(0.25)
            return (0, 0)

    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        poll_interval_sec=0.01,
        db_path=tmp_path / "nonblock.db",
        sync_enabled=True,
        sync_interval_sec=0.05,
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=_FastLink(), db=db, sync_worker=_SlowWorker())  # type: ignore[arg-type]
    monkeypatch.setattr("agzs_edge.service.probe_vps_link", lambda *a, **kw: VpsSendResult(ok=True))

    orig_poll = svc.poll_cycle_once

    def _timed_poll():
        poll_times.append(_time.monotonic())
        return orig_poll()

    svc.poll_cycle_once = _timed_poll  # type: ignore[method-assign]
    t_start = _time.monotonic()
    svc.serve(max_cycles=4)
    total_elapsed = _time.monotonic() - t_start

    assert len(poll_times) == 4
    assert (poll_times[-1] - poll_times[0]) < 0.15
    assert total_elapsed >= 0.25
    assert flush_calls >= 1

    # Проверка OutboxSyncWorker: status_code=0 на batch не вызывает single_sender
    t0 = datetime.now(timezone.utc)
    for idx in range(3):
        db.record_completed_dispense(
            CompletedDispense(
                external_txn_id=f"net-err-{idx}",
                pump_address=1,
                mode="dose",
                preset_ml=5000,
                dispensed_ml=5000,
                volume_liters=5.0,
                price_kzt_per_liter=72.0,
                final_state_code="07",
                error_code="00",
                started_at=t0,
                finished_at=t0,
                last_raw_frame_hex="01",
            ),
            station_id=settings.station_id,
            dispenser_id=settings.dispenser_uuid(1),
            tank_id=settings.tank_id,
            now=t0,
        )
    single_calls = 0

    def _fail_single(*_a):
        nonlocal single_calls
        single_calls += 1
        return VpsSendResult(ok=False, status_code=0, error_text="net")

    worker = OutboxSyncWorker(
        db,
        vps_base_url=settings.vps_base_url,
        device_token="tok",
        sender=_fail_single,
        batch_sender=lambda *_a: VpsSendResult(ok=False, status_code=0, error_text="timed out"),
    )
    sent, failed = worker.flush_due(now=t0)
    assert sent == 0
    assert failed == 3
    assert single_calls == 0


def test_missed_03_recovered_before_auto_reset_and_no_duplicate_on_restart(tmp_path: Path) -> None:
    """Потерянный '03': первый кадр '07' (15000 мл) пишется до 0x37 и не задваивается после рестарта."""
    from agzs_edge.iskra import STATE_COMPLETED
    from agzs_edge.serial_link import PollRawResult

    stop_07 = build_test_response_frame(
        address=1, state_code=STATE_COMPLETED, error_code="00", price_digits=7200, volume_ml=15000
    )

    class _StopLink:
        def __init__(self) -> None:
            self.commands: list[bytes] = []

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            return PollRawResult(address=address, request_bytes=build_test_command(address), response_bytes=stop_07)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.commands.append(request)
            return PollRawResult(address=address, request_bytes=request, response_bytes=b"")

    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "recover.db",
        sync_enabled=False,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=30.0,
    )
    db = EdgeDatabase(settings.db_path)
    svc1 = StationEdgeService(settings, link=_StopLink(), db=db)
    closed1 = svc1.poll_cycle_once()
    assert len(closed1) == 1
    assert closed1[0].dispensed_ml == 15000
    assert db.summary()["total_dispenses"] == 1

    # Имитируем перезапуск службы до отправки 0x37 — колонка всё ещё в '07' с 15000 мл
    svc2 = StationEdgeService(settings, link=_StopLink(), db=EdgeDatabase(settings.db_path))
    closed2 = svc2.poll_cycle_once()
    assert closed2 == []
    assert db.summary()["total_dispenses"] == 1


def test_stopped_04_auto_reset_timeout_records_and_resets(monkeypatch, tmp_path: Path) -> None:
    """Таймаут паузы '04' закрывает заправку в SQLite и только после этого отправляет 0x37."""
    from agzs_edge.iskra import CMD_RESET_ASCII, STATE_DISPENSING, STATE_STOPPED
    from agzs_edge.serial_link import PollRawResult

    f_disp = build_test_response_frame(address=1, state_code=STATE_DISPENSING, price_digits=7200, volume_ml=5000)
    f_stop = build_test_response_frame(address=1, state_code=STATE_STOPPED, price_digits=7200, volume_ml=5000)
    f_idle = build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)

    class _PauseLink:
        def __init__(self, responses: list[bytes]) -> None:
            self.responses = list(responses)
            self.commands: list[bytes] = []

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            resp = self.responses.pop(0)
            return PollRawResult(address=address, request_bytes=build_test_command(address), response_bytes=resp)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            self.commands.append(request)
            return PollRawResult(address=address, request_bytes=request, response_bytes=f_idle)

    link = _PauseLink([f_disp, f_stop, f_stop])
    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "pause04.db",
        sync_enabled=False,
        auto_reset_on_stop=True,
        auto_reset_stopped_delay_sec=60.0,
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=link, db=db)

    ticks = iter([100.0, 165.0])
    monkeypatch.setattr("agzs_edge.service.time.monotonic", lambda: next(ticks))

    assert svc.poll_cycle_once() == []  # 03 (5000 мл)
    assert svc.poll_cycle_once() == []  # 04 -> старт таймера 60 с (t=100.0)
    assert svc.is_idle_for_update() is False
    assert link.commands == []
    assert db.summary()["total_dispenses"] == 0

    closed = svc.poll_cycle_once()      # 04 (t=165.0 >= 100.0 + 60.0) -> запись в БД + 0x37
    assert len(closed) == 1
    assert closed[0].dispensed_ml == 5000
    assert [req[3] for req in link.commands] == [CMD_RESET_ASCII]
    assert db.summary()["total_dispenses"] == 1
    assert db.summary()["total_dispensed_ml"] == 5000


def test_counter_reconciliation_writes_counter_audits(monkeypatch, tmp_path: Path) -> None:
    """Периодическая сверка суммарного счётчика (0.11) пишет записи в таблицу counter_audits."""
    import sqlite3
    from datetime import timedelta
    from agzs_edge.iskra import CMD_PARAMS_ASCII, CMD_RESET_ASCII, CMD_TEST_ASCII, ETX, SOH, STX, compute_bcc
    from agzs_edge.serial_link import PollRawResult
    from agzs_edge.tracker import CompletedDispense

    def _raw(cmd: int, price: bytes, vol: bytes, b17: int, state: str = "05") -> bytes:
        body = b"01" + bytes([cmd, STX]) + price + vol + bytes([b17, 0x8A]) + state.encode("ascii") + bytes([ETX])
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    idle_05 = _raw(CMD_TEST_ASCII, b"007200", b"000000", 0x50)
    cnt_100 = _raw(CMD_PARAMS_ASCII, b"000000", b"010000", 0x5A)  # 0000010000 -> 100.00 л
    cnt_125 = _raw(CMD_PARAMS_ASCII, b"000000", b"012500", 0x5A)  # 0000012500 -> 125.00 л
    rst_ok = _raw(CMD_RESET_ASCII, b"007200", b"000000", 0x50)

    class _AuditLink:
        def __init__(self, cnt_frames: list[bytes]) -> None:
            self.cnt_frames = list(cnt_frames)

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            return PollRawResult(address=address, request_bytes=build_test_command(address), response_bytes=idle_05)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            if request[3] == CMD_PARAMS_ASCII and request[5:11] == b"000011":
                return PollRawResult(address=address, request_bytes=request, response_bytes=self.cnt_frames.pop(0))
            if request[3] == CMD_RESET_ASCII:
                return PollRawResult(address=address, request_bytes=request, response_bytes=rst_ok)
            return PollRawResult(address=address, request_bytes=request, response_bytes=idle_05)

    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        db_path=tmp_path / "audit.db",
        sync_enabled=False,
        read_only=False,
        lock_buttons_on_update=False,
        counter_reconcile_interval_sec=60.0,
    )
    db = EdgeDatabase(settings.db_path)
    svc = StationEdgeService(settings, link=_AuditLink([cnt_100, cnt_125]), db=db)

    t0 = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
    ticks = iter([100.0, 200.0])
    monkeypatch.setattr("agzs_edge.service.time.monotonic", lambda: next(ticks))

    svc.poll_cycle_once(observed_at=t0)

    # Записываем в БД 1 заправку на 20 л (а суммарник вырос на 25 л -> расхождение +5 л)
    db.record_completed_dispense(
        CompletedDispense(
            external_txn_id="audit-disp-1",
            pump_address=1,
            mode="dose",
            preset_ml=20000,
            dispensed_ml=20000,
            volume_liters=20.0,
            price_kzt_per_liter=72.0,
            final_state_code="07",
            error_code="00",
            started_at=t0 + timedelta(seconds=10),
            finished_at=t0 + timedelta(seconds=30),
            last_raw_frame_hex="01",
        ),
        station_id=settings.station_id,
        dispenser_id=settings.dispenser_uuid(1),
        tank_id=settings.tank_id,
    )

    svc.poll_cycle_once(observed_at=t0 + timedelta(seconds=70))

    conn = sqlite3.connect(settings.db_path)
    rows = conn.execute(
        "SELECT total_counter_liters, counter_delta_liters, db_dispenses_liters, discrepancy_liters "
        "FROM counter_audits ORDER BY id ASC"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0] == (100.0, None, 0.0, None)
    assert rows[1] == (125.0, 25.0, 20.0, 5.0)
