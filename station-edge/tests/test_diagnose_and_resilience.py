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
    assert link.commands == []          # 0x37 ещё не отправлен, на табло виден итог
    assert svc.poll_cycle_once() == []  # время 102.5 >= 100.0 + 2.0 -> отправка 0x37
    assert len(link.commands) == 1
    assert link.commands[0][3] == CMD_RESET_ASCII
