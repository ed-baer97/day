"""CLI-интерфейс станционного узла АГЗС (АСКА-02 + УЗГС-01).

Доступные команды:
  python -m agzs_edge probe   -- разовый опрос адресов 1..6 командой «Тест» (проверка живой пары и полярности)
  python -m agzs_edge listen  -- живой мониторинг 23-байтных кадров в консоли без записи/отправки
  python -m agzs_edge serve   -- боевой демон: опрос АСКА-02 + запись в SQLite + отправка на VPS
  python -m agzs_edge status  -- сводка по локальной БД и очереди отправки на VPS
  python -m agzs_edge flush   -- принудительная отправка накопленной очереди outbox на VPS
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import IskraFrameError, parse_iskra_frame
from agzs_edge.serial_link import EmulatorAskaLink, SerialAskaLink, list_available_serial_ports
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


def _cmd_probe(args: argparse.Namespace, settings: EdgeSettings) -> int:
    port = args.port or settings.serial_port
    addresses = tuple(range(1, 7)) if args.all_addresses else settings.pump_addresses

    print("=== Диагностика COM-портов системы ===")
    ports = list_available_serial_ports()
    if not ports:
        print("  Доступные COM-порты не обнаружены (или pyserial не видит устройств).")
    else:
        for dev, desc, hwid in ports:
            marker = " <-- выбран" if dev.upper() == port.upper() else ""
            print(f"  {dev}: {desc} [{hwid}]{marker}")

    print(f"\n=== Разовый опрос АСКА-02 ({port}, {settings.serial_baudrate} 8N1, команда «Тест» код 4) ===")
    link = (
        EmulatorAskaLink(layout=settings.layout)
        if args.emulator or settings.source_mode == "emulator"
        else SerialAskaLink(
            port=port,
            baudrate=settings.serial_baudrate,
            timeout_sec=settings.serial_timeout_sec,
            layout=settings.layout,
        )
    )

    any_reply = False
    try:
        for addr in addresses:
            res = link.poll_test(addr)
            req_hex = res.request_bytes.hex(" ").upper()
            if res.error_message:
                print(f"  [Адрес {addr}] TX: {req_hex} -> ОШИБКА ПОРТА: {res.error_message}")
                continue
            if not res.has_response:
                print(f"  [Адрес {addr}] TX: {req_hex} -> НЕТ ОТВЕТА (0 байт)")
                continue

            any_reply = True
            resp_hex = res.response_bytes.hex(" ").upper()
            try:
                frame = parse_iskra_frame(res.response_bytes, settings.layout)
                print(
                    f"  [Адрес {addr}] TX: {req_hex} -> RX ({len(res.response_bytes)} Б): {resp_hex}\n"
                    f"             ОК: адрес={frame.address}, сост={frame.state_code}({frame.state_name}), "
                    f"ошибка={frame.error_code}, цена={frame.price_kzt_per_liter:.2f} ₸/л ({frame.price_raw}), "
                    f"объём={frame.volume_ml} мл, BCC=0x{frame.checksum_byte:02X}"
                )
            except IskraFrameError as exc:
                print(
                    f"  [Адрес {addr}] TX: {req_hex} -> RX ({len(res.response_bytes)} Б): {resp_hex}\n"
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
    port = args.port or settings.serial_port
    addr = args.addr
    link = (
        EmulatorAskaLink(layout=settings.layout)
        if args.emulator or settings.source_mode == "emulator"
        else SerialAskaLink(
            port=port,
            baudrate=settings.serial_baudrate,
            timeout_sec=settings.serial_timeout_sec,
            layout=settings.layout,
        )
    )
    print(f"Мониторинг адреса {addr} через {port} (Ctrl+C для выхода)...")
    step = 0
    try:
        while args.count is None or step < args.count:
            step += 1
            res = link.poll_test(addr)
            if not res.has_response:
                print(f"[{step:04d}] Нет ответа ({res.error_message or 'таймаут'})")
            else:
                try:
                    frame = parse_iskra_frame(res.response_bytes, settings.layout)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agzs-edge",
        description="Станционный узел АГЗС: опрос УЗГС-01 через АСКА-02 (Искра 1.72, только чтение), запись в SQLite и синхронизация с VPS.",
    )
    parser.add_argument("--env-file", default=".env", help="Путь к файлу .env")
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод логов")

    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Разовый опрос адресов командой «Тест» (проверка связи с АСКА-02)")
    p_probe.add_argument("--port", default="", help="COM-порт (например COM7 или /dev/ttyUSB0)")
    p_probe.add_argument("--all-addresses", action="store_true", help="Опросить все адреса 1..6")
    p_probe.add_argument("--emulator", action="store_true", help="Использовать встроенный имитатор ответа")

    p_listen = sub.add_parser("listen", help="Живой просмотр кадров с одного адреса без записи в БД")
    p_listen.add_argument("--port", default="", help="COM-порт (например COM7)")
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
