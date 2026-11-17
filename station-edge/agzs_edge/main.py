"""CLI-интерфейс станционного узла АГЗС (АСКА-02 + УЗГС-01).

Доступные команды:
  python -m agzs_edge diagnose -- USB/FTDI/протокол/TX-RX (только чтение «Тест»)
  python -m agzs_edge probe   -- разовый опрос адресов 1..6 командой «Тест» (проверка живой пары и полярности)
  python -m agzs_edge listen  -- живой мониторинг 23-байтных кадров в консоли без записи/отправки
  python -m agzs_edge serve   -- боевой демон: опрос АСКА-02 + запись в SQLite + отправка на VPS
  python -m agzs_edge status  -- сводка по локальной БД и очереди отправки на VPS
  python -m agzs_edge flush   -- принудительная отправка накопленной очереди outbox на VPS

Эквивалент запрошенного `python3 -m station_edge --diagnose`:
  python3 -m agzs_edge diagnose
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

from agzs_edge.config import EdgeSettings, FrameLayout
from agzs_edge.iskra import IskraFrameError, parse_iskra_frame
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
    if args.emulator or settings.source_mode == "emulator":
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
    addresses = tuple(range(1, 7)) if args.all_addresses else settings.pump_addresses
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
                        f"ошибка={frame.error_code}, цена={frame.price_kzt_per_liter:.2f} ₸/л ({frame.price_raw}), "
                        f"объём={frame.volume_ml} мл, BCC=0x{frame.checksum_byte:02X}"
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
                        f"ош={frame.error_code} цена={frame.price_kzt_per_liter:.2f} объём={frame.volume_ml} мл"
                    )
                except IskraFrameError as exc:
                    print(f"[{step:04d}] RX RAW ({len(res.response_bytes)}B): {res.response_bytes.hex(' ').upper()} | {exc}")
            time.sleep(settings.poll_interval_sec)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
    return 0


def _cmd_serve(args: argparse.Namespace, settings: EdgeSettings) -> int:
    if args.port:
        settings.serial_port = args.port
    if args.emulator:
        settings.source_mode = "emulator"
    if args.no_sync:
        settings.sync_enabled = False
    service = StationEdgeService(settings)
    service.serve(max_cycles=args.cycles)
    return 0


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


def _cmd_diagnose(args: argparse.Namespace, settings: EdgeSettings) -> int:
    if args.port:
        settings.serial_port = args.port

    # Полный анализатор АСКА-02 (по умолчанию без лишнего TX, если не --live)
    if getattr(args, "aska02", False) or getattr(args, "repair_software", False):
        from pathlib import Path as _Path

        from agzs_edge.diagnostics.aska02_analyzer import run_aska02_diagnostic

        report_dir = _Path(getattr(args, "report_dir", None) or "reports")
        live = bool(getattr(args, "live", False))
        repair = bool(getattr(args, "repair_software", False))
        report = run_aska02_diagnostic(
            settings,
            live=live,
            repair=repair,
            report_dir=report_dir,
        )
        print(f"PRIMARY: {report.primary_diagnosis}")
        print(f"ERROR LOCATION: {report.error_location}")
        print(f"TX={report.transmitted_bytes} RX={report.received_bytes}")
        print(f"Reports: {report_dir / 'aska02_diagnostic_report.md'}")
        if report.repair_actions:
            print("REPAIR:")
            for a in report.repair_actions:
                print(f"  - {a}")
        print("")
        for ev in report.trace[-20:]:
            print(ev.format_line())
        # 0 только если есть USB-ответ и он разобран — иначе 1 (диагностика «не CONNECTED»)
        return 0 if report.received_bytes > 0 and report.primary_diagnosis not in {
            "RESPONSE_TIMEOUT",
            "USB_DEVICE_NOT_FOUND",
            "SERIAL_OPEN_FAILED",
            "TX_WRITE_FAILED",
        } else 1

    from agzs_edge.diagnose import run_diagnose

    report = run_diagnose(settings, address=args.addr)
    print(report.render())
    return 0 if report.status in {"CONNECTED"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agzs-edge",
        description="Станционный узел АГЗС: опрос УЗГС-01 через АСКА-02 (Искра 1.72, только чтение), запись в SQLite и синхронизация с VPS.",
    )
    parser.add_argument("--env-file", default=".env", help="Путь к файлу .env")
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод логов")

    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="Диагностика USB FTDI, порта, протокола и TX/RX (только чтение)")
    p_diag.add_argument("--port", default="", help="COM/TTY порт (по умолчанию из .env / by-id)")
    p_diag.add_argument("--addr", type=int, default=1, help="Адрес колонки для тестового опроса (1..6)")
    p_diag.add_argument(
        "--aska02",
        action="store_true",
        help="Полный ASKA-02 Protocol & Communication Analyzer (L1–L6 + отчёт)",
    )
    p_diag.add_argument(
        "--live",
        action="store_true",
        help="Разрешить один живой TX «Тест» (только чтение). Без флага порт службы не трогаем",
    )
    p_diag.add_argument(
        "--repair-software",
        action="store_true",
        help="Исправить только подтверждённые программные дефекты (с бэкапом; без прошивки/ПУСК)",
    )
    p_diag.add_argument(
        "--report-dir",
        default="reports",
        help="Каталог для aska02_diagnostic_report.json/.md",
    )

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
    p_probe.add_argument("--all-addresses", action="store_true", help="Опросить все адреса 1..6")
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
    p_listen.add_argument("--addr", type=int, default=1, help="Адрес колонки (1..6)")
    p_listen.add_argument("--count", type=int, default=None, help="Число опросов (по умолчанию бесконечно)")
    p_listen.add_argument("--emulator", action="store_true", help="Использовать встроенный имитатор")

    p_serve = sub.add_parser("serve", help="Непрерывный опрос АСКА-02, запись в локальную БД и отправка на VPS")
    p_serve.add_argument("--port", default="", help="Переопределить COM-порт")
    p_serve.add_argument("--emulator", action="store_true", help="Запустить на имитаторе кадров")
    p_serve.add_argument("--no-sync", action="store_true", help="Только локальная запись в SQLite без отправки на VPS")
    p_serve.add_argument("--cycles", type=int, default=None, help="Ограничить число циклов опроса (для проверки)")

    p_status = sub.add_parser("status", help="Показать состояние локальной БД и очереди на VPS")
    p_status.add_argument("--limit", type=int, default=10, help="Сколько последних заправок показать")
    p_status.add_argument("--json", action="store_true", help="Вывести также JSON-сводку")

    p_flush = sub.add_parser("flush", help="Разово выгрузить очередь неотправленных заправок на VPS")
    p_flush.add_argument("--limit", type=int, default=50, help="Максимум пакетов за один прогон")

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
    if args.command == "serve":
        return _cmd_serve(args, settings)
    if args.command == "status":
        return _cmd_status(args, settings)
    if args.command == "flush":
        return _cmd_flush(args, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
