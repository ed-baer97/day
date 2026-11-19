"""CLI-интерфейс станционного узла АГЗС (Компьютер — АСКА-02 — Блок питания — УЗСГ-01).

Доступные команды:
  python -m agzs_edge diagnose   -- USB/FTDI/протокол/TX-RX (только чтение «Тест»)
  python -m agzs_edge probe      -- разовый опрос адресов 1..8 командой «Тест»
  python -m agzs_edge listen     -- живой мониторинг 23-байтных кадров в консоли
  python -m agzs_edge watch-fill -- один налив выбранного адреса, без записи в базу
  python -m agzs_edge serve      -- боевой демон учёта (с --auto-reset для БП без ПУ)
  python -m agzs_edge unlock     -- снять блокировку колонки ('07'/'04' -> '05') командой 0x37
  python -m agzs_edge buttons    -- включить/выключить кнопки на колонке (0.16/0.17/0.18)
  python -m agzs_edge set-dose   -- задать дозу (0x39)
  python -m agzs_edge start      -- запуск заправки (0x35)
  python -m agzs_edge stop       -- останов заправки (0x36)
  python -m agzs_edge set-price  -- установка цены (0.15)
  python -m agzs_edge counters   -- чтение счётчиков и ТПР (0.11, 0.12, 0.14)
  python -m agzs_edge console    -- интерактивный пульт оператора на ПК
  python -m agzs_edge status     -- сводка по локальной БД и очереди отправки на VPS
  python -m agzs_edge monitor    -- табло статистики по колонкам за смену (в т.ч. для tty1)
  python -m agzs_edge flush      -- принудительная отправка накопленной очереди outbox на VPS
  python -m agzs_edge update     -- Pull-проверка и безопасное обновление станции с VPS
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

from agzs_edge.config import EdgeSettings, FrameLayout, MAX_PUMP_ADDRESS, MIN_PUMP_ADDRESS
from agzs_edge.iskra import IskraFrameError, parse_iskra_frame
from agzs_edge.psu_controller import (
    PsuControlError,
    Uzsg01PsuController,
    format_detailed_status,
)
from agzs_edge.serial_link import AskaLink, EmulatorAskaLink, SerialAskaLink, list_available_serial_ports
from agzs_edge.service import StationEdgeService
from agzs_edge.storage import EdgeDatabase
from agzs_edge.sync import OutboxSyncWorker


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _describe_fields(frame) -> str:
    if frame.completed_volume_ml is not None:
        return f"итог налива={frame.completed_volume_ml} мл ({frame.price_raw}), цены в кадре нет"
    return f"цена={frame.price_kzt_per_liter:.2f} ₸/л ({frame.price_raw}), объём={frame.volume_ml} мл"


def _build_diagnostic_link(
    args: argparse.Namespace,
    settings: EdgeSettings,
    *,
    layout: FrameLayout,
) -> tuple[AskaLink, str, int, float]:
    port = args.port or settings.serial_port
    baudrate = args.baudrate if getattr(args, "baudrate", None) is not None else settings.serial_baudrate
    cli_timeout = getattr(args, "timeout", None)
    timeout_sec = cli_timeout if cli_timeout is not None else settings.serial_timeout_sec
    min_wait_sec = cli_timeout if cli_timeout is not None else 1.0
    effective_wait = max(timeout_sec, min_wait_sec)
    if getattr(args, "emulator", False) or settings.source_mode == "emulator":
        link: AskaLink = EmulatorAskaLink(layout=layout)
    else:
        link = SerialAskaLink(
            port=port,
            baudrate=baudrate,
            timeout_sec=timeout_sec,
            layout=layout,
            min_wait_sec=min_wait_sec,
        )
    return link, port, baudrate, effective_wait


def _cmd_probe(args: argparse.Namespace, settings: EdgeSettings) -> int:
    addresses = tuple(range(MIN_PUMP_ADDRESS, MAX_PUMP_ADDRESS + 1)) if args.all_addresses else settings.pump_addresses
    checksum_arg = getattr(args, "checksum", None)
    if checksum_arg == "all":
        tx_modes: tuple[str, ...] = ("xor", "sum7", "sum8")
        parse_layout = replace(settings.layout, checksum_mode="any")
    else:
        mode = checksum_arg or settings.layout.checksum_mode
        tx_modes = (mode,)
        parse_layout = replace(settings.layout, checksum_mode=mode)

    link, port, baudrate, effective_wait = _build_diagnostic_link(args, settings, layout=parse_layout)

    print("=== Диагностика COM-портов системы ===")
    ports = list_available_serial_ports()
    if not ports:
        print("  Доступные COM-порты не обнаружены (или pyserial не видит устройств).")
    else:
        for dev, desc, hwid in ports:
            marker = " <-- выбран" if dev.upper() == port.upper() else ""
            print(f"  {dev}: {desc} [{hwid}]{marker}")

    modes_label = ",".join(tx_modes)
    print(
        f"\n=== Разовый опрос АСКА-02 ({port}, {baudrate} 8N1, timeout={effective_wait:.2f}с, "
        f"BCC={modes_label}, команда «Тест» код 4) ==="
    )

    any_reply = False
    try:
        for addr in addresses:
            for tx_mode in tx_modes:
                res = link.poll_test(addr, checksum_mode=tx_mode)
                req_hex = res.request_bytes.hex(" ").upper()
                tag = f"Адрес {addr}, {tx_mode}" if len(tx_modes) > 1 else f"Адрес {addr}"
                if res.error_message:
                    print(f"  [{tag}] TX: {req_hex} -> ОШИБКА ПОРТА: {res.error_message}")
                    continue
                if not res.has_response:
                    print(f"  [{tag}] TX: {req_hex} -> НЕТ ОТВЕТА (0 байт)")
                    continue

                any_reply = True
                resp_hex = res.response_bytes.hex(" ").upper()
                try:
                    frame = parse_iskra_frame(res.response_bytes, parse_layout)
                    print(
                        f"  [{tag}] TX: {req_hex} -> RX ({len(res.response_bytes)} Б): {resp_hex}\n"
                        f"             ОК: адрес={frame.address}, сост={frame.state_code}({frame.state_name}), "
                        f"ошибка={frame.error_code}, {_describe_fields(frame)}, BCC=0x{frame.checksum_byte:02X}"
                    )
                except IskraFrameError as exc:
                    print(
                        f"  [{tag}] TX: {req_hex} -> RX ({len(res.response_bytes)} Б): {resp_hex}\n"
                        f"             ВНИМАНИЕ (нестандартный кадр): {exc}"
                    )
    finally:
        link.close()

    if not any_reply and not args.emulator:
        print(
            "\nПодсказка по подключению УЗГС-01 к АСКА-02:\n"
            "  1. Красная лампа «Сеть» на АСКА-02 должна гореть (своё питание 220В).\n"
            "  2. Первая зелёная «Обмен» мигает при отправке команды «Тест» с ПК.\n"
            "  3. Если вторая зелёная молчит — проверьте пару с клеммы «К АСКА 01» на двух средних контактах RJ-11\n"
            "     и поменяйте эти две жилы местами один раз."
        )
        return 1
    return 0


def _cmd_listen(args: argparse.Namespace, settings: EdgeSettings) -> int:
    addr = args.addr
    checksum_arg = getattr(args, "checksum", None)
    layout = replace(settings.layout, checksum_mode=checksum_arg) if checksum_arg else settings.layout
    link, port, baudrate, effective_wait = _build_diagnostic_link(args, settings, layout=layout)
    print(
        f"Мониторинг адреса {addr} через {port} "
        f"({baudrate} 8N1, timeout={effective_wait:.2f}с, BCC={layout.checksum_mode}, Ctrl+C для выхода)..."
    )
    step = 0
    try:
        if addr < MIN_PUMP_ADDRESS or addr > MAX_PUMP_ADDRESS:
            raise ValueError(f"Адрес колонки должен быть в диапазоне {MIN_PUMP_ADDRESS}..{MAX_PUMP_ADDRESS}, получено: {addr}")
        while args.count is None or step < args.count:
            step += 1
            res = link.poll_test(addr)
            if not res.has_response:
                print(f"[{step:04d}] Нет ответа ({res.error_message or 'таймаут'})")
            else:
                try:
                    frame = parse_iskra_frame(res.response_bytes, layout)
                    print(
                        f"[{step:04d}] RX: {frame.raw_hex} | сост={frame.state_code}({frame.state_name}) "
                        f"ош={frame.error_code} {_describe_fields(frame)}"
                    )
                except IskraFrameError as exc:
                    print(f"[{step:04d}] RX RAW ({len(res.response_bytes)}B): {res.response_bytes.hex(' ').upper()} | {exc}")
            if args.count is None or step < args.count:
                time.sleep(settings.poll_interval_sec)
    except ValueError as exc:
        print(f"Ошибка параметра: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
    return 0


def _cmd_watch_fill(args: argparse.Namespace, settings: EdgeSettings) -> int:
    from agzs_edge.fill_watch import watch_fill

    addr = args.addr
    checksum_arg = getattr(args, "checksum", None)
    layout = replace(settings.layout, checksum_mode=checksum_arg) if checksum_arg else settings.layout
    link, _port, _baudrate, _effective_wait = _build_diagnostic_link(args, settings, layout=layout)
    if addr < MIN_PUMP_ADDRESS or addr > MAX_PUMP_ADDRESS:
        link.close()
        print(
            f"Ошибка параметра: адрес колонки должен быть в диапазоне {MIN_PUMP_ADDRESS}..{MAX_PUMP_ADDRESS}, получено: {addr}",
            file=sys.stderr,
        )
        return 2
    print(
        f"Наблюдение налива, адрес {addr}. Команда только «Тест». "
        f"База и VPS не изменяются. Остановите службу station-edge, иначе порт занят. Остановка по сигналу печатает итог."
    )

    def _show(sample) -> None:
        print(
            f"{sample.observed_at.strftime('%H:%M:%S')} "
            f"{sample.state_code}/{sample.state_name} {sample.volume_ml} мл "
            f"цена {sample.price_kzt_per_liter:.2f} err={sample.error_code}",
            flush=True,
        )

    try:
        report = watch_fill(
            link,
            addr,
            layout=layout,
            max_seconds=args.seconds,
            idle_seconds=args.idle,
            on_sample=_show,
        )
    except ValueError as exc:
        print(f"Ошибка параметра: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ОШИБКА ПОРТА: {exc}")
        return 1
    except KeyboardInterrupt:
        print("Прервано.")
        return 1
    print("")
    print(report.render())
    return 0


def _cmd_serve(args: argparse.Namespace, settings: EdgeSettings) -> int:
    if args.port:
        settings.serial_port = args.port
    if args.emulator:
        settings.source_mode = "emulator"
    if args.no_sync:
        settings.sync_enabled = False
    if getattr(args, "auto_reset", False):
        settings.auto_reset_on_stop = True
        settings.read_only = False
    service = StationEdgeService(settings)
    service.serve(max_cycles=args.cycles)
    return 0


def _build_psu_controller(
    args: argparse.Namespace,
    settings: EdgeSettings,
    *,
    initial_locked: bool = False,
) -> tuple[AskaLink, Uzsg01PsuController]:
    if getattr(args, "emulator", False) or settings.source_mode == "emulator":
        link: AskaLink = EmulatorAskaLink(layout=settings.layout, initial_locked=initial_locked)
    else:
        link, _port, _baud, _wait = _build_diagnostic_link(args, settings, layout=settings.layout)
    return link, Uzsg01PsuController(link, layout=settings.layout)


def _run_psu_action(
    args: argparse.Namespace,
    settings: EdgeSettings,
    action,
    *,
    initial_locked: bool = False,
) -> int:
    link, ctrl = _build_psu_controller(args, settings, initial_locked=initial_locked)
    try:
        return action(ctrl)
    except (PsuControlError, ValueError) as exc:
        print(f"Ошибка управления УЗСГ-01: {exc}", file=sys.stderr)
        return 1
    finally:
        link.close()


def _cmd_unlock(args: argparse.Namespace, settings: EdgeSettings) -> int:
    def _act(ctrl: Uzsg01PsuController) -> int:
        res = ctrl.reset_column(args.addr, force=args.force)
        print(res.message)
        print("\n--- Состояние ДО ---")
        print(format_detailed_status(res.before))
        if res.reset_sent:
            print("\n--- Состояние ПОСЛЕ ---")
            print(format_detailed_status(res.after))
        return 0 if res.unlocked else 1

    return _run_psu_action(args, settings, _act, initial_locked=True)


def _cmd_buttons(args: argparse.Namespace, settings: EdgeSettings) -> int:
    def _act(ctrl: Uzsg01PsuController) -> int:
        frame = ctrl.set_buttons_mode(args.addr, args.mode)
        print(f"Режим кнопок колонки #{args.addr} установлен: {args.mode}")
        print(format_detailed_status(frame))
        return 0

    return _run_psu_action(args, settings, _act)


def _cmd_set_dose(args: argparse.Namespace, settings: EdgeSettings) -> int:
    if not args.full_tank and args.liters is None:
        print("Укажите --liters <объём> или --full-tank", file=sys.stderr)
        return 2

    def _act(ctrl: Uzsg01PsuController) -> int:
        frame = ctrl.preset_dose(args.addr, liters=args.liters, full_tank=args.full_tank)
        label = "до полного (999 л)" if args.full_tank else f"{args.liters:g} л"
        print(f"Доза на колонке #{args.addr} задана: {label}")
        print(format_detailed_status(frame))
        return 0

    return _run_psu_action(args, settings, _act)


def _cmd_start(args: argparse.Namespace, settings: EdgeSettings) -> int:
    def _act(ctrl: Uzsg01PsuController) -> int:
        frame = ctrl.start_pump(args.addr, liters=args.liters, full_tank=args.full_tank)
        print(f"Отправлена команда ПУСК (0x35) на колонку #{args.addr}")
        print(format_detailed_status(frame))
        return 0

    return _run_psu_action(args, settings, _act)


def _cmd_stop(args: argparse.Namespace, settings: EdgeSettings) -> int:
    def _act(ctrl: Uzsg01PsuController) -> int:
        frame = ctrl.stop_pump(args.addr, force=args.force)
        print(f"Отправлена команда ОСТАНОВ (0x36) на колонку #{args.addr}")
        print(format_detailed_status(frame))
        return 0

    return _run_psu_action(args, settings, _act)


def _cmd_set_price(args: argparse.Namespace, settings: EdgeSettings) -> int:
    def _act(ctrl: Uzsg01PsuController) -> int:
        frame = ctrl.set_price(args.addr, args.price)
        print(f"Цена на колонке #{args.addr} установлена: {args.price:.2f}")
        print(format_detailed_status(frame))
        return 0

    return _run_psu_action(args, settings, _act)


def _cmd_counters(args: argparse.Namespace, settings: EdgeSettings) -> int:
    def _act(ctrl: Uzsg01PsuController) -> int:
        report = ctrl.read_counters(args.addr, mass=args.mass)
        print(report.render())
        return 0

    return _run_psu_action(args, settings, _act)


def _cmd_console(args: argparse.Namespace, settings: EdgeSettings) -> int:
    def _act(ctrl: Uzsg01PsuController) -> int:
        addr = args.addr
        print(
            f"=== Программный пульт УЗСГ-01 (АСКА-02 + БП, адрес {addr}) ===\n"
            "Команды:\n"
            "  Enter / t  — опрос состояния (Тест 0x34)\n"
            "  r          — СБРОС / разблокировка колонки (0x37)\n"
            "  d <л>      — задать дозу в литрах (0x39), например: d 20\n"
            "  df         — задать дозу «до полного» 999 л (0x39)\n"
            "  s          — ПУСК (0x35)\n"
            "  x          — СТОП (0x36)\n"
            "  b on|off|lock — кнопки колонки (0.16 / 0.17 / 0.18)\n"
            "  p <цена>   — установить цену за литр (0.15), например: p 72.00\n"
            "  c          — прочитать счётчики и ТПР (0x38)\n"
            "  q          — выход\n"
        )
        try:
            print(format_detailed_status(ctrl.get_status(addr)))
        except PsuControlError as exc:
            print(f"[Предупреждение при начальном опросе]: {exc}")

        while True:
            try:
                raw = input(f"\nУЗСГ#{addr}> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nВыход из пульта.")
                break
            if not raw or raw.lower() == "t":
                try:
                    print(format_detailed_status(ctrl.get_status(addr)))
                except PsuControlError as exc:
                    print(f"Ошибка: {exc}")
                continue

            parts = raw.split()
            cmd = parts[0].lower()
            try:
                if cmd in {"q", "quit", "exit"}:
                    break
                if cmd == "r":
                    res = ctrl.reset_column(addr)
                    print(res.message)
                    print(format_detailed_status(res.after))
                elif cmd == "df":
                    print(format_detailed_status(ctrl.preset_dose(addr, full_tank=True)))
                elif cmd == "d" and len(parts) == 2:
                    print(format_detailed_status(ctrl.preset_dose(addr, liters=float(parts[1]))))
                elif cmd == "s":
                    print(format_detailed_status(ctrl.start_pump(addr)))
                elif cmd == "x":
                    print(format_detailed_status(ctrl.stop_pump(addr)))
                elif cmd == "b" and len(parts) == 2:
                    mode_map = {"on": "enable", "off": "disable", "lock": "lock-reset"}
                    mode = mode_map.get(parts[1].lower(), parts[1].lower())
                    print(format_detailed_status(ctrl.set_buttons_mode(addr, mode)))
                elif cmd == "p" and len(parts) == 2:
                    print(format_detailed_status(ctrl.set_price(addr, float(parts[1]))))
                elif cmd == "c":
                    print(ctrl.read_counters(addr).render())
                else:
                    print("Неизвестная команда. Введите t, r, d <л>, df, s, x, b on|off|lock, p <цена>, c или q.")
            except (PsuControlError, ValueError) as exc:
                print(f"Ошибка: {exc}")
        return 0

    return _run_psu_action(args, settings, _act)


def _cmd_status(args: argparse.Namespace, settings: EdgeSettings) -> int:
    db = EdgeDatabase(settings.db_path)
    info = db.summary()
    recent = db.list_dispenses(limit=args.limit)
    print("=== Сводка локальной базы станции ===")
    print(f"  Файл БД           : {settings.db_path.resolve()}")
    print(f"  Закрытых заправок : {info['total_dispenses']}")
    print(f"  Суммарный уход    : {info['total_dispensed_ml']} мл ({info['total_liters']} л)")
    print(f"  Отправлено на VPS : {info['outbox_sent']}")
    print(f"  В очереди на VPS  : {info['outbox_pending']}")

    pumps = info.get("pumps") or []
    if isinstance(pumps, list) and pumps:
        print("\n=== Текущее состояние колонок ===")
        for p in pumps:
            print(
                f"  Колонка #{p['pump_address']}: сост={p['state_code']}({p['state_name']}), "
                f"ош={p['error_code']}, цена={p['price_kzt_per_liter']} ₸/л, "
                f"поле объёма={p['volume_ml']} мл (обновлено {p['updated_at']})"
            )

    if recent:
        print(f"\n=== Последние заправки (до {args.limit}) ===")
        for r in recent:
            sync_tag = "SENT" if r.synced_to_vps else "PENDING"
            print(
                f"  #{r.id} [{sync_tag}] колонка={r.pump_address} режим={r.mode} "
                f"уход={r.dispensed_ml} мл ({r.volume_liters:.3f} л) цена={r.price_kzt_per_liter:.2f} "
                f"txn={r.external_txn_id}"
            )
    if args.json:
        print("\n" + json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def _cmd_flush(args: argparse.Namespace, settings: EdgeSettings) -> int:
    db = EdgeDatabase(settings.db_path)
    worker = OutboxSyncWorker(
        db,
        vps_base_url=settings.vps_base_url,
        device_token=settings.device_token,
    )
    sent, failed = worker.flush_due(limit=args.limit)
    print(f"Отправка очереди на VPS ({settings.vps_base_url}): отправлено={sent}, ошибок={failed}")
    return 0 if failed == 0 else 1


def _cmd_monitor(args: argparse.Namespace, settings: EdgeSettings) -> int:
    from agzs_edge.monitor import run_monitor_loop

    if args.shift_start_hour is not None:
        if args.shift_start_hour < 0 or args.shift_start_hour > 23:
            print("Ошибка: --shift-start-hour должен быть в диапазоне 0..23", file=sys.stderr)
            return 2
        settings.shift_start_hour = args.shift_start_hour
    if args.shift_hours is not None:
        if args.shift_hours < 1 or args.shift_hours > 24:
            print("Ошибка: --shift-hours должен быть в диапазоне 1..24", file=sys.stderr)
            return 2
        settings.shift_hours = args.shift_hours
    if args.currency is not None:
        settings.currency_symbol = args.currency.strip() or settings.currency_symbol
    if args.refresh is not None and args.refresh <= 0:
        print("Ошибка: --refresh должен быть больше 0", file=sys.stderr)
        return 2

    return run_monitor_loop(
        settings,
        once=args.once,
        refresh_sec=args.refresh,
        recent_limit=args.limit,
        kiosk=args.kiosk,
    )


def _cmd_diagnose(args: argparse.Namespace, settings: EdgeSettings) -> int:
    if args.port:
        settings.serial_port = args.port

    from agzs_edge.diagnose import run_diagnose

    try:
        report = run_diagnose(settings, address=args.addr)
    except ValueError as exc:
        print(f"Ошибка параметра: {exc}", file=sys.stderr)
        return 2
    print(report.render())
    return 0 if report.status in {"CONNECTED"} else 1


def _cmd_update(args: argparse.Namespace, settings: EdgeSettings) -> int:
    from agzs_edge.updater import EdgeUpdater

    if args.channel is not None:
        settings.update_channel = args.channel
    if args.releases_dir:
        settings.releases_dir = Path(args.releases_dir)
    if args.wait_idle_sec < 0:
        print("Ошибка: --wait-idle-sec должен быть >= 0", file=sys.stderr)
        return 2

    db = EdgeDatabase(settings.db_path, read_only=True)
    updater = EdgeUpdater(settings, db=db)
    result = updater.run_update(
        check_only=args.check,
        wait_idle_sec=args.wait_idle_sec,
        restart_cmd=args.restart_cmd,
    )
    print(
        f"[{result.status.upper()}] станция={settings.station_code} канал={settings.update_channel} "
        f"текущая={result.current_version} целевая={result.target_version}: {result.message}"
    )
    if result.status in {"up_to_date", "update_available", "updated", "deferred_busy"}:
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agzs-edge",
        description=(
            "Станционный узел АГЗС (Компьютер — АСКА-02 — БП — УЗСГ-01): "
            "телеметрия, снятие блокировки 0x37, управление по Протоколу v3.10, SQLite и VPS."
        ),
    )
    parser.add_argument("--env-file", default=".env", help="Путь к файлу .env")
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод логов")

    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="Диагностика USB FTDI, порта, протокола и TX/RX (только чтение)")
    p_diag.add_argument("--port", default="", help="COM/TTY порт (по умолчанию из .env / by-id)")
    p_diag.add_argument("--addr", type=int, default=1, help="Адрес колонки для тестового опроса (1..8)")

    p_probe = sub.add_parser("probe", help="Разовый опрос адресов командой «Тест» (проверка связи с АСКА-02)")
    p_probe.add_argument("--port", default="", help="COM-порт (например COM7 или /dev/ttyUSB0)")
    p_probe.add_argument("--baudrate", type=int, default=None, help="Скорость порта (по умолчанию из .env)")
    p_probe.add_argument("--timeout", type=float, default=None, help="Таймаут ожидания ответа в секундах")
    p_probe.add_argument(
        "--checksum",
        choices=["xor", "sum7", "sum8", "all"],
        default=None,
        help="Режим контрольной суммы BCC в запросе (all = перебрать xor, sum7, sum8)",
    )
    p_probe.add_argument("--all-addresses", action="store_true", help="Опросить все адреса 1..8")
    p_probe.add_argument("--emulator", action="store_true", help="Использовать встроенный имитатор ответа")

    p_listen = sub.add_parser("listen", help="Живой просмотр кадров с одного адреса без записи в БД")
    p_listen.add_argument("--port", default="", help="COM-порт (например COM7)")
    p_listen.add_argument("--baudrate", type=int, default=None, help="Скорость порта (по умолчанию из .env)")
    p_listen.add_argument("--timeout", type=float, default=None, help="Таймаут ожидания ответа в секундах")
    p_listen.add_argument(
        "--checksum",
        choices=["xor", "sum7", "sum8", "any"],
        default=None,
        help="Режим контрольной суммы BCC (по умолчанию из .env)",
    )
    p_listen.add_argument("--addr", type=int, default=1, help="Адрес колонки (1..8)")
    p_listen.add_argument("--count", type=int, default=None, help="Число опросов (по умолчанию бесконечно)")
    p_listen.add_argument("--emulator", action="store_true", help="Использовать встроенный имитатор")

    p_watch = sub.add_parser("watch-fill", help="Считать один налив выбранного адреса без записи в базу")
    p_watch.add_argument("--port", default="", help="COM-порт")
    p_watch.add_argument("--baudrate", type=int, default=None, help="Скорость порта (по умолчанию из .env)")
    p_watch.add_argument(
        "--checksum",
        choices=["xor", "sum7", "sum8", "any"],
        default=None,
        help="Режим контрольной суммы BCC (по умолчанию из .env)",
    )
    p_watch.add_argument("--addr", type=int, default=1, help="Адрес колонки (1..8)")
    p_watch.add_argument("--seconds", type=float, default=900.0, help="Максимум секунд наблюдения")
    p_watch.add_argument("--idle", type=float, default=8.0, help="Сколько секунд тишины после налива считать концом")
    p_watch.add_argument("--timeout", type=float, default=0.8, help="Таймаут одного чтения")
    p_watch.add_argument("--emulator", action="store_true", help="Использовать встроенный имитатор")

    p_serve = sub.add_parser("serve", help="Непрерывный опрос АСКА-02, запись в локальную БД и отправка на VPS")
    p_serve.add_argument("--port", default="", help="Переопределить COM-порт")
    p_serve.add_argument("--emulator", action="store_true", help="Запустить на имитаторе кадров")
    p_serve.add_argument("--no-sync", action="store_true", help="Только локальная запись в SQLite без отправки на VPS")
    p_serve.add_argument("--cycles", type=int, default=None, help="Ограничить число циклов опроса (для проверки)")
    p_serve.add_argument(
        "--auto-reset",
        action="store_true",
        help="Автоматически отправлять «Сброс» (0x37) после останова '07' для работы с БП без пульта",
    )

    def _add_psu_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--port", default="", help="COM-порт (например COM7 или /dev/ttyUSB0)")
        p.add_argument("--baudrate", type=int, default=None, help="Скорость порта (по умолчанию из .env)")
        p.add_argument("--timeout", type=float, default=None, help="Таймаут ожидания ответа в секундах")
        p.add_argument("--addr", type=int, default=1, help="Адрес колонки (1..8)")
        p.add_argument("--emulator", action="store_true", help="Использовать встроенный имитатор УЗСГ-01")

    p_unlock = sub.add_parser(
        "unlock",
        aliases=["reset"],
        help="Снять блокировку колонки из '07'/'04' в готовность '05' командой СБРОС (0x37)",
    )
    _add_psu_common(p_unlock)
    p_unlock.add_argument("--force", action="store_true", help="Отправить СБРОС даже если колонка уже в '05'")

    p_buttons = sub.add_parser(
        "buttons",
        help="Управление кнопками на колонке УЗСГ-01 (0.16 вкл / 0.17 выкл / 0.18 блок сброса)",
    )
    _add_psu_common(p_buttons)
    p_buttons.add_argument(
        "--mode",
        choices=["enable", "disable", "lock-reset"],
        required=True,
        help="Режим кнопок на колонке",
    )

    p_dose = sub.add_parser("set-dose", help="Задать дозу налива с компьютера (команда 0x39)")
    _add_psu_common(p_dose)
    p_dose.add_argument("--liters", type=float, default=None, help="Доза в литрах (например 20 или 15.5)")
    p_dose.add_argument("--full-tank", action="store_true", help="Задать налив до полного бака (999 л)")

    p_start = sub.add_parser("start", help="Запустить налив с компьютера (команда ПУСК 0x35)")
    _add_psu_common(p_start)
    p_start.add_argument("--liters", type=float, default=None, help="Предварительно задать дозу в литрах")
    p_start.add_argument("--full-tank", action="store_true", help="Предварительно задать до полного (999 л)")

    p_stop = sub.add_parser("stop", help="Остановить налив с компьютера (команда ОСТАНОВ 0x36)")
    _add_psu_common(p_stop)
    p_stop.add_argument("--force", action="store_true", help="Отправить 0x36 без предварительной проверки состояния '03'")

    p_price = sub.add_parser("set-price", help="Установить цену за 1 литр газа (команда 0x38, код 0.15)")
    _add_psu_common(p_price)
    p_price.add_argument("--price", type=float, required=True, help="Цена за литр (например 72.00)")

    p_counters = sub.add_parser("counters", help="Прочитать суммарный/суточный счётчики, температуру и ТПР (0x38)")
    _add_psu_common(p_counters)
    p_counters.add_argument("--mass", action="store_true", help="Запросить значения в килограммах и плотность")

    p_console = sub.add_parser(
        "console",
        help="Интерактивный программный пульт оператора ПК — АСКА-02 — БП — УЗСГ-01",
    )
    _add_psu_common(p_console)

    p_status = sub.add_parser("status", help="Показать состояние локальной БД и очереди на VPS")
    p_status.add_argument("--limit", type=int, default=10, help="Сколько последних заправок показать")
    p_status.add_argument("--json", action="store_true", help="Вывести также JSON-сводку")

    p_monitor = sub.add_parser(
        "monitor",
        help="Вывести табло статистики по колонкам и итог за смену (без входа в систему на tty1)",
    )
    p_monitor.add_argument("--once", action="store_true", help="Вывести табло один раз и завершиться")
    p_monitor.add_argument("--refresh", type=float, default=None, help="Интервал обновления экрана (сек.)")
    p_monitor.add_argument("--limit", type=int, default=12, help="Сколько последних наливов показать в журнале")
    p_monitor.add_argument(
        "--shift-start-hour",
        type=int,
        default=None,
        help="Час начала смены (0..23, по умолчанию из .env)",
    )
    p_monitor.add_argument(
        "--shift-hours",
        type=int,
        default=None,
        help="Длительность смены в часах (1..24, по умолчанию из .env)",
    )
    p_monitor.add_argument("--currency", default=None, help="Символ валюты (например ₸ или ₽)")
    p_monitor.add_argument(
        "--kiosk",
        action="store_true",
        help="Режим киоска для /dev/tty1 (игнорировать Ctrl+C, Ctrl+Z, Ctrl+\\)",
    )

    p_flush = sub.add_parser("flush", help="Разово выгрузить очередь неотправленных заправок на VPS")
    p_flush.add_argument("--limit", type=int, default=50, help="Максимум пакетов за один прогон")

    p_update = sub.add_parser(
        "update",
        help="Проверить и безопасно установить обновление station-edge с центрального VPS",
    )
    p_update.add_argument("--check", action="store_true", help="Только проверить наличие новой версии")
    p_update.add_argument(
        "--channel",
        choices=["stable", "canary", "ring0", "ring1", "ring2"],
        default=None,
        help="Кольцо/канал обновлений (по умолчанию из AGZS_UPDATE_CHANNEL)",
    )
    p_update.add_argument(
        "--wait-idle-sec",
        type=float,
        default=180.0,
        help="Сколько секунд ждать завершения активного налива перед рестартом (по умолчанию 180)",
    )
    p_update.add_argument(
        "--restart-cmd",
        default="",
        help="Команда перезапуска сервиса после установки нового .whl",
    )
    p_update.add_argument(
        "--releases-dir",
        default="",
        help="Каталог хранения скачанных .whl пакетов",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        settings = EdgeSettings.from_env(Path(args.env_file))
    except Exception as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    if args.command == "diagnose":
        return _cmd_diagnose(args, settings)
    if args.command == "probe":
        return _cmd_probe(args, settings)
    if args.command == "listen":
        return _cmd_listen(args, settings)
    if args.command == "watch-fill":
        return _cmd_watch_fill(args, settings)
    if args.command == "serve":
        return _cmd_serve(args, settings)
    if args.command in {"unlock", "reset"}:
        return _cmd_unlock(args, settings)
    if args.command == "buttons":
        return _cmd_buttons(args, settings)
    if args.command == "set-dose":
        return _cmd_set_dose(args, settings)
    if args.command == "start":
        return _cmd_start(args, settings)
    if args.command == "stop":
        return _cmd_stop(args, settings)
    if args.command == "set-price":
        return _cmd_set_price(args, settings)
    if args.command == "counters":
        return _cmd_counters(args, settings)
    if args.command == "console":
        return _cmd_console(args, settings)
    if args.command == "status":
        return _cmd_status(args, settings)
    if args.command == "monitor":
        return _cmd_monitor(args, settings)
    if args.command == "flush":
        return _cmd_flush(args, settings)
    if args.command == "update":
        return _cmd_update(args, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
