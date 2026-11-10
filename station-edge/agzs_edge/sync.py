"""Отправка очереди исходящих событий (outbox_queue) со станции на центральный VPS.

Шлёт пакеты на `POST /api/v1/ingest/dispense` с заголовком `X-Device-Token`.
Повторная отправка одного и того же `external_txn_id` идемпотентна: сервер возвращает
`duplicate: true`, не создавая вторую заправку и не списывая литры повторно.
Центр никаких команд пуска или останова на станцию не возвращает.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from agzs_edge.storage import EdgeDatabase, OutboxItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VpsSendResult:
    ok: bool
    duplicate: bool = False
    status_code: int = 200
    response_text: str = ""
    error_text: str = ""


def post_dispense_to_vps(
    base_url: str,
    device_token: str,
    payload_json: str,
    *,
    timeout_sec: float = 10.0,
) -> VpsSendResult:
    """Выполняет HTTP POST `/api/v1/ingest/dispense` на центральный сервер (Ubuntu VPS)."""
    url = base_url.rstrip("/") + "/api/v1/ingest/dispense"
    headers = {"Content-Type": "application/json"}
    if device_token:
        headers["X-Device-Token"] = device_token
    req = urllib.request.Request(
        url=url,
        data=payload_json.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw_text = resp.read().decode("utf-8", errors="replace")
            status_code = getattr(resp, "status", 200)
            try:
                body = json.loads(raw_text)
            except json.JSONDecodeError:
                body = {}
            accepted = bool(body.get("accepted", True))
            duplicate = bool(body.get("duplicate", False))
            if accepted:
                return VpsSendResult(
                    ok=True,
                    duplicate=duplicate,
                    status_code=status_code,
                    response_text=raw_text,
                )
            return VpsSendResult(
                ok=False,
                status_code=status_code,
                error_text=f"Сервер отклонил пакет: {raw_text}",
            )
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return VpsSendResult(
            ok=False,
            status_code=exc.code,
            error_text=f"HTTP {exc.code}: {err_body or exc.reason}",
        )
    except Exception as exc:
        return VpsSendResult(
            ok=False,
            status_code=0,
            error_text=f"Ошибка связи с VPS: {exc}",
        )


class OutboxSyncWorker:
    """Обработчик очереди `outbox_queue`."""

    def __init__(
        self,
        db: EdgeDatabase,
        *,
        vps_base_url: str,
        device_token: str,
        sender: Callable[[str, str, str], VpsSendResult] | None = None,
    ) -> None:
        self.db = db
        self.vps_base_url = vps_base_url
        self.device_token = device_token
        self._sender = sender or (
            lambda url, token, payload: post_dispense_to_vps(url, token, payload)
        )

    def flush_due(self, *, limit: int = 25, now: datetime | None = None) -> tuple[int, int]:
        """Пытается отправить все готовые к отправке записи из `outbox_queue`.

        Возвращает кортеж `(sent_count, failed_count)`.
        """
        items: list[OutboxItem] = self.db.fetch_due_outbox(limit=limit, now=now)
        sent_count = 0
        failed_count = 0

        for item in items:
            result = self._sender(self.vps_base_url, self.device_token, item.payload_json)
            if result.ok:
                self.db.mark_outbox_sent(item.external_txn_id, result.response_text)
                sent_count += 1
                logger.info(
                    "Пакет %s доставлен на VPS (%s)",
                    item.external_txn_id,
                    "дубликат проигнорирован" if result.duplicate else "принят",
                )
            else:
                self.db.mark_outbox_failed(item.external_txn_id, result.error_text, now=now)
                failed_count += 1
                logger.warning(
                    "Не удалось отправить пакет %s (попытка %d): %s",
                    item.external_txn_id,
                    item.attempts + 1,
                    result.error_text,
                )

        return sent_count, failed_count
