"""Линия связи с адаптером АСКА-02 (FTDI FT232R, 9600 8N1) и имитатор для отладки без колонки.

Работает одинаково на Windows (COM7) и Linux (/dev/ttyUSB0) через pyserial,
без вызовов fcntl/termios, благодаря чему живой опрос и запись в базу работают на Windows 10/11.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from agzs_edge.config import FrameLayout
from agzs_edge.iskra import (
    EXPECTED_FRAME_LEN,
    SOH,
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    build_test_command,
    build_test_response_frame,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollRawResult:
    """Результат одного опроса адреса по команде «Тест»."""

    address: int
    request_bytes: bytes
    response_bytes: bytes
    error_message: str | None = None

    @property
    def has_response(self) -> bool:
        return len(self.response_bytes) > 0


class AskaLink(Protocol):
    """Интерфейс линии связи с АСКА-02."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def poll_test(self, address: int) -> PollRawResult: ...


class SerialAskaLink:
    """Живой COM-порт АСКА-02 (FTDI FT232R, 9600 8N1)."""

    def __init__(
        self,
        port: str = "COM7",
        baudrate: int = 9600,
        timeout_sec: float = 0.25,
        layout: FrameLayout | None = None,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout_sec = timeout_sec
        self.layout = layout or FrameLayout()
        self._serial: object | None = None

    def open(self) -> None:
        if self._serial is not None and getattr(self._serial, "is_open", False):
            return
        import serial  # pyserial

        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout_sec,
            write_timeout=self.timeout_sec,
        )
        logger.info("Открыт порт АСКА-02: %s (%d 8N1)", self.port, self.baudrate)

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._serial = None

    def poll_test(self, address: int) -> PollRawResult:
        """Отправляет команду «Тест» (код 4) на указанный адрес и читает 23-байтный кадр ответа."""
        request = build_test_command(address, checksum_mode=self.layout.checksum_mode)
        try:
            self.open()
            ser = self._serial
            assert ser is not None
            ser.reset_input_buffer()  # type: ignore[attr-defined]
            ser.write(request)  # type: ignore[attr-defined]
            ser.flush()  # type: ignore[attr-defined]

            # Читаем с выравниванием по стартовому байту SOH (0x01) на случай помех на линии
            raw = self._read_aligned_frame(ser, self.layout.frame_length)
            return PollRawResult(address=address, request_bytes=request, response_bytes=raw)
        except Exception as exc:
            self.close()
            return PollRawResult(
                address=address,
                request_bytes=request,
                response_bytes=b"",
                error_message=str(exc),
            )

    def _read_aligned_frame(self, ser: object, expected_len: int) -> bytes:
        deadline = time.monotonic() + max(self.timeout_sec * 2.0, 0.35)
        buf = bytearray()
        while time.monotonic() < deadline and len(buf) < expected_len:
            chunk: bytes = ser.read(expected_len - len(buf))  # type: ignore[attr-defined]
            if not chunk:
                break
            buf.extend(chunk)
            # Если в начале мусор до 0x01 (SOH), сдвигаем буфер до первого SOH
            if SOH in buf:
                soh_idx = buf.index(SOH)
                if soh_idx > 0:
                    del buf[:soh_idx]
        return bytes(buf)


class EmulatorAskaLink:
    """Безопасный имитатор кадров УЗГС-01 (Искра 1.72) для проверки записи в БД и отправки на VPS без колонки.

    Генерирует по очереди:
      - На адресе 1: заправку по обычной дозе (задали 20 000 мл -> остаток убывает 12 500 -> 5 000 -> 0 -> COMPLETED)
      - На адресе 2: заправку «до полного» (нарастание 0 -> 4 200 -> 9 800 -> 14 600 -> COMPLETED)
    """

    def __init__(self, layout: FrameLayout | None = None, price_digits: int = 10000) -> None:
        self.layout = layout or FrameLayout()
        self.price_digits = price_digits
        self._step_by_addr: dict[int, int] = {}

    def open(self) -> None:
        return

    def close(self) -> None:
        return

    def poll_test(self, address: int) -> PollRawResult:
        request = build_test_command(address, checksum_mode=self.layout.checksum_mode)
        step = self._step_by_addr.get(address, 0)
        self._step_by_addr[address] = (step + 1) % 8

        if address % 2 == 1:
            # Сценарий 1: обычная доза 20 000 мл (остаток уменьшается)
            schedule = [
                (STATE_IDLE, 0, "00"),
                (STATE_DOSE_SET, 20000, "01"),
                (STATE_DISPENSING, 16000, "01"),
                (STATE_DISPENSING, 12500, "01"),
                (STATE_DISPENSING, 6000, "01"),
                (STATE_DISPENSING, 0, "01"),
                (STATE_COMPLETED, 0, "01"),
                (STATE_IDLE, 0, "00"),
            ]
        else:
            # Сценарий 2: режим «до полного» (объём увеличивается с 0)
            schedule = [
                (STATE_IDLE, 0, "00"),
                (STATE_DISPENSING, 0, "02"),
                (STATE_DISPENSING, 3500, "02"),
                (STATE_DISPENSING, 8200, "02"),
                (STATE_DISPENSING, 12750, "02"),
                (STATE_COMPLETED, 12750, "02"),
                (STATE_IDLE, 0, "00"),
                (STATE_IDLE, 0, "00"),
            ]

        state_code, vol_ml, flags = schedule[step]
        response = build_test_response_frame(
            address=address,
            state_code=state_code,
            error_code="00",
            price_digits=self.price_digits,
            volume_ml=vol_ml,
            flags=flags,
            checksum_mode=self.layout.checksum_mode,
        )
        return PollRawResult(address=address, request_bytes=request, response_bytes=response)


def list_available_serial_ports() -> list[tuple[str, str, str]]:
    """Возвращает список доступных COM-портов: (port, description, hwid)."""
    try:
        from serial.tools import list_ports

        return [(p.device, p.description or "", p.hwid or "") for p in list_ports.comports()]
    except Exception:
        return []
