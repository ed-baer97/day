"""Линия связи с адаптером АСКА-02 (FTDI FT232R, 9600 8N1) и имитатор для отладки без колонки.

Работает одинаково на Windows (COM7) и Linux (/dev/ttyUSB0) через pyserial,
без вызовов fcntl/termios, благодаря чему живой опрос и запись в базу работают на Windows 10/11.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from agzs_edge.aska_compat import Attempt
from agzs_edge.config import FrameLayout
from agzs_edge.iskra import (
    SOH,
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    build_test_command,
    build_test_response_frame,
)

logger = logging.getLogger(__name__)
_PORT_LOCK = threading.RLock()


class _ObservedSerial:
    """Пропускает write/read через Attempt без изменения аргументов и числа вызовов."""

    def __init__(self, ser: object, attempt: Attempt) -> None:
        self._ser = ser
        self._attempt = attempt

    def write(self, data: bytes) -> int:
        return self._attempt.write(self._ser.write, data)  # type: ignore[attr-defined]

    def read(self, size: int) -> bytes:
        return self._attempt.read(self._ser.read, size)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._ser, name)


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
    def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult: ...


class SerialAskaLink:
    """Живой COM-порт АСКА-02 (FTDI FT232R, 9600 8N1)."""

    def __init__(
        self,
        port: str = "COM7",
        baudrate: int = 9600,
        timeout_sec: float = 1.0,
        layout: FrameLayout | None = None,
        *,
        min_wait_sec: float = 1.0,
        inter_byte_timeout_sec: float = 0.15,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout_sec = timeout_sec
        self.layout = layout or FrameLayout()
        self.min_wait_sec = min_wait_sec
        self.inter_byte_timeout_sec = inter_byte_timeout_sec
        self._serial: object | None = None
        self._lock = _PORT_LOCK
        self.last_attempt: Attempt | None = None

    def open(self) -> None:
        with self._lock:
            if self._serial is not None and getattr(self._serial, "is_open", False):
                return
            import serial  # pyserial

            # Короткий таймаут одного read() + общий deadline в _read_aligned_frame.
            read_timeout = min(max(self.timeout_sec, self.min_wait_sec, 0.02), self.inter_byte_timeout_sec)
            kwargs = {
                "port": self.port,
                "baudrate": self.baudrate,
                "bytesize": serial.EIGHTBITS,
                "parity": serial.PARITY_NONE,
                "stopbits": serial.STOPBITS_ONE,
                "timeout": read_timeout,
                "write_timeout": max(self.timeout_sec, 0.5),
            }
            # На Linux исключаем параллельный доступ к тому же TTY.
            if os.name == "posix":
                kwargs["exclusive"] = True
            self._serial = serial.Serial(**kwargs)
            logger.info("Открыт порт АСКА-02: %s (%d 8N1)", self.port, self.baudrate)

    def close(self) -> None:
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._serial = None

    def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
        """Отправляет команду «Тест» (код 4) на указанный адрес и читает ответ (если есть)."""
        mode = checksum_mode or self.layout.checksum_mode
        request = build_test_command(address, checksum_mode=mode)
        with self._lock:
            try:
                self.open()
                assert self._serial is not None
                attempt = Attempt(request, channel=address)
                self.last_attempt = attempt
                ser = _ObservedSerial(self._serial, attempt)
                ser.reset_input_buffer()  # type: ignore[attr-defined]
                ser.write(request)
                ser.flush()  # type: ignore[attr-defined]
                logger.debug("TX addr=%s hex=%s", address, request.hex(" ").upper())

                raw = self._read_aligned_frame(ser, self.layout.frame_length)
                if raw:
                    logger.debug("RX addr=%s len=%s hex=%s", address, len(raw), raw.hex(" ").upper())
                else:
                    logger.debug("RX addr=%s EMPTY", address)
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
        deadline = time.monotonic() + max(self.timeout_sec, self.min_wait_sec)
        buf = bytearray()
        while True:
            soh_idx = buf.index(SOH) if SOH in buf else -1
            target_len = (soh_idx + expected_len) if soh_idx >= 0 else expected_len
            if len(buf) >= target_len or time.monotonic() >= deadline:
                break

            t_before = time.monotonic()
            chunk: bytes = ser.read(target_len - len(buf))  # type: ignore[attr-defined]
            if not chunk:
                # Если данные уже начали поступать и линия замолчала — отдаём то, что успело прийти
                if buf:
                    break
                if time.monotonic() - t_before < 0.005:
                    time.sleep(0.01)
                continue
            buf.extend(chunk)

        if SOH in buf:
            soh_idx = buf.index(SOH)
            tail = buf[soh_idx:]
            if soh_idx == 0:
                return bytes(tail[:expected_len])
            # Срезаем ведущий шум до SOH только если за ним действительно лежит полный кадр Искра
            if (
                len(tail) >= expected_len
                and 0 <= self.layout.etx_offset < len(tail)
                and tail[self.layout.etx_offset] == self.layout.etx_byte
            ):
                return bytes(tail[:expected_len])
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

    def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
        mode = checksum_mode or self.layout.checksum_mode
        request = build_test_command(address, checksum_mode=mode)
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
            checksum_mode=mode,
        )
        return PollRawResult(address=address, request_bytes=request, response_bytes=response)


def list_available_serial_ports() -> list[tuple[str, str, str]]:
    """Возвращает список доступных COM-портов: (port, description, hwid)."""
    try:
        from serial.tools import list_ports

        return [(p.device, p.description or "", p.hwid or "") for p in list_ports.comports()]
    except Exception:
        return []
