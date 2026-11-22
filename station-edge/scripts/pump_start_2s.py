"""Разовый пуск насоса на 2 секунды через АСКА-02.

Служба station-edge должна быть остановлена: порт один.
Пуск 0x35 уходит только из '01' или '04'. Из '07' скрипт сначала шлёт сброс 0x37,
из '05' — дозу 999 л (0x39), затем 0x35. Через 2 секунды всегда уходит останов 0x36.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import (
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_STOPPED,
    IskraFrameError,
    IskraTelemetryFrame,
    build_reset_command,
    build_set_dose_command,
    build_start_command,
    build_stop_command,
    build_test_command,
    parse_iskra_frame,
)
from agzs_edge.serial_link import PollRawResult, build_link

FULL_TANK_ML = 999_000
HOLD_SEC = 2.0


def _describe(frame: IskraTelemetryFrame) -> str:
    dose = frame.preset_dose_ml
    dose_text = f" доза_мл={dose}" if dose is not None else ""
    return (
        f"сост={frame.state_code} клапан={int(frame.valve_open)} "
        f"поле={frame.price_raw} объём={frame.volume_raw} "
        f"status={frame.status_byte17:02X} {frame.status_byte18:02X}{dose_text}"
    )


def _exchange(link, address: int, request: bytes, mode: str, title: str) -> IskraTelemetryFrame | None:
    print(f"TX {title} {request.hex(' ').upper()}", flush=True)
    result: PollRawResult = link.send_command(address, request)
    if result.error_message:
        print(f"RX {title} ошибка: {result.error_message}", flush=True)
        return None
    if not result.has_response:
        print(f"RX {title} нет ответа", flush=True)
        return None
    print(f"RX {title} {result.response_bytes.hex(' ').upper()}", flush=True)
    try:
        frame = parse_iskra_frame(result.response_bytes, link.layout)
    except IskraFrameError as exc:
        print(f"RX {title} кадр не разобран: {exc}", flush=True)
        return None
    print(f"   {title}: {_describe(frame)}", flush=True)
    return frame


def main() -> int:
    settings = EdgeSettings.from_env(ROOT / ".env")
    if not settings.pump_addresses:
        print("В .env нет AGZS_PUMP_ADDRESSES", flush=True)
        return 1
    address = settings.pump_addresses[0]
    mode = settings.layout.tx_checksum_mode
    link = build_link(settings)
    started = False
    try:
        link.open()
        status = _exchange(link, address, build_test_command(address, checksum_mode=mode), mode, "ТЕСТ")
        if status is None:
            return 1
        if status.state_code not in {STATE_DOSE_SET, STATE_STOPPED}:
            if status.state_code != STATE_IDLE:
                status = _exchange(
                    link, address, build_reset_command(address, checksum_mode=mode), mode, "СБРОС"
                )
            if status is not None and status.state_code == STATE_IDLE:
                status = _exchange(
                    link,
                    address,
                    build_set_dose_command(address, FULL_TANK_ML, checksum_mode=mode),
                    mode,
                    "ДОЗА 999 л",
                )
        if status is None or status.state_code not in {STATE_DOSE_SET, STATE_STOPPED}:
            code = status.state_code if status is not None else "нет кадра"
            print(f"Пуск не отправлен: колонка в '{code}', нужен '01' или '04'.", flush=True)
            return 2
        started_frame = _exchange(
            link, address, build_start_command(address, checksum_mode=mode), mode, "ПУСК"
        )
        started = True
        if started_frame is None:
            print("Ответ на пуск пустой. Останов всё равно будет отправлен.", flush=True)
        deadline = time.monotonic() + HOLD_SEC
        while time.monotonic() < deadline:
            _exchange(link, address, build_test_command(address, checksum_mode=mode), mode, "ТЕСТ")
            time.sleep(0.4)
        return 0
    finally:
        if started:
            _exchange(link, address, build_stop_command(address, checksum_mode=mode), mode, "СТОП")
            _exchange(link, address, build_test_command(address, checksum_mode=mode), mode, "ТЕСТ")
        link.close()


if __name__ == "__main__":
    sys.exit(main())
