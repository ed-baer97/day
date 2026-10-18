"""Кладёт скрипт уровня на Shelly Plus Uni и запускает его.

  python scripts/install_shelly_level.py ^
    --shelly 192.168.0.104 ^
    --url http://192.168.0.106:8000/api/v1/ingest/level ^
    --token КЛЮЧ_РЕЗЕРВУАРА

Скрипт на приборе сам шлёт напряжение каждые 15 секунд.
Ключ берётся из карточки резервуара, поле X-Device-Token.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("shelly_level.js")
SCRIPT_NAME = "level"


def js_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_script(source: str, url: str, token: str) -> str:
    if "%%SERVER_URL%%" not in source or "%%DEVICE_TOKEN%%" not in source:
        raise ValueError("в скрипте нет полей адреса и ключа")
    rendered = source.replace("%%SERVER_URL%%", js_quote(url)).replace("%%DEVICE_TOKEN%%", js_quote(token))
    if "%%SERVER_URL%%" in rendered or "%%DEVICE_TOKEN%%" in rendered:
        raise ValueError("подстановка не завершилась")
    return rendered


def rpc(host: str, method: str, params: dict | None = None) -> dict:
    # Shelly обрезает большой JSON, если кириллица уехала в \uXXXX.
    body = json.dumps({"id": 1, "method": method, "params": params or {}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host}/rpc",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=8) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")
    except urllib.error.URLError as error:
        raise SystemExit(f"нет связи с Shelly: {error.reason}") from error
    payload = json.loads(raw) if raw else None
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error")
    if isinstance(error, dict):
        raise SystemExit(str(error.get("message") or "ошибка Shelly"))
    result = payload.get("result")
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise SystemExit("непонятный ответ Shelly")
    return result


def put_code(host: str, identifier: int, code: str) -> None:
    step = 900
    for offset in range(0, len(code), step):
        params: dict = {"id": identifier, "code": code[offset : offset + step]}
        if offset:
            params["append"] = True
        rpc(host, "Script.PutCode", params)


def script_id(host: str) -> int:
    listed = rpc(host, "Script.List")
    for item in listed.get("scripts") or []:
        if isinstance(item, dict) and item.get("name") == SCRIPT_NAME:
            return int(item["id"])
    created = rpc(host, "Script.Create", {"name": SCRIPT_NAME})
    return int(created["id"])


def stop_script(host: str, identifier: int) -> None:
    for _ in range(3):
        rpc(host, "Script.Stop", {"id": identifier})
        time.sleep(0.4)
        status = rpc(host, "Script.GetStatus", {"id": identifier})
        if not status.get("running"):
            return


def install(host: str, url: str, token: str) -> int:
    code = render_script(SCRIPT_PATH.read_text(encoding="utf-8"), url, token)
    identifier = script_id(host)
    stop_script(host, identifier)
    put_code(host, identifier, code)
    rpc(host, "Script.Start", {"id": identifier})
    time.sleep(0.4)
    rpc(host, "Script.SetConfig", {"id": identifier, "config": {"enable": True}})
    status = rpc(host, "Script.GetStatus", {"id": identifier})
    print(identifier, "running" if status.get("running") else status)
    return identifier


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузка скрипта уровня на Shelly Plus Uni")
    parser.add_argument("--shelly", default="192.168.0.104")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    install(args.shelly, args.url, args.token)


if __name__ == "__main__":
    main()
