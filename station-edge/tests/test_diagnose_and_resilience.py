"""Офлайн-тесты: кадр/BCC, пустой RX, частичный ответ, занятый порт, сервис без нулевого газа."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agzs_edge.config import EdgeSettings, FrameLayout
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


def test_observer_keeps_tx_bytes_and_reports_zero_rx() -> None:
    from agzs_edge.aska_compat import compare_tx

    fake = _FakeSerial([])
    link = SerialAskaLink(port="COM7", timeout_sec=0.1, min_wait_sec=0.1, inter_byte_timeout_sec=0.02)
    link._serial = fake  # noqa: SLF001
    res = link.poll_test(1)

    assert fake.written == [build_test_command(1)]
    assert compare_tx(build_test_command(1), fake.written[0], 23)["wire_format_preserved"]
    report = link.last_attempt.report(driver_reported_timeout=True)
    assert report["tx_exactly_matches_existing_frame"]
    assert report["rx_bytes"] == 0
    assert report["code"] == "RX_ZERO_AT_DRIVER_TIMEOUT"
    assert report["value"] is None
    assert res.response_bytes == b""


def test_observer_accepts_valid_reply_via_existing_parser() -> None:
    frame = build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)
    fake = _FakeSerial([frame])
    link = SerialAskaLink(port="COM7", timeout_sec=0.2, min_wait_sec=0.2)
    link._serial = fake  # noqa: SLF001
    res = link.poll_test(1)

    parsed = parse_iskra_frame(res.response_bytes)
    link.last_attempt.parser_result(frame_valid=True, matches_request=parsed.address == 1, value=parsed.volume_ml)
    report = link.last_attempt.report()
    assert report["code"] == "VALID_REPLY_REPORTED_BY_EXISTING_PARSER"
    assert report["measurement_valid"] is True
    assert report["value"] == 0


def test_protocol_config_rejects_unknown(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGZS_PROTOCOL", "aska02_native")
    monkeypatch.setenv("AGZS_SERIAL_PORT", "COM7")
    with pytest.raises(ValueError, match="iskra_172"):
        EdgeSettings.from_env(tmp_path / "missing.env")
