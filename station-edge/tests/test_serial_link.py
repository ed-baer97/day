"""Тесты логики чтения COM-порта SerialAskaLink и диагностических флагов CLI probe."""

from __future__ import annotations

import sys
import types

from agzs_edge.config import FrameLayout
from agzs_edge.iskra import STATE_IDLE, build_test_response_frame, compute_bcc
from agzs_edge.main import main
from agzs_edge.serial_link import SerialAskaLink


class _FakeSerial:
    """Имитация pyserial.Serial с настраиваемой последовательностью чанков ответа."""

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


def test_serial_link_waits_for_slow_response_despite_short_timeout() -> None:
    """При timeout_sec=0.25 первые пустые read() не должны обрывать чтение до истечения min_wait_sec."""
    frame = build_test_response_frame(address=1, state_code=STATE_IDLE, price_digits=7200, volume_ml=0)
    fake_ser = _FakeSerial([b"", b"", b"", frame[:10], frame[10:]])

    link = SerialAskaLink(
        port="COM7",
        baudrate=9600,
        timeout_sec=0.25,
        min_wait_sec=0.4,
        inter_byte_timeout_sec=0.05,
    )
    link._serial = fake_ser  # noqa: SLF001

    res = link.poll_test(1)
    assert res.error_message is None
    assert res.response_bytes == frame
    assert fake_ser.reset_calls == 1


def test_serial_link_aligns_leading_noise_before_iskra_frame() -> None:
    """Шумовые байты перед SOH (0x01) отбрасываются, если за ними следует целый 23-байтный кадр."""
    frame = build_test_response_frame(address=2, state_code=STATE_IDLE, price_digits=7200, volume_ml=1500)
    fake_ser = _FakeSerial([b"\xFF\x00" + frame])

    link = SerialAskaLink(port="COM7", timeout_sec=0.2, min_wait_sec=0.2)
    link._serial = fake_ser  # noqa: SLF001

    res = link.poll_test(2)
    assert res.response_bytes == frame


def test_serial_link_preserves_short_non_iskra_reply_even_with_0x01_byte() -> None:
    """Короткий нестандартный ответ (например, протокол другого вида с 0x01 внутри) не обрезается."""
    weird_reply = b"\x7F\x01\x04\x03\x82"
    fake_ser = _FakeSerial([weird_reply, b""])

    link = SerialAskaLink(port="COM7", timeout_sec=0.2, min_wait_sec=0.2)
    link._serial = fake_ser  # noqa: SLF001

    res = link.poll_test(1)
    assert res.response_bytes == weird_reply


def test_serial_link_open_uses_short_read_timeout_and_preserves_min_wait(monkeypatch) -> None:
    """open() выставляет короткий read_timeout для chunked-чтения при общем min_wait_sec >= 1.0."""
    captured_kwargs: dict[str, object] = {}

    class _DummySerialModule:
        EIGHTBITS = 8
        PARITY_NONE = "N"
        STOPBITS_ONE = 1

        @staticmethod
        def Serial(**kwargs: object) -> _FakeSerial:
            captured_kwargs.update(kwargs)
            return _FakeSerial([])

    monkeypatch.setitem(sys.modules, "serial", _DummySerialModule())
    link = SerialAskaLink(port="/dev/ttyUSB0", baudrate=9600, timeout_sec=0.25)
    link.open()

    assert captured_kwargs["port"] == "/dev/ttyUSB0"
    assert captured_kwargs["baudrate"] == 9600
    assert captured_kwargs["timeout"] == 0.15


def test_cli_probe_checksum_all_tries_xor_sum7_and_sum8(monkeypatch, capsys) -> None:
    """`probe --checksum all` перебирает xor, sum7 и sum8 и разбирает ответ с любой из этих BCC."""
    sent_requests: list[tuple[int, bytes, str]] = []
    sum8_reply = build_test_response_frame(
        address=1,
        state_code=STATE_IDLE,
        price_digits=7200,
        volume_ml=0,
        checksum_mode="sum8",
    )

    class _FakeLink:
        def __init__(self, **kwargs: object) -> None:
            self.layout: FrameLayout = kwargs["layout"]  # type: ignore[assignment]

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None):
            from agzs_edge.iskra import build_test_command
            from agzs_edge.serial_link import PollRawResult

            mode = checksum_mode or self.layout.checksum_mode
            req = build_test_command(address, checksum_mode=mode)
            sent_requests.append((address, req, mode))
            resp = sum8_reply if mode == "sum8" else b""
            return PollRawResult(address=address, request_bytes=req, response_bytes=resp)

    monkeypatch.setattr("agzs_edge.main.SerialAskaLink", _FakeLink)
    monkeypatch.setattr("agzs_edge.main.list_available_serial_ports", lambda: [])

    fake_tools = types.SimpleNamespace(list_ports=types.SimpleNamespace(comports=lambda: []))
    monkeypatch.setitem(sys.modules, "serial.tools", fake_tools)

    rc = main(["probe", "--port", "COM7", "--checksum", "all", "--timeout", "1.5"])
    assert rc == 0

    modes_for_addr1 = [m for addr, _, m in sent_requests if addr == 1]
    assert modes_for_addr1 == ["xor", "sum7", "sum8"]

    # Проверяем, что для адреса 1 ушли три разные контрольные суммы: xor=0x34, sum7=0x1A, sum8=0x9A
    bcc_bytes = [req[-1] for addr, req, _ in sent_requests if addr == 1]
    body_addr1 = sent_requests[0][1][1:-1]
    assert bcc_bytes == [
        compute_bcc(body_addr1, "xor"),
        compute_bcc(body_addr1, "sum7"),
        compute_bcc(body_addr1, "sum8"),
    ]

    out = capsys.readouterr().out
    assert "timeout=1.50с" in out
    assert "[Адрес 1, sum8]" in out
    assert "ОК: адрес=1" in out
