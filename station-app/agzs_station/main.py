"""Точка входа пульта. Окно подключается флагом --ui и не говорит с колонкой напрямую."""

import sys

from agzs_station.application.cashier import CashierService
from agzs_station.config import Settings


def main() -> int:
    try:
        settings = Settings()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if settings.env == "production" and settings.pump_driver == "emulator":
        print("Профиль production с драйвером emulator не запускается.", file=sys.stderr)
        return 2
    if settings.env in {"emulator", "test"} and settings.pump_driver != "emulator":
        print("Профиль emulator требует AGZS_PUMP_DRIVER=emulator.", file=sys.stderr)
        return 2
    service = CashierService(
        settings.api_base,
        settings.station_code,
        training=settings.env != "production",
    )
    if "--ui" in sys.argv:
        from agzs_station.ui.window import run_window

        return run_window(service, settings.env)
    print("Касса готова. Окно кассира: agzs-station --ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
