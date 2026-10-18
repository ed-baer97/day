"""Имитация Топаз-119-28М: один отпуск, только чтение.

  python scripts/fake_topaz.py --volume 40.5 --txn topaz-1

Повторы с тем же --txn сервер помечает duplicate и не вычитает литры второй раз.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(description="Имитация отпуска Топаз-119-28М")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--station", default="a2222222-2222-2222-2222-222222222201")
    parser.add_argument("--tank", default="b2222222-2222-2222-2222-222222222201")
    parser.add_argument("--dispenser", default="d2222222-2222-2222-2222-222222222201")
    parser.add_argument("--volume", type=float, required=True)
    parser.add_argument("--txn", default="")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    payload = {
        "station_id": args.station,
        "dispenser_id": args.dispenser,
        "tank_id": args.tank,
        "volume_liters": args.volume,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    if args.txn:
        payload["external_txn_id"] = args.txn
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-Device-Token"] = args.token
    url = args.base.rstrip("/") + "/api/v1/ingest/dispense"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        print(error.code, error.read().decode())
        raise SystemExit(1) from error
    print(body.get("message"), body.get("calculated_remainder_liters"), "duplicate" if body.get("duplicate") else "")


if __name__ == "__main__":
    main()
