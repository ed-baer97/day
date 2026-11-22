"""Пуск как на пульте: сброс, «ВКЛ», температура, плотность, доза, 10 секунд.

Служба station-edge должна быть остановлена: порт один.
После 0x35 всегда уходит останов 0x36.
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
    build_param_command,
    build_reset_command,
    build_set_dose_command,
    build_start_command,
    build_stop_command,
    build_test_command,
    parse_iskra_frame,
)
from agzs_edge.serial_link import PollRawResult, build_link

FULL_TANK_ML = 999_000
HOLD_SEC = 10.0


def _describe(frame: IskraTelemetryFrame) -> str:
    dose = frame.preset_dose_ml
    dose_text = f" доза_мл={dose}" if dose is not None else ""
    return (
        f"сост={frame.state_code} клапан={int(frame.valve_open)} "
        f"поле={frame.price_raw} объём={frame.volume_raw} "
        f"status={frame.status_byte17:02X} {frame.status_byte18:02X}{dose_text}"
    )


def _exchange(link, address: int, request: bytes, title: str) -> IskraTelemetryFrame | None:
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


def _sensor_note(frame: IskraTelemetryFrame, title: str) -> None:
    extra = frame.raw_bytes[5:9]
    text = extra.decode("ascii", errors="replace")
    if title == "ТЕМПЕРАТУРА":
        sign = -1.0 if extra[0] == 0x31 else 1.0
        digits = text[1:]
        if digits.isdigit():
            print(f"   температура={sign * (int(digits) / 10.0):.1f} C", flush=True)
    elif text.isdigit():
        print(f"   плотность_поле={int(text) / 1000.0:.3f}", flush=True)


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
        status = _exchange(link, address, build_test_command(address, checksum_mode=mode), "ТЕСТ")
        if status is None:
            return 1
        status = _exchange(link, address, build_reset_command(address, checksum_mode=mode), "СБРОС")
        if status is None or status.state_code != STATE_IDLE:
            code = status.state_code if status is not None else "нет кадра"
            print(f"Пуск не отправлен: после сброса колонка в '{code}', нужен '05'.", flush=True)
            return 2
        _exchange(
            link,
            address,
            build_param_command(address, "0.16", checksum_mode=mode),
            "ВКЛ",
        )
        for code, status_ascii, title in (
            ("0.12", "00", "ТЕМПЕРАТУРА"),
            ("0.12", "01", "ПЛОТНОСТЬ"),
        ):
            frame = _exchange(
                link,
                address,
                build_param_command(address, code, status_ascii=status_ascii, checksum_mode=mode),
                title,
            )
            if frame is not None:
                _sensor_note(frame, title)
            status = _exchange(link, address, build_reset_command(address, checksum_mode=mode), "СБРОС")
        if status is None or status.state_code != STATE_IDLE:
            code = status.state_code if status is not None else "нет кадра"
            print(f"Пуск не отправлен: перед дозой колонка в '{code}', нужен '05'.", flush=True)
            return 2
        status = _exchange(
            link,
            address,
            build_set_dose_command(address, FULL_TANK_ML, checksum_mode=mode),
            "ДОЗА 999 л",
        )
        if status is None or status.state_code not in {STATE_DOSE_SET, STATE_STOPPED}:
            code = status.state_code if status is not None else "нет кадра"
            print(f"Пуск не отправлен: колонка в '{code}', нужен '01' или '04'.", flush=True)
            return 2
        started_frame = _exchange(link, address, build_start_command(address, checksum_mode=mode), "ПУСК")
        started = True
        if started_frame is None:
            print("Ответ на пуск пустой. Останов всё равно будет отправлен.", flush=True)
        deadline = time.monotonic() + HOLD_SEC
        while time.monotonic() < deadline:
            _exchange(link, address, build_test_command(address, checksum_mode=mode), "ТЕСТ")
            time.sleep(0.4)
        return 0
    finally:
        if started:
            _exchange(link, address, build_stop_command(address, checksum_mode=mode), "СТОП")
            _exchange(link, address, build_test_command(address, checksum_mode=mode), "ТЕСТ")
        link.close()


if __name__ == "__main__":
    sys.exit(main())
