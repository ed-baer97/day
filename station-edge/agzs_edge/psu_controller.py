"""Контроллер связки «Компьютер — АСКА-02 — Блок питания — УЗСГ-01» (Протокол v3.10).

При замене штатного Пульта управления (ПУ) на Блок питания (БП) и АСКА-02:
- в БП нет процессора ПП2 и кнопок СБРОС/ПУСК/СТОП;
- кнопка СБРОС на самой колонке по умолчанию заблокирована (бит 5 байта 17 = 0);
- после каждой заправки или 10-секундного останова по ДТФ колонка переходит
  в состояние '07' (Останов) и ждёт от компьютера команду «Сброс» (0x37).

Этот модуль реализует полный цикл управления и снятия блокировки по Протоколу v3.10:
- «Тест» (0x34) — диагностика состояния, клапана, блокировки кнопок и ошибок 01..04;
- «Сброс» (0x37) — вывод колонки из блокировки '07'/'04' в готовность '05';
- «Задание дозы» (0x39) — задание дозы в миллилитрах или «до полного» (999 л);
- «Пуск» (0x35) и «Останов» (0x36);
- «Параметры» (0x38) — управление кнопками колонки (0.16/0.17/0.18), ценой (0.15)
  и чтение счётчиков/датчиков (0.11, 0.19, 0.12, 0.14).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from agzs_edge.config import FrameLayout
from agzs_edge.iskra import (
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_NAMES,
    STATE_STOPPED,
    IskraFrameError,
    IskraTelemetryFrame,
    build_param_command,
    build_reset_command,
    build_set_dose_command,
    build_start_command,
    build_stop_command,
    build_test_command,
    parse_iskra_frame,
)
from agzs_edge.serial_link import AskaLink, PollRawResult

logger = logging.getLogger(__name__)


def send_buttons_param_to_pumps(
    link: AskaLink,
    addresses: tuple[int, ...],
    param_code: str,
    *,
    checksum_mode: str,
    last_frames: dict[int, IskraTelemetryFrame] | None = None,
    reset_after: bool = True,
) -> tuple[list[int], list[tuple[int, str]]]:
    """Отправляет команду режима кнопок (0.16/0.17/0.18) на список адресов колонок.

    reset_after=False не шлёт 0x37 после 000016: штатный опрос не сбрасывает колонку.
    """
    succeeded: list[int] = []
    errors: list[tuple[int, str]] = []
    for address in addresses:
        frame = last_frames.get(address) if last_frames else None
        if frame is None and last_frames is None:
            poll_res = link.poll_test(address, checksum_mode=checksum_mode)
            if poll_res.error_message:
                errors.append((address, poll_res.error_message))
                continue
            if poll_res.has_response:
                try:
                    frame = parse_iskra_frame(
                        poll_res.response_bytes,
                        FrameLayout(checksum_mode=checksum_mode),
                    )
                except IskraFrameError as exc:
                    errors.append((address, str(exc)))
                    continue
        if frame is not None and (frame.is_dispensing or frame.valve_open):
            errors.append((address, "колонка выполняет налив"))
            continue
        if frame is not None and frame.state_code != STATE_IDLE:
            reset_req = build_reset_command(address, checksum_mode=checksum_mode)
            reset_res = link.send_command(address, reset_req)
            if reset_res.error_message:
                errors.append((address, reset_res.error_message))
                continue
        req = build_param_command(address, param_code, volume_digits=0, checksum_mode=checksum_mode)
        res = link.send_command(address, req)
        if res.error_message:
            errors.append((address, res.error_message))
            continue
        if reset_after and param_code == "0.16":
            reset_req = build_reset_command(address, checksum_mode=checksum_mode)
            reset_after = link.send_command(address, reset_req)
            if reset_after.error_message:
                errors.append((address, reset_after.error_message))
                continue
        succeeded.append(address)
    return succeeded, errors

COLUMN_ERROR_DESCRIPTIONS: dict[int, str] = {
    0: "Ошибок колонки нет",
    1: "Ошибка 01: последовательность импульсов от турбинки (разъём/зазор/геометрия ТПР)",
    2: "Ошибка 02: нет сигнала датчика импульсов турбинки (обрыв/разъём/индуктивный датчик)",
    3: "Ошибка 03: переполнение счётчика текущей заправки (>999 л)",
    4: "Ошибка 04: превышение максимально возможной скорости заправки (>45 л/мин)",
}

STATE_DESCRIPTIONS_RU: dict[str, str] = {
    "01": "Задание дозы (готовность к пуску)",
    "02": "Остаток дозы",
    "03": "Пуск (идёт заправка)",
    "04": "Останов (возможен повторный пуск или сброс)",
    "05": "Сброс (готовность к заданию дозы)",
    "06": "Авария",
    "07": "Останов (для новой дозы нужен СБРОС 0x37)",
}


class PsuControlError(RuntimeError):
    """Ошибка обмена или недопустимого состояния при управлении УЗСГ-01."""


@dataclass(frozen=True)
class ResetResult:
    """Результат выполнения команды «Сброс» (0x37)."""

    before: IskraTelemetryFrame
    reply: IskraTelemetryFrame | None
    after: IskraTelemetryFrame
    reset_sent: bool
    unlocked: bool
    message: str


@dataclass(frozen=True)
class CountersReport:
    """Показания счётчиков и параметров УЗСГ-01 по команде 0x38."""

    address: int
    mass_mode: bool
    total_counter_1_raw: str | None
    total_counter_1_value: float | None
    total_counter_2_raw: str | None
    total_counter_2_value: float | None
    daily_counter_raw: str | None
    daily_counter_value: float | None
    temperature_c: float | None
    density_kg_m3: float | None
    propane_percent: int | None
    tpr_liters_per_pulse: float | None
    final_status: IskraTelemetryFrame

    def render(self) -> str:
        unit = "кг" if self.mass_mode else "л"
        lines = [f"=== Счётчики и параметры УЗСГ-01 (адрес {self.address}) ==="]
        if self.total_counter_1_value is not None:
            lines.append(
                f"  Суммарный счётчик 1 (0.11): {self.total_counter_1_value:.2f} {unit} "
                f"(raw={self.total_counter_1_raw})"
            )
        else:
            lines.append("  Суммарный счётчик 1 (0.11): нет данных")

        if self.total_counter_2_value is not None:
            lines.append(
                f"  Суммарный счётчик 2 (0.19): {self.total_counter_2_value:.2f} {unit} "
                f"(raw={self.total_counter_2_raw})"
            )

        if self.daily_counter_value is not None:
            lines.append(
                f"  Суточный счётчик    (0.12): {self.daily_counter_value:.2f} {unit} "
                f"(raw={self.daily_counter_raw})"
            )
        else:
            lines.append("  Суточный счётчик    (0.12): нет данных")

        if self.temperature_c is not None:
            lines.append(f"  Средняя температура (0.12): {self.temperature_c:+.1f} °C")
        if self.density_kg_m3 is not None:
            unit_d = "кг/л" if self.density_kg_m3 < 2.0 else "кг/м³"
            lines.append(f"  Средняя плотность   (0.12): {self.density_kg_m3:.3f} {unit_d}")
        if self.tpr_liters_per_pulse is not None or self.propane_percent is not None:
            lines.append(
                f"  Параметры ТПР       (0.14): коэф={self.tpr_liters_per_pulse} л/имп, "
                f"пропан={self.propane_percent} %"
            )
        lines.append(
            f"  Состояние после сброса    : {self.final_status.state_code} "
            f"({STATE_DESCRIPTIONS_RU.get(self.final_status.state_code, self.final_status.state_name)})"
        )
        return "\n".join(lines)


def _decode_dose_type_ru(bits: int) -> str:
    if bits == 0x10:
        return "0x10 (сброс)"
    if bits in {0x11, 0x14}:
        return f"0x{bits:02X} (доза в литрах)"
    if bits in {0x12, 0x15}:
        return f"0x{bits:02X} (доза в деньгах)"
    return f"0x{bits:02X}"


def format_detailed_status(frame: IskraTelemetryFrame) -> str:
    """Формирует подробную карточку состояния колонки УЗСГ-01 по Протоколу v3.10."""
    state_ru = STATE_DESCRIPTIONS_RU.get(
        frame.state_code, STATE_NAMES.get(frame.state_code, frame.state_name)
    )
    valve_text = "ОТКРЫТ" if frame.valve_open else "ЗАКРЫТ"
    ss_text = "ВКЛ" if frame.start_stop_buttons_enabled else "ВЫКЛ"
    rst_text = "ВКЛ" if frame.reset_button_enabled else "ЗАБЛОКИРОВАНА"
    err_text = COLUMN_ERROR_DESCRIPTIONS.get(
        frame.column_error_code, f"Код ошибки {frame.column_error_code}"
    )

    lines = [
        f"Колонка #{frame.address} (ответ на команду 0x{frame.command_code:02X})",
        f"  Состояние (Sost байт 20)   : {frame.state_code} — {state_ru}",
        f"  Электромагнитный клапан    : {valve_text} (байт 17 = 0x{frame.status_byte17:02X}, бит 7)",
        f"  Кнопки на колонке ПУСК/СТОП: {ss_text} (бит 6)",
        f"  Кнопка на колонке СБРОС    : {rst_text} (бит 5)",
        f"  Тип дозы (биты 0..4)       : {_decode_dose_type_ru(frame.dose_type_bits)}",
        f"  Байт 18 (доп. статус)      : 0x{frame.status_byte18:02X}",
        f"  Ошибка колонки (байт 19)   : {err_text} (Sost[19]=0x{frame.sost_byte19:02X})",
    ]
    if frame.is_mass_mode:
        density_text = (
            f"{frame.density_kg_per_l:.3f} кг/л"
            if frame.density_kg_per_l is not None
            else f"raw={frame.price_raw}"
        )
        lines.append(
            f"  Единицы измерения          : КГ (плотность={density_text}, "
            f"расчётный объём={frame.effective_volume_ml} мл)"
        )
    elif frame.state_code == STATE_IDLE:
        lines.append(
            f"  Поле Price (цена)          : {frame.price_kzt_per_liter:.2f} (raw={frame.price_raw})"
        )
    elif frame.preset_amount is not None:
        lines.append(
            f"  Поле Price (доза в деньгах): {frame.preset_amount:.2f} (raw={frame.price_raw})"
        )
    else:
        dose_val = int(frame.price_raw) / 100.0 if frame.price_raw.isdigit() else 0.0
        lines.append(
            f"  Поле Price (уставка/доза)  : {dose_val:.2f} (raw={frame.price_raw})"
        )
    lines.append(
        f"  Поле Volume (налито)       : {frame.volume_ml} мл ({frame.volume_ml / 1000.0:.3f} л, raw={frame.volume_raw})"
    )
    lines.append(f"  Кадр HEX                   : {frame.raw_hex}")

    if frame.is_locked_in_stop:
        lines.append(
            "  [СБРОС 0x37] Колонка находится в останове ('04'/'07'), а кнопка «СБРОС» на колонке "
            "отключена (бит 5 = 0). Без пульта управления возврат в '05' выполняется командой «Сброс» (0x37)."
        )
    if (
        frame.state_code == STATE_COMPLETED
        and frame.volume_ml == 0
        and frame.price_raw.isdigit()
        and int(frame.price_raw) > 0
    ):
        lines.append(
            "  [ДИАГНОСТИКА НАЛИВА] В состоянии '07' налито 0 мл при заданной дозе: "
            "возможен останов при снижении расхода < 4,5 л/мин (РЭ п. 15.5) либо 10-секундная отсечка по ДТФ "
            "(нет жидкой фазы / не включён насос через БУН / закрыт вентиль, РЭ лист 15 п. 5.3.4)."
        )
    return "\n".join(lines)


class Uzsg01PsuController:
    """Программный пульт управления УЗСГ-01 через АСКА-02 при питании от Блока питания."""

    def __init__(self, link: AskaLink, layout: FrameLayout | None = None) -> None:
        self.link = link
        self.layout = layout or FrameLayout()

    def _tx_checksum_mode(self) -> str:
        return self.layout.tx_checksum_mode

    def _send_and_parse(
        self,
        address: int,
        request: bytes,
        *,
        allow_empty: bool = False,
    ) -> IskraTelemetryFrame | None:
        res: PollRawResult = self.link.send_command(address, request)
        if res.error_message:
            raise PsuControlError(f"Ошибка COM-порта при работе с колонкой #{address}: {res.error_message}")
        if not res.has_response:
            if allow_empty:
                return None
            raise PsuControlError(
                f"Колонка #{address} не ответила (RX=0 байт) на команду 0x{request[3]:02X}. "
                "Проверьте питание АСКА-02, БП УЗСГ-01 и полярность пары в кабеле RJ-11."
            )
        try:
            frame = parse_iskra_frame(res.response_bytes, self.layout)
        except IskraFrameError as exc:
            raise PsuControlError(
                f"Некорректный кадр от колонки #{address} на команду 0x{request[3]:02X}: {exc}"
            ) from exc
        if frame.address != address:
            raise PsuControlError(
                f"Ответ пришёл от колонки #{frame.address}, ожидалась #{address}"
            )
        return frame

    def get_status(self, address: int) -> IskraTelemetryFrame:
        """Опрос состояния колонки командой «Тест» (0x34)."""
        req = build_test_command(address, checksum_mode=self._tx_checksum_mode())
        frame = self._send_and_parse(address, req, allow_empty=False)
        assert frame is not None
        return frame

    def reset_column(self, address: int, *, force: bool = False) -> ResetResult:
        """Отправляет команду «Сброс» (0x37, п. 4.4) для вывода колонки из блокировки '07'/'04' в '05'."""
        before = self.get_status(address)
        if not force and (before.valve_open or before.state_code == STATE_DISPENSING):
            raise PsuControlError(
                f"Колонка #{address} сейчас выполняет налив (состояние '03', клапан открыт). "
                "Сначала выполните «Останов» (0x36) или передайте force=True."
            )
        if not force and before.state_code == STATE_IDLE:
            return ResetResult(
                before=before,
                reply=None,
                after=before,
                reset_sent=False,
                unlocked=True,
                message=f"Колонка #{address} уже находится в состоянии '05' (Сброс / Готовность).",
            )

        req = build_reset_command(address, checksum_mode=self._tx_checksum_mode())
        reply = self._send_and_parse(address, req, allow_empty=False)
        after = self.get_status(address)
        unlocked = after.state_code == STATE_IDLE
        if unlocked:
            msg = (
                f"Колонка #{address} переведена из состояния '{before.state_code}' "
                f"в готовность '05' командой СБРОС (0x37)."
            )
        else:
            msg = (
                f"Команда СБРОС (0x37) отправлена, но колонка #{address} осталась "
                f"в состоянии '{after.state_code}' ({after.state_name})."
            )
        return ResetResult(
            before=before,
            reply=reply,
            after=after,
            reset_sent=True,
            unlocked=unlocked,
            message=msg,
        )

    def set_buttons_mode(self, address: int, mode: str) -> IskraTelemetryFrame:
        """Управляет кнопками на корпусе колонки УЗСГ-01 (п. 2.1–2.3 параметров, 0x38)."""
        code_map = {
            "enable": "0.16",      # Включить ПУСК, СТОП и СБРОС на ГРК
            "disable": "0.17",     # Выключить кнопки на ГРК
            "lock-reset": "0.18",  # Включить ПУСК/СТОП и заблокировать СБРОС
        }
        if mode not in code_map:
            raise ValueError(f"Неизвестный режим кнопок {mode!r}; допустимы: {', '.join(code_map)}")
        status = self.get_status(address)
        if status.state_code == STATE_DISPENSING or status.valve_open:
            raise PsuControlError(f"Нельзя менять режим кнопок во время налива на колонке #{address}.")
        if status.state_code != STATE_IDLE:
            reset_res = self.reset_column(address)
            if not reset_res.unlocked:
                raise PsuControlError(reset_res.message)
        req = build_param_command(
            address,
            code_map[mode],
            volume_digits=0,
            checksum_mode=self._tx_checksum_mode(),
        )
        # По таблицам 2.1–2.3 Протокола v3.10 колонка может не слать ответ на 0x38.
        self._send_and_parse(address, req, allow_empty=True)
        if mode == "enable":
            reset_req = build_reset_command(address, checksum_mode=self._tx_checksum_mode())
            self._send_and_parse(address, reset_req, allow_empty=True)
        return self.get_status(address)

    def preset_dose(
        self,
        address: int,
        liters: float | None = None,
        *,
        full_tank: bool = False,
    ) -> IskraTelemetryFrame:
        """Задаёт дозу налива (команда 0x39, п. 4.5). При блокировке в '07' сначала сбрасывает в '05'."""
        if full_tank:
            volume_ml = 999_000
        else:
            if liters is None or liters <= 0:
                raise ValueError("Укажите положительный объём в литрах или full_tank=True")
            volume_ml = int(round(liters * 1000))
            if volume_ml <= 0 or volume_ml > 999_999:
                raise ValueError(f"Доза в миллилитрах должна быть 1..999999, получено: {volume_ml}")
            if volume_ml < 5000:
                logger.warning(
                    "Колонка #%d: задана доза %d мл < 5000 мл (минимальная по РЭ УЗСГ-01 — 5 л)",
                    address,
                    volume_ml,
                )

        status = self.get_status(address)
        if status.state_code == STATE_DISPENSING or status.valve_open:
            raise PsuControlError(f"Колонка #{address} уже выполняет налив (состояние '03').")
        if status.state_code != STATE_IDLE:
            reset_res = self.reset_column(address)
            if not reset_res.unlocked:
                raise PsuControlError(
                    f"Не удалось перевести колонку #{address} в '05' перед заданием дозы: {reset_res.message}"
                )

        req = build_set_dose_command(address, volume_ml, checksum_mode=self._tx_checksum_mode())
        reply = self._send_and_parse(address, req, allow_empty=False)
        assert reply is not None
        if reply.state_code != STATE_DOSE_SET:
            status_after = self.get_status(address)
            if status_after.state_code != STATE_DOSE_SET:
                raise PsuControlError(
                    f"Колонка #{address} не перешла в состояние '01' (Задание дозы), "
                    f"текущее состояние: {status_after.state_code}."
                )
            return status_after
        return reply

    def start_pump(
        self,
        address: int,
        *,
        liters: float | None = None,
        full_tank: bool = False,
    ) -> IskraTelemetryFrame:
        """Запускает налив командой «Пуск» (0x35, п. 4.2)."""
        status = self.get_status(address)
        if liters is not None or full_tank:
            status = self.preset_dose(address, liters=liters, full_tank=full_tank)
        elif status.state_code == STATE_COMPLETED:
            reset_res = self.reset_column(address)
            if not reset_res.unlocked:
                raise PsuControlError(reset_res.message)
            status = self.preset_dose(address, full_tank=True)
        elif status.state_code == STATE_IDLE:
            status = self.preset_dose(address, full_tank=True)

        if status.state_code not in {STATE_DOSE_SET, STATE_STOPPED}:
            raise PsuControlError(
                f"Пуск колонки #{address} невозможен из состояния '{status.state_code}' ({status.state_name}). "
                "По п. 4.2 требуется состояние '01' (Задание дозы) или '04' (Останов)."
            )

        req = build_start_command(address, checksum_mode=self._tx_checksum_mode())
        reply = self._send_and_parse(address, req, allow_empty=False)
        assert reply is not None
        return reply

    def stop_pump(self, address: int, *, force: bool = False) -> IskraTelemetryFrame:
        """Останавливает налив командой «Останов» (0x36, п. 4.3)."""
        if not force:
            status = self.get_status(address)
            if status.state_code != STATE_DISPENSING and not status.valve_open:
                raise PsuControlError(
                    f"Останов колонки #{address} невозможен: она в состоянии '{status.state_code}' "
                    f"({status.state_name}), а не в состоянии '03' (Пуск)."
                )
        req = build_stop_command(address, checksum_mode=self._tx_checksum_mode())
        reply = self._send_and_parse(address, req, allow_empty=False)
        assert reply is not None
        return reply

    def _reset_to_idle_bits(
        self,
        address: int,
        *,
        status_ascii: str = "00",
        max_retries: int = 5,
        retry_delay_sec: float = 0.05,
    ) -> IskraTelemetryFrame | None:
        """Повторяет «Сброс» (0x37) по п. 1.1–1.6 Протокола v3.10, пока биты 0–4 байта 17 не станут 0x10."""
        mode = self._tx_checksum_mode()
        last_reply: IskraTelemetryFrame | None = None
        for attempt in range(max(1, max_retries)):
            req = build_reset_command(address, status_ascii=status_ascii, checksum_mode=mode)
            reply = self._send_and_parse(address, req, allow_empty=True)
            if reply is not None:
                last_reply = reply
                if reply.dose_type_bits == 0x10:
                    return reply
            if attempt + 1 < max_retries and retry_delay_sec > 0:
                time.sleep(retry_delay_sec)
        return last_reply

    def set_price(
        self,
        address: int,
        price_per_liter: float,
        *,
        max_retries: int = 5,
        retry_delay_sec: float = 0.1,
    ) -> IskraTelemetryFrame:
        """Устанавливает цену за литр командой 0x38 (код 0.15, п. 2.4 параметров Протокола v3.10)."""
        if price_per_liter <= 0:
            raise ValueError("Цена за литр должна быть больше 0")
        price_kop = int(round(price_per_liter * 100))
        if price_kop <= 0 or price_kop > 999_999:
            raise ValueError(f"Цена в копейках/тиынах вне диапазона 1..999999: {price_kop}")

        status = self.get_status(address)
        if status.state_code == STATE_DISPENSING or status.valve_open:
            raise PsuControlError(f"Нельзя менять цену во время налива на колонке #{address}.")
        if status.state_code != STATE_IDLE:
            reset_res = self.reset_column(address)
            if not reset_res.unlocked:
                raise PsuControlError(reset_res.message)

        mode = self._tx_checksum_mode()
        req_price = build_param_command(
            address,
            "0.15",
            volume_digits=price_kop,
            checksum_mode=mode,
        )
        # П. 2.4 шаг 1: ответ в таблице указан как «нет»
        self._send_and_parse(address, req_price, allow_empty=True)
        if retry_delay_sec > 0:
            time.sleep(retry_delay_sec)

        # П. 2.4 шаг 2: Тест, повторять пока (byte17 & 0x7F) != 0x16
        test_req = build_test_command(address, checksum_mode=mode)
        step2_ok = False
        for attempt in range(max(1, max_retries)):
            frame = self._send_and_parse(address, test_req, allow_empty=True)
            if frame is not None and (frame.status_byte17 & 0x7F) == 0x16:
                step2_ok = True
                break
            if attempt + 1 < max_retries and retry_delay_sec > 0:
                time.sleep(retry_delay_sec)
        if not step2_ok:
            self._send_and_parse(
                address,
                build_reset_command(address, checksum_mode=mode),
                allow_empty=True,
            )
            raise PsuControlError(
                f"Колонка #{address} не подтвердила режим установки цены (ожидалось 0x16 в байте 17 после 0.15)."
            )

        # П. 2.4 шаг 3: Останов (запись цены в память), повторять пока (byte17 & 0x7F) != 0x30
        stop_req = build_stop_command(address, checksum_mode=mode)
        step3_ok = False
        for attempt in range(max(1, max_retries)):
            reply = self._send_and_parse(address, stop_req, allow_empty=True)
            if reply is not None and (reply.status_byte17 & 0x7F) == 0x30:
                step3_ok = True
                break
            if attempt + 1 < max_retries and retry_delay_sec > 0:
                time.sleep(retry_delay_sec)
        if not step3_ok:
            self._send_and_parse(
                address,
                build_reset_command(address, checksum_mode=mode),
                allow_empty=True,
            )
            raise PsuControlError(
                f"Колонка #{address} не подтвердила запись цены командой Останов (ожидалось 0x30 в байте 17)."
            )

        final = self.get_status(address)
        if final.state_code != STATE_IDLE:
            self._reset_to_idle_bits(address)
            final = self.get_status(address)

        expected_price = price_kop / 100.0
        if (
            final.state_code == STATE_IDLE
            and final.price_kzt_per_liter > 0
            and abs(final.price_kzt_per_liter - expected_price) > 0.02
        ):
            raise PsuControlError(
                f"Цена на колонке #{address} после установки ({final.price_kzt_per_liter:.2f}) "
                f"не совпала с заданной ({expected_price:.2f})."
            )
        return final

    def read_total_counter_1(self, address: int, *, mass: bool = False) -> float | None:
        """Считывает суммарный счётчик 1 (0x38, код 0.11) с гарантированным возвратом в '05'."""
        status = self.get_status(address)
        if status.state_code == STATE_DISPENSING or status.valve_open:
            raise PsuControlError(f"Нельзя считывать счётчик во время налива на колонке #{address}.")
        if status.state_code != STATE_IDLE:
            reset_res = self.reset_column(address)
            if not reset_res.unlocked:
                raise PsuControlError(reset_res.message)

        mode = self._tx_checksum_mode()
        status_ascii = "01" if mass else "00"
        req = build_param_command(
            address,
            "0.11",
            volume_digits=0,
            status_ascii=status_ascii,
            checksum_mode=mode,
        )
        try:
            frame = self._send_and_parse(address, req, allow_empty=False)
        except PsuControlError:
            frame = None
        finally:
            self._reset_to_idle_bits(address, status_ascii=status_ascii)

        if frame is not None and frame.dose_type_bits == 0x1A:
            raw_s = frame.raw_bytes[7:17].decode("ascii", errors="replace")
            if raw_s.isdigit():
                return int(raw_s) / 100.0
        return None

    def read_counters(self, address: int, *, mass: bool = False) -> CountersReport:
        """Считывает суммарные, суточный счётчики и ТПР (0x38, разделы 1.1–1.5) со сбросом в '05'."""
        status = self.get_status(address)
        if status.state_code == STATE_DISPENSING or status.valve_open:
            raise PsuControlError(f"Нельзя считывать счётчики во время налива на колонке #{address}.")
        if status.state_code != STATE_IDLE:
            reset_res = self.reset_column(address)
            if not reset_res.unlocked:
                raise PsuControlError(reset_res.message)

        status_ascii = "01" if mass else "00"
        mode = self._tx_checksum_mode()

        def _query_and_reset(code: str, st: str) -> IskraTelemetryFrame | None:
            req = build_param_command(address, code, volume_digits=0, status_ascii=st, checksum_mode=mode)
            try:
                frame = self._send_and_parse(address, req, allow_empty=False)
            except PsuControlError:
                frame = None
            # По таблицам 1.1–1.5 после чтения параметров повторяем «Сброс», пока биты 0..4 != 0x10.
            self._reset_to_idle_bits(address, status_ascii=st)
            return frame

        # 1.1 Суммарный счётчик 1 (0.11, маркер 1Ah, байты 7..16)
        tot1_raw: str | None = None
        tot1_val: float | None = None
        f1 = _query_and_reset("0.11", status_ascii)
        if f1 is not None and f1.dose_type_bits == 0x1A:
            raw_s = f1.raw_bytes[7:17].decode("ascii", errors="replace")
            if raw_s.isdigit():
                tot1_raw = raw_s
                tot1_val = int(raw_s) / 100.0

        # 1.2 Суммарный счётчик 2 (0.19, маркер 1Bh, байты 7..16)
        tot2_raw: str | None = None
        tot2_val: float | None = None
        f2 = _query_and_reset("0.19", status_ascii)
        if f2 is not None and f2.dose_type_bits == 0x1B:
            raw_s2 = f2.raw_bytes[7:17].decode("ascii", errors="replace")
            if raw_s2.isdigit():
                tot2_raw = raw_s2
                tot2_val = int(raw_s2) / 100.0

        # 1.3 Суточный счётчик (0.12, маркер 18h, байты 9..16, байты 5..8 температура/плотность)
        daily_raw: str | None = None
        daily_val: float | None = None
        temp_c: float | None = None
        density: float | None = None
        f3 = _query_and_reset("0.12", status_ascii)
        if f3 is not None and f3.dose_type_bits == 0x18:
            raw_d = f3.raw_bytes[9:17].decode("ascii", errors="replace")
            if raw_d.isdigit():
                daily_raw = raw_d
                daily_val = int(raw_d) / 100.0
            extra = f3.raw_bytes[5:9]
            extra_s = extra.decode("ascii", errors="replace")
            if not mass:
                sign = -1.0 if extra[0] == 0x31 else 1.0
                digits_t = extra_s[1:].strip().replace(".", "")
                if digits_t.isdigit():
                    temp_c = sign * (int(digits_t) / 10.0)
            else:
                digits_p = extra_s.strip().replace(".", "")
                if digits_p.isdigit():
                    density = int(digits_p) / 1000.0

        # 1.5 Параметры ТПР (0.14, Status='00', маркер 19h, байты 11..12 пропан %, 13..16 / 1e6)
        propane_pct: int | None = None
        tpr_coef: float | None = None
        f4 = _query_and_reset("0.14", "00")
        if f4 is not None and f4.dose_type_bits == 0x19:
            prop_s = f4.raw_bytes[11:13].decode("ascii", errors="replace")
            tpr_s = f4.raw_bytes[13:17].decode("ascii", errors="replace")
            if prop_s.isdigit():
                propane_pct = int(prop_s)
            if tpr_s.isdigit():
                tpr_coef = int(tpr_s) / 1_000_000.0

        final_status = self.get_status(address)
        if final_status.state_code != STATE_IDLE:
            self._reset_to_idle_bits(address)
            final_status = self.get_status(address)

        return CountersReport(
            address=address,
            mass_mode=mass,
            total_counter_1_raw=tot1_raw,
            total_counter_1_value=tot1_val,
            total_counter_2_raw=tot2_raw,
            total_counter_2_value=tot2_val,
            daily_counter_raw=daily_raw,
            daily_counter_value=daily_val,
            temperature_c=temp_c,
            density_kg_m3=density,
            propane_percent=propane_pct,
            tpr_liters_per_pulse=tpr_coef,
            final_status=final_status,
        )
