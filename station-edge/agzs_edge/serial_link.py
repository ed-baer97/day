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

from agzs_edge.config import EdgeSettings, FrameLayout
from agzs_edge.iskra import (
    CMD_PARAMS_ASCII,
    CMD_RESET_ASCII,
    CMD_SET_DOSE_ASCII,
    CMD_START_ASCII,
    CMD_STOP_ASCII,
    CMD_TEST_ASCII,
    ETX,
    SOH,
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_STOPPED,
    STX,
    build_command_frame,
    build_test_command,
    build_test_response_frame,
    compute_bcc,
    verify_frame_checksum,
)

logger = logging.getLogger(__name__)
_PORT_LOCK = threading.RLock()


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
    def send_command(self, address: int, request: bytes) -> PollRawResult: ...


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
        inter_frame_delay_sec: float = 0.05,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout_sec = timeout_sec
        self.layout = layout or FrameLayout()
        self.min_wait_sec = min_wait_sec
        self.inter_byte_timeout_sec = inter_byte_timeout_sec
        self.inter_frame_delay_sec = max(0.0, inter_frame_delay_sec)
        self._serial: object | None = None
        self._lock = _PORT_LOCK
        self._last_io_done_mono: float = 0.0

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
        return self.send_command(address, request)

    def send_command(self, address: int, request: bytes) -> PollRawResult:
        """Отправляет произвольный 23-байтный кадр Протокола v3.10 и читает ответ (если есть)."""
        with self._lock:
            try:
                if self.inter_frame_delay_sec > 0 and self._last_io_done_mono > 0:
                    gap = time.monotonic() - self._last_io_done_mono
                    if gap < self.inter_frame_delay_sec:
                        time.sleep(self.inter_frame_delay_sec - gap)

                self.open()
                assert self._serial is not None
                ser = self._serial
                ser.reset_input_buffer()  # type: ignore[attr-defined]
                ser.write(request)  # type: ignore[attr-defined]
                ser.flush()  # type: ignore[attr-defined]
                logger.debug("TX addr=%s cmd=0x%02X hex=%s", address, request[3], request.hex(" ").upper())

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
            finally:
                self._last_io_done_mono = time.monotonic()

    def _extract_valid_frame(self, buf: bytearray, expected_len: int) -> bytes | None:
        soh = self.layout.soh_byte
        etx_off = self.layout.etx_offset
        etx_val = self.layout.etx_byte
        start = 0
        while start <= len(buf) - expected_len:
            try:
                idx = buf.index(soh, start)
            except ValueError:
                return None
            if idx + expected_len > len(buf):
                return None
            candidate = bytes(buf[idx : idx + expected_len])
            if (
                len(candidate) > 4
                and candidate[4] == STX
                and 0 <= etx_off < len(candidate)
                and candidate[etx_off] == etx_val
                and verify_frame_checksum(candidate, self.layout)
            ):
                return candidate
            start = idx + 1
        return None

    def _next_read_size(self, buf: bytearray, expected_len: int) -> int:
        soh = self.layout.soh_byte
        for pos in range(len(buf) - 1, -1, -1):
            if buf[pos] == soh and (len(buf) - pos) < expected_len:
                return expected_len - (len(buf) - pos)
        return expected_len

    def _read_aligned_frame(self, ser: object, expected_len: int) -> bytes:
        deadline = time.monotonic() + max(self.timeout_sec, self.min_wait_sec)
        soh = self.layout.soh_byte
        buf = bytearray()
        last_rx_mono = 0.0

        while True:
            valid = self._extract_valid_frame(buf, expected_len)
            if valid is not None:
                return valid

            now = time.monotonic()
            if now >= deadline:
                break

            read_size = self._next_read_size(buf, expected_len)
            t_before = time.monotonic()
            chunk: bytes = ser.read(read_size)  # type: ignore[attr-defined]
            if chunk:
                buf.extend(chunk)
                last_rx_mono = time.monotonic()
                continue

            now = time.monotonic()
            if soh not in buf:
                # До реального SOH может прилететь шум; не обрываем чтение раньше deadline
                if now - t_before < 0.005:
                    time.sleep(min(0.01, max(0.0, deadline - now)))
                continue

            # После приёма SOH ждём до завершения межбайтового таймаута
            since_last_rx = now - last_rx_mono
            if since_last_rx >= self.inter_byte_timeout_sec:
                break
            if now - t_before < 0.005:
                wait_left = min(
                    0.01,
                    max(0.0, self.inter_byte_timeout_sec - since_last_rx),
                    max(0.0, deadline - now),
                )
                if wait_left > 0:
                    time.sleep(wait_left)

        valid = self._extract_valid_frame(buf, expected_len)
        if valid is not None:
            return valid

        if soh in buf:
            start = 0
            while start <= len(buf) - expected_len:
                try:
                    idx = buf.index(soh, start)
                except ValueError:
                    break
                tail = buf[idx:]
                if (
                    len(tail) >= expected_len
                    and len(tail) > 4
                    and tail[4] == STX
                    and 0 <= self.layout.etx_offset < len(tail)
                    and tail[self.layout.etx_offset] == self.layout.etx_byte
                ):
                    return bytes(tail[:expected_len])
                start = idx + 1
            if buf.index(soh) == 0:
                return bytes(buf[:expected_len])
        return bytes(buf)


class EmulatorAskaLink:
    """Безопасный имитатор кадров УЗСГ-01 (Искра 1.72 / Протокол v3.10) без живой колонки.

    При обычном опросе `poll_test` воспроизводит демонстрационные наливы для тестов учёта.
    При вызове `send_command` (или `initial_locked=True`) ведёт себя как живая колонка УЗСГ-01
    с Блоком питания: поддерживает Сброс (0x37), Задание дозы (0x39), Пуск (0x35), Останов (0x36)
    и команды параметров 0x38 (кнопки, цена, счётчики).
    """

    def __init__(
        self,
        layout: FrameLayout | None = None,
        price_digits: int = 10000,
        *,
        initial_locked: bool = False,
    ) -> None:
        self.layout = layout or FrameLayout()
        self.price_digits = price_digits
        self._initial_locked = initial_locked
        self._step_by_addr: dict[int, int] = {}
        self._controlled_state: dict[int, dict[str, object]] = {}

    def open(self) -> None:
        return

    def close(self) -> None:
        return

    def _get_state(self, address: int) -> dict[str, object]:
        if address not in self._controlled_state:
            self._controlled_state[address] = {
                "state_code": STATE_COMPLETED if self._initial_locked else STATE_IDLE,
                "price_kop": self.price_digits,
                "dose_ml": 900000 if self._initial_locked else 0,
                "dispensed_ml": 0,
                "valve_open": False,
                "buttons_ss": True,
                "button_reset": False,
                "dose_type": 0x10,
                "total_counter_1": 123456,
                "total_counter_2": 123456,
                "daily_counter": 4500,
                "temp_c_tenths": 215,
                "propane_pct": 65,
                "tpr_coef": 1234,
                "pending_price_kop": None,
                "price_stage": None,
            }
        return self._controlled_state[address]

    def _build_live_reply(
        self,
        address: int,
        reply_cmd: int,
        state: dict[str, object],
        *,
        price_field: bytes | None = None,
        volume_field: bytes | None = None,
        dose_bits_override: int | None = None,
        byte17_override: int | None = None,
    ) -> bytes:
        if byte17_override is not None:
            byte17 = byte17_override
        else:
            byte17 = (
                (0x80 if state["valve_open"] else 0)
                | (0x40 if state["buttons_ss"] else 0)
                | (0x20 if state["button_reset"] else 0)
                | ((dose_bits_override if dose_bits_override is not None else int(state["dose_type"])) & 0x1F)
            )
        byte18 = 0x8A
        state_code = str(state["state_code"])
        if price_field is None:
            if state_code == STATE_IDLE:
                price_val = int(state["price_kop"])
            else:
                dose_ml = int(state["dose_ml"])
                price_val = (dose_ml // 10) if dose_ml > 0 else int(state["price_kop"])
            price_field = f"{price_val:06d}".encode("ascii")
        if volume_field is None:
            volume_field = f"{int(state['dispensed_ml']):06d}".encode("ascii")
        body = (
            f"{address:02d}".encode("ascii")
            + bytes([reply_cmd, STX])
            + price_field
            + volume_field
            + bytes([byte17, byte18])
            + state_code.encode("ascii")
            + bytes([ETX])
        )
        mode = self.layout.tx_checksum_mode
        return bytes([SOH]) + body + bytes([compute_bcc(body, mode)])

    def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
        mode = checksum_mode or self.layout.checksum_mode
        request = build_test_command(address, checksum_mode=mode)
        if address in self._controlled_state or self._initial_locked:
            state = self._get_state(address)
            return PollRawResult(
                address=address,
                request_bytes=request,
                response_bytes=self._build_live_reply(address, CMD_TEST_ASCII, state),
            )

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

    def send_command(self, address: int, request: bytes) -> PollRawResult:
        """Эмулирует ответ колонки УЗСГ-01 на команды Протокола v3.10."""
        cmd = request[3]
        if (
            cmd == CMD_RESET_ASCII
            and address in self._step_by_addr
            and address not in self._controlled_state
            and not self._initial_locked
        ):
            self._step_by_addr[address] = 0
            mode = self.layout.tx_checksum_mode
            reply = build_command_frame(
                address,
                CMD_RESET_ASCII,
                price_digits=self.price_digits,
                volume_digits=0,
                status_ascii="00",
                sost_ascii=STATE_IDLE,
                checksum_mode=mode,
            )
            return PollRawResult(address=address, request_bytes=request, response_bytes=reply)

        state = self._get_state(address)
        if cmd == CMD_TEST_ASCII:
            if state.get("price_stage") == "wait_test":
                state["price_stage"] = "wait_stop"
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(
                        address,
                        CMD_TEST_ASCII,
                        state,
                        byte17_override=0x16,
                    ),
                )
            if state["state_code"] == STATE_DISPENSING:
                dose = int(state["dose_ml"])
                disp = int(state["dispensed_ml"])
                if dose > 0:
                    if disp + 500 < dose:
                        state["dispensed_ml"] = disp + 500
                    else:
                        state["dispensed_ml"] = dose
                        state["state_code"] = STATE_COMPLETED
                        state["valve_open"] = False
            return PollRawResult(
                address=address,
                request_bytes=request,
                response_bytes=self._build_live_reply(address, CMD_TEST_ASCII, state),
            )

        if cmd == CMD_RESET_ASCII:
            state["state_code"] = STATE_IDLE
            state["valve_open"] = False
            state["dose_ml"] = 0
            state["dispensed_ml"] = 0
            state["dose_type"] = 0x10
            state["pending_price_kop"] = None
            state["price_stage"] = None
            return PollRawResult(
                address=address,
                request_bytes=request,
                response_bytes=self._build_live_reply(address, CMD_RESET_ASCII, state),
            )

        if cmd == CMD_SET_DOSE_ASCII:
            vol_ml = int(request[11:17].decode("ascii"))
            state["dose_ml"] = vol_ml
            state["dispensed_ml"] = 0
            state["valve_open"] = False
            state["state_code"] = STATE_DOSE_SET
            state["dose_type"] = 0x11
            return PollRawResult(
                address=address,
                request_bytes=request,
                response_bytes=self._build_live_reply(address, CMD_SET_DOSE_ASCII, state),
            )

        if cmd == CMD_START_ASCII:
            if state["state_code"] in {STATE_DOSE_SET, STATE_STOPPED}:
                state["state_code"] = STATE_DISPENSING
                state["valve_open"] = True
            return PollRawResult(
                address=address,
                request_bytes=request,
                response_bytes=self._build_live_reply(address, CMD_START_ASCII, state),
            )

        if cmd == CMD_STOP_ASCII:
            if state.get("price_stage") == "wait_stop":
                pending = state.get("pending_price_kop")
                if isinstance(pending, int) and pending > 0:
                    state["price_kop"] = pending
                state["pending_price_kop"] = None
                state["price_stage"] = None
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(
                        address,
                        CMD_STOP_ASCII,
                        state,
                        byte17_override=0x30,
                    ),
                )
            if state["state_code"] == STATE_DISPENSING:
                state["state_code"] = STATE_STOPPED
                state["valve_open"] = False
            return PollRawResult(
                address=address,
                request_bytes=request,
                response_bytes=self._build_live_reply(address, CMD_STOP_ASCII, state),
            )

        if cmd == CMD_PARAMS_ASCII:
            p_code = request[5:11].decode("ascii")
            v_code = request[11:17].decode("ascii")
            s_code = request[17:19].decode("ascii")
            if p_code == "000016":
                state["buttons_ss"] = True
                state["button_reset"] = True
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(address, CMD_PARAMS_ASCII, state),
                )
            if p_code == "000017":
                state["buttons_ss"] = False
                state["button_reset"] = False
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(address, CMD_PARAMS_ASCII, state),
                )
            if p_code == "000018":
                state["buttons_ss"] = True
                state["button_reset"] = False
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(address, CMD_PARAMS_ASCII, state),
                )
            if p_code == "000015":
                state["pending_price_kop"] = int(v_code)
                state["price_stage"] = "wait_test"
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=b"",
                )
            if p_code in {"000011", "000019"}:
                marker = 0x1A if p_code == "000011" else 0x1B
                cnt = int(state["total_counter_1"] if p_code == "000011" else state["total_counter_2"])
                cnt_s = f"{cnt:010d}".encode("ascii")
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(
                        address,
                        CMD_PARAMS_ASCII,
                        state,
                        price_field=b"00" + cnt_s[:4],
                        volume_field=cnt_s[4:],
                        dose_bits_override=marker,
                    ),
                )
            if p_code in {"000012", "000013"}:
                if p_code == "000013":
                    state["daily_counter"] = 0
                daily_s = f"{int(state['daily_counter']):08d}".encode("ascii")
                prefix = b"0540" if s_code == "01" else f"0{int(state['temp_c_tenths']):03d}".encode("ascii")
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(
                        address,
                        CMD_PARAMS_ASCII,
                        state,
                        price_field=prefix + daily_s[:2],
                        volume_field=daily_s[2:],
                        dose_bits_override=0x18,
                    ),
                )
            if p_code == "000014":
                if s_code == "01":
                    return PollRawResult(
                        address=address,
                        request_bytes=request,
                        response_bytes=self._build_live_reply(
                            address,
                            CMD_PARAMS_ASCII,
                            state,
                            price_field=b"000001",
                            volume_field=b"200005",
                            dose_bits_override=0x19,
                        ),
                    )
                vol_s = f"{int(state['propane_pct']):02d}{int(state['tpr_coef']):04d}".encode("ascii")
                return PollRawResult(
                    address=address,
                    request_bytes=request,
                    response_bytes=self._build_live_reply(
                        address,
                        CMD_PARAMS_ASCII,
                        state,
                        price_field=b"000000",
                        volume_field=vol_s,
                        dose_bits_override=0x19,
                    ),
                )

        return PollRawResult(
            address=address,
            request_bytes=request,
            response_bytes=self._build_live_reply(address, cmd, state),
        )


def build_link(settings: EdgeSettings) -> AskaLink:
    """Создаёт линию связи с АСКА-02 (COM/TTY или встроенный эмулятор) по настройкам узла."""
    if settings.source_mode == "emulator":
        return EmulatorAskaLink(layout=settings.layout)
    return SerialAskaLink(
        port=settings.serial_port,
        baudrate=settings.serial_baudrate,
        timeout_sec=settings.serial_timeout_sec,
        layout=settings.layout,
        inter_frame_delay_sec=settings.inter_frame_delay_sec,
    )


def list_available_serial_ports() -> list[tuple[str, str, str]]:
    """Возвращает список доступных COM-портов: (port, description, hwid)."""
    try:
        from serial.tools import list_ports

        return [(p.device, p.description or "", p.hwid or "") for p in list_ports.comports()]
    except Exception:
        return []
