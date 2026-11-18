"""Консольный монитор статистики по колонкам за смену (в том числе для /dev/tty1 без GUI).

Показывает на экране:
- текущую смену и статус выгрузки на VPS;
- сводку по каждой колонке (№ колонки, статус ТРК, время, цена, число наливов, объём, сумма);
- журнал последних наливов за смену (№ колонки, время, режим, объём, цена, сумма, статус VPS);
- строку «ИТОГО ЗА СМЕНУ».

Работает только на чтение локальной SQLite БД (`read_only=True`) и не требует входа под паролем администратора.
"""

from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from agzs_edge.config import EdgeSettings
from agzs_edge.psu_controller import STATE_DESCRIPTIONS_RU
from agzs_edge.storage import DispenseRow, EdgeDatabase, parse_iso_datetime

_SHORT_STATE_RU: dict[str, str] = {
    "01": "Доза задана",
    "02": "Остаток",
    "03": "Идёт налив",
    "04": "Останов",
    "05": "Готова",
    "06": "Авария",
    "07": "Стоп/Сброс",
    "NR": "Нет связи",
    "--": "Нет данных",
}


@dataclass(frozen=True)
class ShiftWindow:
    start: datetime
    end: datetime
    label: str


@dataclass(frozen=True)
class PumpShiftSummary:
    pump_address: int
    state_code: str
    state_name: str
    state_label_ru: str
    current_price: float
    live_volume_ml: int
    last_time_str: str
    dispense_count: int
    total_volume_liters: float
    total_amount: float


@dataclass(frozen=True)
class ShiftDispenseEntry:
    id: int
    pump_address: int
    time_str: str
    mode_label: str
    volume_liters: float
    price_per_liter: float
    amount: float
    synced_to_vps: bool


@dataclass(frozen=True)
class ShiftDashboardSnapshot:
    station_code: str
    generated_at: datetime
    shift: ShiftWindow
    currency_symbol: str
    pumps: list[PumpShiftSummary]
    recent_dispenses: list[ShiftDispenseEntry]
    total_dispenses: int
    total_volume_liters: float
    total_amount: float
    outbox_pending: int
    outbox_sent: int


def _local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo or timezone.utc


def resolve_shift_window(
    now: datetime | None = None,
    *,
    shift_start_hour: int = 8,
    shift_hours: int = 12,
) -> ShiftWindow:
    """Вычисляет границы текущей смены [start, end) и её название."""
    if shift_start_hour < 0 or shift_start_hour > 23:
        raise ValueError("shift_start_hour должен быть в диапазоне 0..23")
    if shift_hours < 1 or shift_hours > 24:
        raise ValueError("shift_hours должен быть в диапазоне 1..24")

    if now is None:
        local_now = datetime.now().astimezone()
    elif now.tzinfo is None:
        local_now = now.replace(tzinfo=_local_tz())
    else:
        local_now = now

    today_anchor = local_now.replace(hour=shift_start_hour, minute=0, second=0, microsecond=0)
    anchor = today_anchor - timedelta(days=1) if local_now < today_anchor else today_anchor
    elapsed_hours = int((local_now - anchor).total_seconds() // 3600)
    slot_idx = elapsed_hours // shift_hours
    start = anchor + timedelta(hours=slot_idx * shift_hours)
    end = start + timedelta(hours=shift_hours)

    if shift_hours == 24:
        label = "Суточная смена"
    elif 6 <= start.hour < 18:
        label = "Дневная смена"
    else:
        label = "Ночная смена"

    return ShiftWindow(start=start, end=end, label=label)


def _format_local_time(raw: str, tz: tzinfo | None = None) -> str:
    parsed = parse_iso_datetime(raw)
    if parsed is None:
        return "—"
    target_tz = tz or _local_tz()
    return parsed.astimezone(target_tz).strftime("%H:%M:%S")


def _state_label(state_code: str, state_name: str) -> str:
    if state_code in _SHORT_STATE_RU:
        return _SHORT_STATE_RU[state_code]
    if state_code in STATE_DESCRIPTIONS_RU:
        return STATE_DESCRIPTIONS_RU[state_code]
    return state_name or "—"


def _mode_label(mode: str) -> str:
    if mode == "dose":
        return "Доза"
    if mode == "full_tank":
        return "Полный"
    return mode or "—"


def _format_money(value: float, currency: str, width: int = 12) -> str:
    formatted = f"{value:,.2f}".replace(",", " ")
    full = f"{formatted} {currency}" if currency else formatted
    if len(full) <= width:
        return full
    compact = f"{value:.2f} {currency}" if currency else f"{value:.2f}"
    if len(compact) <= width:
        return compact
    no_cur = f"{value:,.2f}".replace(",", " ")
    if len(no_cur) <= width:
        return no_cur
    rounded = f"{value:,.0f}".replace(",", " ")
    return f"{rounded} {currency}" if currency else rounded


def _format_price(value: float, currency: str, width: int = 8) -> str:
    if value <= 0:
        return "—"
    full = f"{value:.2f} {currency}" if currency else f"{value:.2f}"
    if len(full) <= width:
        return full
    return f"{value:.2f}"


def build_shift_snapshot(
    db: EdgeDatabase,
    settings: EdgeSettings,
    *,
    now: datetime | None = None,
    recent_limit: int = 12,
) -> ShiftDashboardSnapshot:
    """Собирает срез статистики по колонкам и заправкам за текущую смену."""
    if now is None:
        local_now = datetime.now().astimezone()
    elif now.tzinfo is None:
        local_now = now.replace(tzinfo=_local_tz())
    else:
        local_now = now

    tz = local_now.tzinfo
    shift = resolve_shift_window(
        local_now,
        shift_start_hour=settings.shift_start_hour,
        shift_hours=settings.shift_hours,
    )
    summary = db.summary()
    dispenses: list[DispenseRow] = db.list_dispenses_between(shift.start, shift.end)

    raw_pumps = summary.get("pumps") or []
    live_by_addr: dict[int, dict[str, object]] = {}
    if isinstance(raw_pumps, list):
        for item in raw_pumps:
            if isinstance(item, dict) and "pump_address" in item:
                live_by_addr[int(item["pump_address"])] = item

    addresses = sorted(
        set(settings.pump_addresses)
        | set(live_by_addr.keys())
        | {d.pump_address for d in dispenses}
    )

    dispenses_by_addr: dict[int, list[tuple[DispenseRow, float, float]]] = {addr: [] for addr in addresses}
    recent_entries: list[ShiftDispenseEntry] = []
    total_volume_liters = 0.0
    total_amount = 0.0

    for d in dispenses:
        live = live_by_addr.get(d.pump_address, {})
        fallback_price = float(live.get("price_kzt_per_liter", 0.0) or 0.0)
        eff_price = d.price_kzt_per_liter if d.price_kzt_per_liter > 0 else fallback_price
        amount = round(d.volume_liters * eff_price, 2)

        dispenses_by_addr.setdefault(d.pump_address, []).append((d, eff_price, amount))
        total_volume_liters += d.volume_liters
        total_amount += amount

        if len(recent_entries) < max(0, recent_limit):
            recent_entries.append(
                ShiftDispenseEntry(
                    id=d.id,
                    pump_address=d.pump_address,
                    time_str=_format_local_time(d.finished_at, tz),
                    mode_label=_mode_label(d.mode),
                    volume_liters=d.volume_liters,
                    price_per_liter=eff_price,
                    amount=amount,
                    synced_to_vps=d.synced_to_vps,
                )
            )

    pump_summaries: list[PumpShiftSummary] = []
    for addr in addresses:
        live = live_by_addr.get(addr, {})
        state_code = str(live.get("state_code", "--"))
        state_name = str(live.get("state_name", "NO_DATA"))
        current_price = float(live.get("price_kzt_per_liter", 0.0) or 0.0)
        live_volume_ml = int(live.get("volume_ml", 0) or 0)

        addr_rows = dispenses_by_addr.get(addr, [])
        if addr_rows:
            last_time_str = _format_local_time(addr_rows[0][0].finished_at, tz)
        elif live.get("updated_at"):
            last_time_str = _format_local_time(str(live["updated_at"]), tz)
        else:
            last_time_str = "—"

        pump_summaries.append(
            PumpShiftSummary(
                pump_address=addr,
                state_code=state_code,
                state_name=state_name,
                state_label_ru=_state_label(state_code, state_name),
                current_price=current_price,
                live_volume_ml=live_volume_ml,
                last_time_str=last_time_str,
                dispense_count=len(addr_rows),
                total_volume_liters=round(sum(row[0].volume_liters for row in addr_rows), 3),
                total_amount=round(sum(row[2] for row in addr_rows), 2),
            )
        )

    return ShiftDashboardSnapshot(
        station_code=settings.station_code,
        generated_at=local_now,
        shift=shift,
        currency_symbol=settings.currency_symbol,
        pumps=pump_summaries,
        recent_dispenses=recent_entries,
        total_dispenses=len(dispenses),
        total_volume_liters=round(total_volume_liters, 3),
        total_amount=round(total_amount, 2),
        outbox_pending=int(summary.get("outbox_pending", 0) or 0),
        outbox_sent=int(summary.get("outbox_sent", 0) or 0),
    )


def _clip(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _format_row(cells: list[tuple[str, int, str]]) -> str:
    parts: list[str] = []
    for text, width, align in cells:
        clipped = _clip(text, width)
        if align == "right":
            parts.append(clipped.rjust(width))
        elif align == "center":
            parts.append(clipped.center(width))
        else:
            parts.append(clipped.ljust(width))
    return "│ " + " │ ".join(parts) + " │"


def _border(widths: list[int], left: str, mid: str, right: str) -> str:
    return left + mid.join("─" * (w + 2) for w in widths) + right


def render_shift_dashboard(snapshot: ShiftDashboardSnapshot, *, kiosk: bool = False) -> str:
    """Форматирует табло статистики колонок и журнала наливов (ширина 80 символов)."""
    cur = snapshot.currency_symbol
    shift_start = snapshot.shift.start.strftime("%d.%m %H:%M")
    shift_end = snapshot.shift.end.strftime("%d.%m %H:%M")
    now_str = snapshot.generated_at.strftime("%d.%m.%Y %H:%M:%S")

    lines: list[str] = [
        f" АГЗС {snapshot.station_code} — МОНИТОР КОЛОНОК".ljust(58) + now_str.rjust(22),
        f" {snapshot.shift.label}: {shift_start} – {shift_end} | "
        f"VPS: отпр. {snapshot.outbox_sent}, очер. {snapshot.outbox_pending}",
        "",
        " [1] СТАТИСТИКА ПО КОЛОНКАМ ЗА СМЕНУ",
    ]

    # Сумма ширин: 6 + 11 + 8 + 8 + 4 + 9 + 12 = 58 + 22 обрамление = ровно 80 символов
    p_widths = [6, 11, 8, 8, 4, 9, 12]
    lines.append(_border(p_widths, "┌", "┬", "┐"))
    lines.append(
        _format_row(
            [
                ("№ Кол.", 6, "center"),
                ("Статус ТРК", 11, "left"),
                ("Время", 8, "center"),
                ("Цена", 8, "right"),
                ("Нал.", 4, "right"),
                ("Объём, л", 9, "right"),
                ("Сумма", 12, "right"),
            ]
        )
    )
    lines.append(_border(p_widths, "├", "┼", "┤"))

    if not snapshot.pumps:
        lines.append(_format_row([("Нет настроенных колонок", 76, "center")]))
    else:
        for p in snapshot.pumps:
            lines.append(
                _format_row(
                    [
                        (f"#{p.pump_address}", 6, "center"),
                        (p.state_label_ru, 11, "left"),
                        (p.last_time_str, 8, "center"),
                        (_format_price(p.current_price, cur), 8, "right"),
                        (str(p.dispense_count), 4, "right"),
                        (f"{p.total_volume_liters:.2f}", 9, "right"),
                        (_format_money(p.total_amount, cur), 12, "right"),
                    ]
                )
            )

    p_total_widths = [42, 4, 9, 12]
    lines.append("├" + "─" * 44 + "┼" + "─" * 6 + "┼" + "─" * 11 + "┼" + "─" * 14 + "┤")
    lines.append(
        _format_row(
            [
                ("ИТОГО ЗА СМЕНУ", 42, "left"),
                (str(snapshot.total_dispenses), 4, "right"),
                (f"{snapshot.total_volume_liters:.2f}", 9, "right"),
                (_format_money(snapshot.total_amount, cur), 12, "right"),
            ]
        )
    )
    lines.append(_border(p_total_widths, "└", "┴", "┘"))

    lines.append("")
    lines.append(" [2] ПОСЛЕДНИЕ НАЛИВЫ ЗА СМЕНУ")

    # Сумма ширин: 6 + 8 + 9 + 9 + 8 + 12 + 3 = 55 + 22 обрамление + 3 = 80 символов
    d_widths = [6, 8, 9, 9, 8, 12, 3]
    lines.append(_border(d_widths, "┌", "┬", "┐"))
    lines.append(
        _format_row(
            [
                ("№ Кол.", 6, "center"),
                ("Время", 8, "center"),
                ("Режим", 9, "left"),
                ("Объём, л", 9, "right"),
                ("Цена", 8, "right"),
                ("Сумма", 12, "right"),
                ("VPS", 3, "center"),
            ]
        )
    )
    lines.append(_border(d_widths, "├", "┼", "┤"))

    if not snapshot.recent_dispenses:
        lines.append(_format_row([("В текущей смене закрытых наливов ещё нет", 76, "center")]))
    else:
        for entry in snapshot.recent_dispenses:
            lines.append(
                _format_row(
                    [
                        (f"#{entry.pump_address}", 6, "center"),
                        (entry.time_str, 8, "center"),
                        (entry.mode_label, 9, "left"),
                        (f"{entry.volume_liters:.2f}", 9, "right"),
                        (_format_price(entry.price_per_liter, cur), 8, "right"),
                        (_format_money(entry.amount, cur), 12, "right"),
                        ("OK" if entry.synced_to_vps else "…", 3, "center"),
                    ]
                )
            )

    d_total_widths = [29, 9, 8, 12, 3]
    lines.append("├" + "─" * 31 + "┼" + "─" * 11 + "┼" + "─" * 10 + "┼" + "─" * 14 + "┼" + "─" * 5 + "┤")
    lines.append(
        _format_row(
            [
                (f"ИТОГО ЗА СМЕНУ ({snapshot.total_dispenses} нал.)", 29, "left"),
                (f"{snapshot.total_volume_liters:.2f}", 9, "right"),
                ("—", 8, "center"),
                (_format_money(snapshot.total_amount, cur), 12, "right"),
                ("—", 3, "center"),
            ]
        )
    )
    lines.append(_border(d_total_widths, "└", "┴", "┘"))

    if kiosk:
        lines.append(" [Режим киоска tty1: вход без пароля, только просмотр]")
    else:
        lines.append(" [Монитор смены (только чтение) | Ctrl+C для выхода]")
    return "\n".join(lines)


def install_kiosk_signal_handlers() -> None:
    """Блокирует сигналы прерывания с клавиатуры (Ctrl+C, Ctrl+Z, Ctrl+\\) в режиме киоска."""
    for sig_name in ("SIGINT", "SIGQUIT", "SIGTSTP"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (OSError, ValueError):
                pass


def run_monitor_loop(
    settings: EdgeSettings,
    *,
    once: bool = False,
    refresh_sec: float | None = None,
    recent_limit: int = 12,
    kiosk: bool = False,
) -> int:
    """Запускает однократный вывод или цикл обновления табло статистики на экране."""
    db = EdgeDatabase(settings.db_path, read_only=True)
    effective_kiosk = kiosk or settings.monitor_kiosk

    if once:
        snapshot = build_shift_snapshot(db, settings, recent_limit=recent_limit)
        print(render_shift_dashboard(snapshot, kiosk=effective_kiosk))
        return 0

    if effective_kiosk:
        install_kiosk_signal_handlers()

    interval = refresh_sec if refresh_sec is not None else settings.monitor_refresh_sec
    if interval <= 0:
        interval = 2.0

    # Скрываем курсор на время работы живого табло, чтобы экран не мерцал
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    try:
        while True:
            snapshot = build_shift_snapshot(db, settings, recent_limit=recent_limit)
            frame = render_shift_dashboard(snapshot, kiosk=effective_kiosk)
            sys.stdout.write("\033[H\033[J" + frame + "\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
