"""Протокол «Искра 1.72» для УЗГС-01 (Технопроект) через адаптер АСКА-02.

ВАЖНО (аппаратная безопасность):
Этот модуль реализует ИСКЛЮЧИТЕЛЬНО команду опроса состояния «Тест» (код 4).
Формирование команд пуска, задания дозы, установки цены или останова физически
не предусмотрено: пуск и остановка колонки выполняются только аппаратно с пульта УЗГС-01.
"""

from __future__ import annotations

from dataclasses import dataclass

from agzs_edge.config import FrameLayout

SOH = 0x01
ETX = 0x03
CMD_TEST_ASCII = ord("4")  # 0x34 — код команды «Тест» в протоколе Искра 1.72
EXPECTED_FRAME_LEN = 23

# Коды состояния колонки в кадре ответа «Тест»
STATE_IDLE = "00"        # Свободна / ожидание
STATE_DOSE_SET = "01"    # Доза набрана на пульте, ожидание пуска
STATE_DISPENSING = "02"  # Идёт отпуск газа (клапан/насос включены)
STATE_STOPPED = "03"     # Остановлена до окончания дозы (кнопка Стоп / отсечка)
STATE_COMPLETED = "04"   # Отпуск завершён (доза выдана или завершён налив «до полного»)
STATE_ERROR = "06"       # Авария в кадре (код 06)

STATE_NAMES: dict[str, str] = {
    STATE_IDLE: "IDLE",
    STATE_DOSE_SET: "DOSE_SET",
    STATE_DISPENSING: "DISPENSING",
    STATE_STOPPED: "STOPPED",
    STATE_COMPLETED: "COMPLETED",
    STATE_ERROR: "ERROR",
}


class IskraFrameError(ValueError):
    """Ошибка длины, формата или контрольной суммы кадра Искра 1.72."""


@dataclass(frozen=True)
class IskraTelemetryFrame:
    """Разобранный 23-байтный кадр ответа «Искра 1.72» на команду «Тест»."""

    address: int
    command_code: int
    state_code: str
    state_name: str
    error_code: str
    price_raw: str
    price_kzt_per_liter: float
    volume_ml: int
    flags_raw: str
    checksum_byte: int
    raw_bytes: bytes

    @property
    def raw_hex(self) -> str:
        return self.raw_bytes.hex(" ").upper()

    @property
    def is_dispensing(self) -> bool:
        return self.state_code == STATE_DISPENSING

    @property
    def is_finished_state(self) -> bool:
        return self.state_code in {STATE_IDLE, STATE_COMPLETED, STATE_STOPPED}

    @property
    def has_protocol_alarm(self) -> bool:
        return self.error_code != "00" or self.state_code == STATE_ERROR


def compute_bcc(payload_after_soh_including_etx: bytes, mode: str = "xor") -> int:
    """Вычисляет байт контрольной суммы (BCC) для кадра Искра 1.72.

    Поддерживаемые режимы:
      - 'xor'  : побитовый XOR всех байт после SOH (включая ETX)
      - 'sum7' : сумма байт по модулю 128 с установкой/сбросом бита (0x7F)
      - 'sum8' : младший байт суммы всех байт (sum & 0xFF)
    """
    if mode == "xor":
        acc = 0
        for b in payload_after_soh_including_etx:
            acc ^= b
        return acc & 0xFF
    if mode == "sum7":
        return sum(payload_after_soh_including_etx) & 0x7F
    if mode == "sum8":
        return sum(payload_after_soh_including_etx) & 0xFF
    raise ValueError(f"Неизвестный режим контрольной суммы: {mode}")


def verify_frame_checksum(frame: bytes, layout: FrameLayout | None = None) -> bool:
    """Проверяет контрольную сумму кадра по выбранному в FrameLayout режиму."""
    cfg = layout or FrameLayout()
    if len(frame) != cfg.frame_length:
        return False
    received = frame[cfg.bcc_offset]
    body = frame[1 : cfg.bcc_offset]
    if cfg.checksum_mode == "any":
        return received in {
            compute_bcc(body, "xor"),
            compute_bcc(body, "sum7"),
            compute_bcc(body, "sum8"),
        }
    return received == compute_bcc(body, cfg.checksum_mode)


def build_test_command(address: int, *, checksum_mode: str = "xor") -> bytes:
    """Собирает запрос «Тест» (код 4) протокола Искра 1.72 для адреса 1..6.

    Формат кадра запроса (5 байт):
      [0] 0x01 (SOH)
      [1] ASCII адрес колонки ('1'..'6', 0x31..0x36)
      [2] 0x34 ('4' — команда «Тест»)
      [3] 0x03 (ETX)
      [4] BCC (контрольная сумма по байтам [1..3])
    """
    if not isinstance(address, int) or address < 1 or address > 6:
        raise ValueError(f"Адрес колонки должен быть целым числом 1..6, получено: {address!r}")
    addr_byte = ord(str(address))
    body = bytes([addr_byte, CMD_TEST_ASCII, ETX])
    mode = "xor" if checksum_mode == "any" else checksum_mode
    bcc = compute_bcc(body, mode)
    return bytes([SOH]) + body + bytes([bcc])


def build_test_response_frame(
    *,
    address: int,
    state_code: str = STATE_IDLE,
    error_code: str = "00",
    price_digits: int | str = 10000,
    volume_ml: int = 0,
    flags: str = "00",
    checksum_mode: str = "xor",
) -> bytes:
    """Собирает эталонный 23-байтный ответный кадр «Искра 1.72» (для тестов и эмулятора).

    Раскладка (23 байта):
      1 (SOH) + 1 (addr) + 1 ('4') + 2 (state) + 2 (err) + 6 (price) + 6 (volume_ml) + 2 (flags) + 1 (ETX) + 1 (BCC) = 23
    """
    if address < 1 or address > 6:
        raise ValueError("Адрес должен быть в диапазоне 1..6")
    if len(state_code) != 2 or len(error_code) != 2 or len(flags) != 2:
        raise ValueError("Поля state_code, error_code и flags должны состоять ровно из 2 ASCII-символов")
    if volume_ml < 0 or volume_ml > 999_999:
        raise ValueError("volume_ml должен помещаться в 6 десятичных цифр (0..999999)")

    price_str = f"{int(price_digits):06d}" if isinstance(price_digits, int) else str(price_digits).zfill(6)
    if len(price_str) != 6 or not price_str.isdigit():
        raise ValueError("Поле цены должно состоять из 6 цифр")

    vol_str = f"{volume_ml:06d}"
    ascii_payload = f"{address}4{state_code}{error_code}{price_str}{vol_str}{flags}".encode("ascii")
    body = ascii_payload + bytes([ETX])
    mode = "xor" if checksum_mode == "any" else checksum_mode
    bcc = compute_bcc(body, mode)
    frame = bytes([SOH]) + body + bytes([bcc])
    assert len(frame) == EXPECTED_FRAME_LEN
    return frame


def _decode_price(price_raw: str) -> float:
    """Переводит 6 цифр цены из кадра в тенге за литр.

    Если в кадре передаются тиыны/сотые доли (например '010000' -> 100.00 ₸),
    делим на 100; если целые тенге с ведущими нулями ('000100' -> 100 ₸), оставляем целым.
    """
    raw_val = int(price_raw)
    if raw_val >= 1000 and raw_val % 100 == 0:
        return raw_val / 100.0
    return float(raw_val)


def parse_iskra_frame(raw: bytes, layout: FrameLayout | None = None) -> IskraTelemetryFrame:
    """Разбирает и проверяет 23-байтный кадр ответа «Искра 1.72»."""
    cfg = layout or FrameLayout()
    if len(raw) != cfg.frame_length:
        raise IskraFrameError(
            f"Неверная длина кадра Искра: ожидалось {cfg.frame_length} байт, получено {len(raw)} ({raw.hex(' ').upper()})"
        )
    if raw[0] != cfg.soh_byte:
        raise IskraFrameError(
            f"Кадр не начинается с SOH (0x{cfg.soh_byte:02X}): первый байт 0x{raw[0]:02X}"
        )
    if raw[cfg.etx_offset] != cfg.etx_byte:
        raise IskraFrameError(
            f"Отсутствует маркер ETX (0x{cfg.etx_byte:02X}) на позиции {cfg.etx_offset}: 0x{raw[cfg.etx_offset]:02X}"
        )
    if not verify_frame_checksum(raw, cfg):
        expected = compute_bcc(raw[1 : cfg.bcc_offset], "xor" if cfg.checksum_mode == "any" else cfg.checksum_mode)
        raise IskraFrameError(
            f"Неверная контрольная сумма кадра: в кадре 0x{raw[cfg.bcc_offset]:02X}, ожидалось 0x{expected:02X}"
        )

    try:
        addr_char = chr(raw[cfg.addr_offset])
        address = int(addr_char)
    except ValueError as exc:
        raise IskraFrameError(f"Некорректный адрес колонки в байте [{cfg.addr_offset}]: 0x{raw[cfg.addr_offset]:02X}") from exc

    if address < 1 or address > 6:
        raise IskraFrameError(f"Адрес колонки вне диапазона 1..6: {address}")

    cmd_code = raw[cfg.cmd_offset]
    try:
        state_code = raw[cfg.state_slice[0] : cfg.state_slice[1]].decode("ascii")
        error_code = raw[cfg.error_slice[0] : cfg.error_slice[1]].decode("ascii")
        price_raw = raw[cfg.price_slice[0] : cfg.price_slice[1]].decode("ascii")
        volume_raw = raw[cfg.volume_slice[0] : cfg.volume_slice[1]].decode("ascii")
        flags_raw = raw[cfg.flags_slice[0] : cfg.flags_slice[1]].decode("ascii")
    except UnicodeDecodeError as exc:
        raise IskraFrameError(f"Не-ASCII символы в полях данных кадра: {raw.hex(' ').upper()}") from exc

    if not price_raw.isdigit() or len(price_raw) != 6:
        raise IskraFrameError(f"Поле цены должно содержать 6 цифр, получено: {price_raw!r}")
    if not volume_raw.isdigit() or len(volume_raw) != 6:
        raise IskraFrameError(f"Поле объёма должно содержать 6 цифр, получено: {volume_raw!r}")

    volume_ml = int(volume_raw)
    price_kzt = _decode_price(price_raw)
    state_name = STATE_NAMES.get(state_code, f"UNKNOWN_{state_code}")

    return IskraTelemetryFrame(
        address=address,
        command_code=cmd_code,
        state_code=state_code,
        state_name=state_name,
        error_code=error_code,
        price_raw=price_raw,
        price_kzt_per_liter=price_kzt,
        volume_ml=volume_ml,
        flags_raw=flags_raw,
        checksum_byte=raw[cfg.bcc_offset],
        raw_bytes=bytes(raw),
    )
