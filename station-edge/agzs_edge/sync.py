"""Отправка очереди исходящих событий (outbox_queue) со станции на центральный VPS.

Шлёт пакеты на `POST /api/v1/ingest/dispense` / `/dispenses/batch` с заголовком `X-Device-Token`.
Повторная отправка одного и того же `external_txn_id` идемпотентна: сервер возвращает
`duplicate: true`, не создавая вторую заправку и не списывая литры повторно.
Центр никаких команд пуска или останова на станцию не возвращает.
"""

from __future__ import annotations

import contextlib
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from agzs_edge.config import validate_vps_url
from agzs_edge.storage import EdgeDatabase, OutboxItem

logger = logging.getLogger(__name__)
MAX_BATCH_SIZE = 200
_AUTH_ERROR_CODES = frozenset({401, 403})


@dataclass(frozen=True)
class VpsSendResult:
    ok: bool
    duplicate: bool = False
    status_code: int = 200
    response_text: str = ""
    error_text: str = ""


def send_vps_request(
    base_url: str,
    path: str,
    device_token: str,
    *,
    method: str,
    body_text: str | None = None,
    accept_json: bool = False,
    allow_insecure_http: bool = False,
    timeout_sec: float = 10.0,
) -> VpsSendResult:
    """Выполняет HTTP-запрос к VPS и возвращает унифицированный VpsSendResult."""
    del accept_json
    try:
        safe_base = validate_vps_url(base_url, allow_insecure_http=allow_insecure_http)
    except ValueError as exc:
        return VpsSendResult(ok=False, status_code=0, error_text=str(exc))

    url = safe_base + path
    headers: dict[str, str] = {"Accept": "application/json"}
    if body_text is not None:
        headers["Content-Type"] = "application/json"
    if device_token:
        headers["X-Device-Token"] = device_token
    data = None if body_text is None else body_text.encode("utf-8")
    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw_text = resp.read().decode("utf-8", errors="replace")
            status_code = getattr(resp, "status", 200)
            return VpsSendResult(ok=True, status_code=status_code, response_text=raw_text)
    except urllib.error.HTTPError as exc:
        err_body = ""
        with contextlib.suppress(Exception):
            err_body = exc.read().decode("utf-8", errors="replace")
        return VpsSendResult(
            ok=False,
            status_code=exc.code,
            error_text=f"HTTP {exc.code}: {err_body or exc.reason}",
        )
    except Exception as exc:
        return VpsSendResult(ok=False, status_code=0, error_text=f"Ошибка связи с VPS: {exc}")


_send_vps_request = send_vps_request


def probe_vps_link(
    base_url: str,
    device_token: str,
    tank_id: str,
    *,
    allow_insecure_http: bool = False,
    timeout_sec: float = 10.0,
) -> VpsSendResult:
    """Проверяет, что центральный сервер принимает токен этой станции."""
    if not tank_id:
        return VpsSendResult(ok=False, error_text="не задан идентификатор резервуара")
    return send_vps_request(
        base_url,
        f"/api/v1/ingest/tanks/{tank_id}",
        device_token,
        method="GET",
        accept_json=True,
        allow_insecure_http=allow_insecure_http,
        timeout_sec=timeout_sec,
    )


def _is_non_bool_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def post_dispense_to_vps(
    base_url: str,
    device_token: str,
    payload_json: str,
    *,
    allow_insecure_http: bool = False,
    timeout_sec: float = 10.0,
) -> VpsSendResult:
    """Выполняет HTTP POST `/api/v1/ingest/dispense` и требует явный JSON ACK (`accepted: true`)."""
    result = send_vps_request(
        base_url,
        "/api/v1/ingest/dispense",
        device_token,
        method="POST",
        body_text=payload_json,
        allow_insecure_http=allow_insecure_http,
        timeout_sec=timeout_sec,
    )
    if not result.ok:
        return result
    try:
        body = json.loads(result.response_text)
    except json.JSONDecodeError as exc:
        return VpsSendResult(
            ok=False,
            status_code=result.status_code,
            response_text=result.response_text,
            error_text=f"Некорректный JSON-ответ сервера: {exc}",
        )
    if not isinstance(body, dict) or body.get("accepted") is not True:
        return VpsSendResult(
            ok=False,
            status_code=result.status_code,
            response_text=result.response_text,
            error_text=f"Сервер не подтвердил приём (accepted != true): {result.response_text[:300]}",
        )
    return VpsSendResult(
        ok=True,
        duplicate=bool(body.get("duplicate", False)),
        status_code=result.status_code,
        response_text=result.response_text,
    )


def post_dispenses_batch_to_vps(
    base_url: str,
    device_token: str,
    items: list[dict],
    *,
    allow_insecure_http: bool = False,
    timeout_sec: float = 15.0,
) -> VpsSendResult:
    """Выполняет пакетный HTTP POST `/api/v1/ingest/dispenses/batch` и проверяет подсчёт принятых/дублей."""
    payload = json.dumps({"items": items}, ensure_ascii=False)
    result = send_vps_request(
        base_url,
        "/api/v1/ingest/dispenses/batch",
        device_token,
        method="POST",
        body_text=payload,
        allow_insecure_http=allow_insecure_http,
        timeout_sec=timeout_sec,
    )
    if not result.ok:
        return result
    try:
        body = json.loads(result.response_text)
    except json.JSONDecodeError as exc:
        return VpsSendResult(
            ok=False,
            status_code=result.status_code,
            response_text=result.response_text,
            error_text=f"Некорректный JSON-ответ пакетного приёма: {exc}",
        )
    if not isinstance(body, dict) or body.get("accepted") is False:
        return VpsSendResult(
            ok=False,
            status_code=result.status_code,
            response_text=result.response_text,
            error_text=f"Сервер отклонил пакет: {result.response_text[:300]}",
        )

    accepted_count = body.get("accepted_count")
    duplicates_count = body.get("duplicates_count", 0)
    if (
        not _is_non_bool_int(accepted_count)
        or not _is_non_bool_int(duplicates_count)
        or accepted_count < 0
        or duplicates_count < 0
        or (accepted_count + duplicates_count) != len(items)
    ):
        return VpsSendResult(
            ok=False,
            status_code=result.status_code,
            response_text=result.response_text,
            error_text=f"Неполный ACK пакетного приёма ({accepted_count}+{duplicates_count} != {len(items)})",
        )
    if "results" in body:
        results = body["results"]
        if (
            not isinstance(results, list)
            or len(results) != len(items)
            or not all(isinstance(row, dict) and row.get("accepted") is True for row in results)
        ):
            return VpsSendResult(
                ok=False,
                status_code=result.status_code,
                response_text=result.response_text,
                error_text="Сервер подтвердил не все элементы пакета в results",
            )
    return result


class OutboxSyncWorker:
    """Обработчик очереди `outbox_queue` с поддержкой высокоскоростного Bulk Ingest."""

    def __init__(
        self,
        db: EdgeDatabase,
        *,
        vps_base_url: str,
        device_token: str,
        allow_insecure_http: bool = False,
        sender: Callable[[str, str, str], VpsSendResult] | None = None,
        batch_sender: Callable[[str, str, list[dict]], VpsSendResult] | None = None,
    ) -> None:
        self.db = db
        self.vps_base_url = vps_base_url
        self.device_token = device_token
        self.allow_insecure_http = allow_insecure_http
        self._sender = sender or (
            lambda url, token, payload: post_dispense_to_vps(
                url, token, payload, allow_insecure_http=self.allow_insecure_http
            )
        )
        self._batch_sender = batch_sender or (
            lambda url, token, items: post_dispenses_batch_to_vps(
                url, token, items, allow_insecure_http=self.allow_insecure_http
            )
        )

    def flush_due(self, *, limit: int = 25, now: datetime | None = None) -> tuple[int, int]:
        """Пытается отправить готовые записи из `outbox_queue` пакетами до `MAX_BATCH_SIZE`."""
        items: list[OutboxItem] = self.db.fetch_due_outbox(limit=limit, now=now)
        if not items:
            return 0, 0

        sent_count = 0
        failed_count = 0
        valid_pairs: list[tuple[OutboxItem, dict]] = []
        for it in items:
            try:
                parsed_obj = json.loads(it.payload_json)
            except ValueError as exc:
                self.db.mark_outbox_failed(
                    it.external_txn_id,
                    f"Некорректный JSON: {exc}",
                    now=now,
                    permanent=True,
                )
                failed_count += 1
                logger.error("Запись %s переведена в dead-letter (битый JSON): %s", it.external_txn_id, exc)
                continue
            if not isinstance(parsed_obj, dict):
                self.db.mark_outbox_failed(
                    it.external_txn_id,
                    "Некорректный JSON: ожидался объект",
                    now=now,
                    permanent=True,
                )
                failed_count += 1
                continue
            valid_pairs.append((it, parsed_obj))

        auth_aborted = False
        for start in range(0, len(valid_pairs), MAX_BATCH_SIZE):
            chunk_pairs = valid_pairs[start : start + MAX_BATCH_SIZE]
            chunk = [it for it, _ in chunk_pairs]
            if len(chunk_pairs) > 1:
                try:
                    parsed = [obj for _, obj in chunk_pairs]
                    batch_res = self._batch_sender(self.vps_base_url, self.device_token, parsed)
                    if batch_res.ok:
                        self.db.mark_outbox_batch_sent(
                            [(it.external_txn_id, batch_res.response_text) for it in chunk]
                        )
                        sent_count += len(chunk)
                        logger.info("Пакет из %d наливов успешно доставлен на VPS в 1 запросе", len(chunk))
                        continue
                    if batch_res.status_code in _AUTH_ERROR_CODES:
                        remaining_ids = [it.external_txn_id for it, _ in valid_pairs[start:]]
                        self.db.mark_outbox_auth_blocked(remaining_ids, batch_res.error_text, now=now)
                        failed_count += len(remaining_ids)
                        logger.error(
                            "Токен устройства отклонён сервером (HTTP %d): очередь (%d записей) переведена в auth_blocked",
                            batch_res.status_code,
                            len(remaining_ids),
                        )
                        auth_aborted = True
                        break
                    if batch_res.status_code == 0:
                        for it in chunk:
                            self.db.mark_outbox_failed(it.external_txn_id, batch_res.error_text, now=now)
                            failed_count += 1
                        logger.warning(
                            "Сетевая ошибка пакетной отправки (%s): отложено %d записей без поштучного перебора",
                            batch_res.error_text,
                            len(chunk),
                        )
                        break
                    logger.warning("Пакетная отправка отклонена (%s), переход на поштучную", batch_res.error_text)
                except Exception as exc:
                    logger.warning("Ошибка пакетной отправки (%s), переход на поштучную", exc)

            for idx, item in enumerate(chunk):
                result = self._sender(self.vps_base_url, self.device_token, item.payload_json)
                if result.ok:
                    self.db.mark_outbox_sent(item.external_txn_id, result.response_text)
                    sent_count += 1
                    logger.info(
                        "Пакет %s доставлен на VPS (%s)",
                        item.external_txn_id,
                        "дубликат проигнорирован" if result.duplicate else "принят",
                    )
                elif result.status_code in _AUTH_ERROR_CODES:
                    remaining_ids = [it.external_txn_id for it in chunk[idx:]] + [
                        it.external_txn_id for it, _ in valid_pairs[start + len(chunk) :]
                    ]
                    self.db.mark_outbox_auth_blocked(remaining_ids, result.error_text, now=now)
                    failed_count += len(remaining_ids)
                    logger.error(
                        "Токен устройства отклонён сервером (HTTP %d): остановлена отправка (%d записей в auth_blocked)",
                        result.status_code,
                        len(remaining_ids),
                    )
                    auth_aborted = True
                    break
                else:
                    permanent = result.status_code in {400, 422}
                    self.db.mark_outbox_failed(
                        item.external_txn_id,
                        result.error_text,
                        now=now,
                        permanent=permanent,
                    )
                    failed_count += 1
                    if permanent:
                        logger.error(
                            "Пакет %s отклонён сервером (HTTP %d) и переведён в dead-letter: %s",
                            item.external_txn_id,
                            result.status_code,
                            result.error_text,
                        )
                    else:
                        logger.warning(
                            "Не удалось отправить пакет %s (попытка %d): %s",
                            item.external_txn_id,
                            item.attempts + 1,
                            result.error_text,
                        )
            if auth_aborted:
                break

        return sent_count, failed_count
