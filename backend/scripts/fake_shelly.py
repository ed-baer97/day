"""Имитация Shelly: шлёт уровень на локальный сервер.

Один замер литрами:
  python scripts/fake_shelly.py --liters 10000

Один замер вольтами (на сервере уже должна быть калибровка):
  python scripts/fake_shelly.py --volts 2.5

Повтор каждые 30 секунд:
  python scripts/fake_shelly.py --liters 10000 --repeat 5 --interval 30
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4


def post(url: str, payload: dict, token: str) -> dict:
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Device-Token"] = token
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser(description="Имитация Shelly Plus Uni")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--station", default="a2222222-2222-2222-2222-222222222201")
    parser.add_argument("--tank", default="b2222222-2222-2222-2222-222222222201")
    parser.add_argument("--liters", type=float)
    parser.add_argument("--volts", type=float)
    parser.add_argument("--token", default="")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()
    if args.liters is None and args.volts is None:
        parser.error("нужен --liters или --volts")

    url = args.base.rstrip("/") + "/api/v1/ingest/level"
    for index in range(args.repeat):
        payload = {
            "station_id": args.station,
            "tank_id": args.tank,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source_event_id": f"shelly-{uuid4()}",
        }
        if args.liters is not None:
            payload["actual_remainder_liters"] = args.liters
        if args.volts is not None:
            payload["volts"] = args.volts
        try:
            body = post(url, payload, args.token)
        except urllib.error.HTTPError as error:
            print(error.code, error.read().decode())
            raise SystemExit(1) from error
        print(index + 1, body.get("balance_status"), body.get("actual_remainder_liters"), body.get("delta_liters"))
        if index + 1 < args.repeat:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
