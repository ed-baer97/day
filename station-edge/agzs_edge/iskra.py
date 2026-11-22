"""Протокол «Искра 1.72» (ООО Техно Проект, v3.10) для УЗСГ-01 / УЗГС-01 через адаптер АСКА-02.

Поддерживает как безопасный мониторинг (команда «Тест», код 0x34), так и полный
цикл управления колонкой при работе с блоком питания без пульта управления:
Сброс (0x37), Задание дозы (0x39), Пуск (0x35), Останов (0x36), Параметры (0x38).
"""

from __future__ import annotations

from dataclasses import dataclass

from agzs_edge.config import FrameLayout, MAX_PUMP_ADDRESS, MIN_PUMP_ADDRESS

SOH = 0x01
STX = 0x02
ETX = 0x03

# Коды команд управления по разделу 3.1.1 Протокола обмена данными v3.10.
CMD_SETUP_ASCII = ord("3")     # 0x33 — «Установка» (установка параметров ГРК)
CMD_TEST_ASCII = ord("4")      # 0x34 — «Тест» (опрос состояния ГРК)
CMD_START_ASCII = ord("5")     # 0x35 — «Пуск» (запуск ГРК)
CMD_STOP_ASCII = ord("6")      # 0x36 — «Останов» (останов ГРК)
CMD_RESET_ASCII = ord("7")     # 0x37 — «Сброс» (сброс состояния ГРК)
CMD_PARAMS_ASCII = ord("8")    # 0x38 — «Параметры» (запрос/установка параметров ГРК)
CMD_SET_DOSE_ASCII = ord("9")  # 0x39 — «Задание дозы»
EXPECTED_FRAME_LEN = 23

# Коды чтения/управления команды 0x38 («Параметры») в 6-байтовом поле Price.
# Калибровка ТПР (0.10) и сброс суточного счётчика (0.13) намеренно исключены для безопасности.
PARAM_PRICE_CODES: dict[str, str] = {
    "0.11": "000011",  # Суммарный счётчик 1
    "0.12": "000012",  # Суточный счётчик + температура/плотность
    "0.14": "000014",  # Параметры ТПР / плотномера
    "0.15": "000015",  # Установка цены
    "0.16": "000016",  # Включить кнопки на ГРК
    "0.17": "000017",  # Выключить кнопки на ГРК
    "0.18": "000018",  # Включить кнопки и заблокировать сброс на ГРК
    "0.19": "000019",  # Суммарный счётчик 2
}

# Поле Code ответа «Тест» протокола Искра 1.72 / v3.10.
STATE_DOSE_SET = "01"     # Готовность к пуску
STATE_REMAINDER = "02"    # Остаток дозы (устаревшее, держим как идущий налив)
STATE_DISPENSING = "03"   # Пуск
STATE_STOPPED = "04"      # Останов
STATE_IDLE = "05"         # Сброс, дозы нет
STATE_ERROR = "06"        # Авария
STATE_COMPLETED = "07"    # Останов (табл. 3.2.2; для новой дозы требуется «Сброс» 0x37 в '05')

STATE_NAMES: dict[str, str] = {
    STATE_DOSE_SET: "DOSE_SET",
    STATE_REMAINDER: "REMAINDER",
    STATE_DISPENSING: "DISPENSING",
    STATE_STOPPED: "STOPPED",
    STATE_IDLE: "IDLE",
    STATE_ERROR: "ERROR",
    STATE_COMPLETED: "COMPLETED",
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
    completed_volume_ml: int | None = None

    @property
    def raw_hex(self) -> str:
        return self.raw_bytes.hex(" ").upper()

    @property
    def volume_raw(self) -> str:
        return self.raw_bytes[11:17].decode("ascii", errors="replace") if len(self.raw_bytes) >= 17 else "000000"

    @property
    def reported_volume_ml(self) -> int:
        return self.completed_volume_ml if self.completed_volume_ml is not None else self.volume_ml

    @property
    def is_v310_status(self) -> bool:
        return self.flags_raw.startswith("P")

    @property
    def is_mass_mode(self) -> bool:
        """Биты 7–6 байта 19 (Sost) == 0;1 (0x40) по табл. 3.2.2: объём в кг, в Price — плотность."""
        return len(self.raw_bytes) > 19 and (self.sost_byte19 & 0xC0) == 0x40

    @property
    def density_kg_per_l(self) -> float | None:
        """Плотность СУГ (кг/л) из поля Price в режиме килограммов."""
        if self.is_mass_mode and self.price_raw.isdigit():
            val = int(self.price_raw)
            if val <= 0:
                return None
            return val / 100_000.0 if val > 1000 else val / 1000.0
        return None

    @property
    def effective_volume_ml(self) -> int:
        """Объём в миллилитрах (при отпуске в килограммах пересчитывается через плотность)."""
        vol = self.reported_volume_ml
        if not self.is_mass_mode:
            return vol
        density = self.density_kg_per_l
        if density is not None and 0.3 <= density <= 1.0:
            return int(round(vol / density))
        return vol

    @property
    def preset_dose_ml(self) -> int | None:
        """Заданная доза в миллилитрах, когда в состоянии != '05' поле Price несёт уставку по п. 3.2.1."""
        if (
            self.state_code != STATE_IDLE
            and self.is_v310_status
            and not self.is_mass_mode
            and self.dose_type_bits not in {0x12, 0x15}
            and self.price_raw.isdigit()
        ):
            return int(self.price_raw) * 10
        return None

    @property
    def preset_amount(self) -> float | None:
        """Заданная доза в деньгах (биты 0..4 байта 17 == 12h/15h по табл. 3.2.1)."""
        if (
            self.state_code != STATE_IDLE
            and self.is_v310_status
            and not self.is_mass_mode
            and self.dose_type_bits in {0x12, 0x15}
            and self.price_raw.isdigit()
        ):
            return int(self.price_raw) / 100.0
        return None

    @property
    def is_dispensing(self) -> bool:
        return self.state_code in {STATE_DISPENSING, STATE_REMAINDER}

    @property
    def is_finished_state(self) -> bool:
        return self.state_code in {STATE_IDLE, STATE_COMPLETED, STATE_STOPPED}

    @property
    def has_protocol_alarm(self) -> bool:
        return self.error_code != "00" or self.state_code == STATE_ERROR or self.column_error_code > 0

    @property
    def status_byte17(self) -> int:
        return self.raw_bytes[17] if len(self.raw_bytes) > 17 else 0

    @property
    def status_byte18(self) -> int:
        return self.raw_bytes[18] if len(self.raw_bytes) > 18 else 0

    @property
    def sost_byte19(self) -> int:
        return self.raw_bytes[19] if len(self.raw_bytes) > 19 else 0

    @property
    def valve_open(self) -> bool:
        """Бит 7 байта 17 по табл. 3.2.1: 1 = клапан открыт, 0 = закрыт."""
        return bool(self.status_byte17 & 0x80)

    @property
    def start_stop_buttons_enabled(self) -> bool:
        """Бит 6 байта 17 по табл. 3.2.1: 1 = кнопки ПУСК/СТОП на колонке включены."""
        return bool(self.status_byte17 & 0x40)

    @property
    def reset_button_enabled(self) -> bool:
        """Бит 5 байта 17 по табл. 3.2.1: 1 = кнопка СБРОС на колонке включена, 0 = заблокирована."""
        return bool(self.status_byte17 & 0x20)

    @property
    def dose_type_bits(self) -> int:
        """Биты 0–4 байта 17 по табл. 3.2.1 (10h=сброс, 11h/14h=литры, 12h/15h=деньги)."""
        return self.status_byte17 & 0x1F

    @property
    def column_error_code(self) -> int:
        """Код ошибки колонки 1..4 из битов 0–5 байта 19 (табл. 3.2.2, Приложение 6)."""
        if len(self.raw_bytes) <= 19:
            return 0
        bits = self.sost_byte19 & 0x3F
        if 0x31 <= bits <= 0x34:
            return bits - 0x30
        return 0

    @property
    def is_locked_in_stop(self) -> bool:
        """True, если колонка в останове ('04'/'07') при выключенной кнопке СБРОС (бит 5 = 0)."""
        return self.state_code in {STATE_COMPLETED, STATE_STOPPED} and not self.reset_button_enabled

    @property
    def is_parameter_readout(self) -> bool:
        """True, если кадр несёт ответ чтения/установки параметров (cmd 0x38 или маркеры 16h, 18h..1Bh в байте 17)."""
        return self.command_code == CMD_PARAMS_ASCII or (
            self.is_v310_status and self.dose_type_bits in {0x16, 0x18, 0x19, 0x1A, 0x1B}
        )


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


def _format_six_field(value: int | str, field_name: str) -> bytes:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0 or value > 999_999:
            raise ValueError(f"Поле {field_name} должно быть в диапазоне 0..999999, получено: {value}")
        return f"{value:06d}".encode("ascii")
    text = str(value)
    if len(text) < 6 and text.isdigit():
        text = text.zfill(6)
    if len(text) != 6:
        raise ValueError(f"Поле {field_name} должно состоять ровно из 6 ASCII-символов, получено: {value!r}")
    return text.encode("ascii")


def build_command_frame(
    address: int,
    command_ascii: int,
    *,
    price_digits: int | str = 0,
    volume_digits: int | str = 0,
    status_ascii: str = "00",
    sost_ascii: str = "00",
    checksum_mode: str = "xor",
) -> bytes:
    """Собирает 23-байтный кадр команды управления АСУ → АСКА по Протоколу v3.10."""
    if not isinstance(address, int) or isinstance(address, bool) or address < MIN_PUMP_ADDRESS or address > MAX_PUMP_ADDRESS:
        raise ValueError(
            f"Адрес колонки должен быть целым числом {MIN_PUMP_ADDRESS}..{MAX_PUMP_ADDRESS}, получено: {address!r}"
        )
    if not isinstance(command_ascii, int) or not 0 <= command_ascii <= 0xFF:
        raise ValueError(f"Код команды должен быть байтом 0..255, получено: {command_ascii!r}")
    if len(status_ascii) != 2 or len(sost_ascii) != 2:
        raise ValueError("Поля status_ascii и sost_ascii должны состоять ровно из 2 ASCII-символов")

    body = (
        f"{address:02d}".encode("ascii")
        + bytes([command_ascii, STX])
        + _format_six_field(price_digits, "Price")
        + _format_six_field(volume_digits, "Volume")
        + status_ascii.encode("ascii")
        + sost_ascii.encode("ascii")
        + bytes([ETX])
    )
    mode = "xor" if checksum_mode == "any" else checksum_mode
    return bytes([SOH]) + body + bytes([compute_bcc(body, mode)])


def build_test_command(address: int, *, checksum_mode: str = "xor") -> bytes:
    """Собирает запрос «Тест» (код 0x34) протокола v3.10 для адреса 1..8."""
    return build_command_frame(
        address,
        CMD_TEST_ASCII,
        price_digits=0,
        volume_digits=0,
        status_ascii="00",
        sost_ascii="00",
        checksum_mode=checksum_mode,
    )


def build_reset_command(address: int, *, status_ascii: str = "00", checksum_mode: str = "xor") -> bytes:
    """Собирает команду «Сброс» (код 0x37, п. 4.4) для перевода ГРК из '07'/'04' в '05'."""
    return build_command_frame(
        address,
        CMD_RESET_ASCII,
        price_digits=0,
        volume_digits=0,
        status_ascii=status_ascii,
        sost_ascii="00",
        checksum_mode=checksum_mode,
    )


def build_set_dose_command(
    address: int,
    volume_ml: int,
    *,
    price_digits: int | str = 0,
    status_ascii: str = "00",
    checksum_mode: str = "xor",
) -> bytes:
    """Собирает команду «Задание дозы» (код 0x39, п. 4.5). Для «до полного» volume_ml=999000."""
    if not isinstance(volume_ml, int) or isinstance(volume_ml, bool) or volume_ml <= 0 or volume_ml > 999_999:
        raise ValueError(f"Доза налива (мл) должна быть в диапазоне 1..999999, получено: {volume_ml!r}")
    return build_command_frame(
        address,
        CMD_SET_DOSE_ASCII,
        price_digits=price_digits,
        volume_digits=volume_ml,
        status_ascii=status_ascii,
        sost_ascii="00",
        checksum_mode=checksum_mode,
    )


def build_start_command(address: int, *, checksum_mode: str = "xor") -> bytes:
    """Собирает команду «Пуск» (код 0x35, п. 4.2) для запуска налива из состояния '01' или '04'."""
    return build_command_frame(
        address,
        CMD_START_ASCII,
        price_digits=0,
        volume_digits=0,
        status_ascii="00",
        sost_ascii="00",
        checksum_mode=checksum_mode,
    )


def build_stop_command(address: int, *, checksum_mode: str = "xor") -> bytes:
    """Собирает команду «Останов» (код 0x36, п. 4.3) для остановки налива из состояния '03'."""
    return build_command_frame(
        address,
        CMD_STOP_ASCII,
        price_digits=0,
        volume_digits=0,
        status_ascii="00",
        sost_ascii="00",
        checksum_mode=checksum_mode,
    )


def build_param_command(
    address: int,
    param_code: str,
    *,
    volume_digits: int | str = 0,
    status_ascii: str = "00",
    checksum_mode: str = "xor",
) -> bytes:
    """Собирает команду «Параметры» (код 0x38, разделы 1–2 описания параметров)."""
    code = param_code.strip()
    if code in {"000010", "000013"}:
        raise ValueError(
            f"Код параметра {param_code!r} запрещён: запись коэффициента ТПР (0.10) и сброс суточного счётчика (0.13) отключены."
        )
    if code in PARAM_PRICE_CODES:
        price_field = PARAM_PRICE_CODES[code]
    elif len(code) == 6 and code.isdigit():
        price_field = code
    else:
        raise ValueError(f"Неизвестный код параметра: {param_code!r}")
    return build_command_frame(
        address,
        CMD_PARAMS_ASCII,
        price_digits=price_field,
        volume_digits=volume_digits,
        status_ascii=status_ascii,
        sost_ascii="00",
        checksum_mode=checksum_mode,
    )


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
    """Собирает эталонный 23-байтный ответ «Тест» протокола Искра 1.72.

    Раскладка: SOH, адрес из 2 цифр, '4', STX, цена 6, объём 6, ошибка 2, состояние 2, ETX, CRC.
    Параметр flags оставлен для старых вызовов и в кадр не входит.
    """
    del flags
    if address < MIN_PUMP_ADDRESS or address > MAX_PUMP_ADDRESS:
        raise ValueError(f"Адрес должен быть в диапазоне {MIN_PUMP_ADDRESS}..{MAX_PUMP_ADDRESS}")
    if len(state_code) != 2 or len(error_code) != 2:
        raise ValueError("Поля state_code и error_code должны состоять ровно из 2 ASCII-символов")
    if volume_ml < 0 or volume_ml > 999_999:
        raise ValueError("volume_ml должен помещаться в 6 десятичных цифр (0..999999)")

    price_str = f"{int(price_digits):06d}" if isinstance(price_digits, int) and not isinstance(price_digits, bool) else str(price_digits).zfill(6)
    if len(price_str) != 6 or not price_str.isdigit():
        raise ValueError("Поле цены должно состоять из 6 цифр")

    frame = build_command_frame(
        address,
        CMD_TEST_ASCII,
        price_digits=price_str,
        volume_digits=volume_ml,
        status_ascii=error_code,
        sost_ascii=state_code,
        checksum_mode=checksum_mode,
    )
    assert len(frame) == EXPECTED_FRAME_LEN
    return frame


def _read_error_field(field: bytes, *, cmd_code: int = CMD_TEST_ASCII) -> tuple[str, str]:
    """Возвращает `(код ошибки, слово статуса линии)`.

    В legacy-ответах две ASCII-цифры 00..06 — код ошибки протокола («00» — нет аварии, «06» — авария).
    На УЗСГ-01 через АСКА-02 байт 17 является битовой маской Status (табл. 3.2.1):
    биты 7 (клапан), 6 (кнопки пуск/стоп), 5 (кнопка сброс), 0–4 (тип дозы / маркер параметра),
    а байт 18 содержит дополнительный флаг (например `0x88`…`0x9F` или `0x00`).
    """
    if cmd_code != CMD_PARAMS_ASCII and len(field) == 2 and field[0] == 0x30 and 0x30 <= field[1] <= 0x36:
        return field.decode("ascii"), ""
    if len(field) == 2 and (
        (field[1] & 0x80) == 0x80
        or (field[0] & 0x10) == 0x10
        or 0x10 <= (field[0] & 0x7F) <= 0x7F
    ):
        return "00", f"P{field[1]:02X}"
    return field.hex().upper(), field.hex().upper()


def _decode_price(price_raw: str) -> float:
    """Переводит 6 цифр цены из кадра в рубли/тенге за литр (табл. 3.1/3.2: цена в копейках/тиынах)."""
    return int(price_raw) / 100.0


def _completed_volume_in_price_field(state_code: str, flags_raw: str, price_raw: str, volume_raw: str) -> int | None:
    """По п. 3.2.1 Протокола v3.10 при состоянии != '05' поле Price несёт уставку дозы, а не отпуск.

    Реальный налитый объём всегда приходит в поле Volume (байты 11–16).
    Подставлять уставку (например 090000 = 900 л «до полного») как налитый объём нельзя,
    иначе холостое нажатие «ПУСК» при Volume=000000 ошибочно спишет 9000 мл в БД.
    """
    del state_code, flags_raw, price_raw, volume_raw
    return None


def _validate_frame_envelope(raw: bytes, cfg: FrameLayout) -> int:
    """Проверяет заголовок/хвост/КС 23-байтного кадра Искра 1.72 и возвращает адрес колонки."""
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
    if raw[4] != STX:
        raise IskraFrameError(f"Отсутствует маркер STX (0x02) на позиции 4: 0x{raw[4]:02X}")
    try:
        address = int(raw[cfg.addr_offset : cfg.addr_offset + 2].decode("ascii"))
    except ValueError as exc:
        raise IskraFrameError(
            f"Некорректный адрес колонки в байтах [{cfg.addr_offset}:{cfg.addr_offset + 2}]: "
            f"{raw[cfg.addr_offset : cfg.addr_offset + 2].hex(' ').upper()}"
        ) from exc
    if address < MIN_PUMP_ADDRESS or address > MAX_PUMP_ADDRESS:
        raise IskraFrameError(f"Адрес колонки вне диапазона {MIN_PUMP_ADDRESS}..{MAX_PUMP_ADDRESS}: {address}")
    return address


def _decode_sost_field(field: bytes) -> str:
    """Нормализует 2-байтовое поле Sost (байты 19..20) по табл. 3.2.2 Протокола v3.10.

    Байт 19 (Sost[19]) в битах 0..5 содержит код ошибки колонки (0x30..0x34),
    а в битах 6..7 может содержать статусные флаги; байт 20 несёт состояние 01..07.
    """
    if len(field) == 2 and 0x30 <= (field[0] & 0x3F) <= 0x34 and 0x31 <= (field[1] & 0x7F) <= 0x37:
        return f"0{chr(field[1] & 0x7F)}"
    return field.decode("ascii")


def parse_iskra_frame(raw: bytes, layout: FrameLayout | None = None) -> IskraTelemetryFrame:
    """Разбирает и проверяет 23-байтный кадр ответа «Искра 1.72»."""
    cfg = layout or FrameLayout()
    address = _validate_frame_envelope(raw, cfg)

    cmd_code = raw[cfg.cmd_offset]
    try:
        state_code = _decode_sost_field(raw[cfg.state_slice[0] : cfg.state_slice[1]])
        price_raw = raw[cfg.price_slice[0] : cfg.price_slice[1]].decode("ascii")
        volume_raw = raw[cfg.volume_slice[0] : cfg.volume_slice[1]].decode("ascii")
    except UnicodeDecodeError as exc:
        raise IskraFrameError(f"Не-ASCII символы в полях данных кадра: {raw.hex(' ').upper()}") from exc
    error_code, flags_raw = _read_error_field(
        raw[cfg.error_slice[0] : cfg.error_slice[1]],
        cmd_code=cmd_code,
    )

    is_param_frame = cmd_code == CMD_PARAMS_ASCII or (
        flags_raw.startswith("P") and (raw[17] & 0x1F) in {0x16, 0x18, 0x19, 0x1A, 0x1B}
    )

    if not is_param_frame:
        if not price_raw.isdigit() or len(price_raw) != 6:
            raise IskraFrameError(f"Поле цены должно содержать 6 цифр, получено: {price_raw!r}")
        if not volume_raw.isdigit() or len(volume_raw) != 6:
            raise IskraFrameError(f"Поле объёма должно содержать 6 цифр, получено: {volume_raw!r}")

    volume_ml = int(volume_raw) if volume_raw.isdigit() else 0
    completed_volume_ml = _completed_volume_in_price_field(state_code, flags_raw, price_raw, volume_raw) if price_raw.isdigit() and volume_raw.isdigit() else None
    is_mass_frame = len(raw) > 19 and (raw[19] & 0xC0) == 0x40
    # На живой колонке УЗСГ-01 (статус P..) по п. 3.2.1 Протокола v3.10 цена за литр передаётся
    # только в состоянии сброса ('05') с маркером 0x10, а в состояниях '01'/'03'/'04'/'07' в поле Price стоит уставка дозы
    # (или плотность СУГ при режиме массы в байте 19, или счётчик/датчик при маркере != 0x10).
    is_volume_in_price_slot = (
        is_param_frame
        or not price_raw.isdigit()
        or completed_volume_ml is not None
        or is_mass_frame
        or (flags_raw.startswith("P") and (raw[17] & 0x1F) != 0x10)
        or (state_code != STATE_IDLE and flags_raw.startswith("P"))
    )
    price_kzt = 0.0 if is_volume_in_price_slot else _decode_price(price_raw)
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
        completed_volume_ml=completed_volume_ml,
    )
