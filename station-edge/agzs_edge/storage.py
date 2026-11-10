"""Локальная база данных станции (SQLite в режиме WAL).

Хранит:
  1. `dispenses`      — закрытые заправки с полем `dispensed_ml`, ценой, режимом и временем.
  2. `outbox_queue`   — локальная очередь исходящих пакетов на центральный VPS (гарантия доставки без дублей).
  3. `pump_live_state`— последнее известное состояние каждой колонки (для мониторинга на станции).
  4. `raw_frames`     — диагностический кольцевой буфер сырых кадров/ошибок АСКА-02.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agzs_edge.iskra import IskraTelemetryFrame
from agzs_edge.tracker import CompletedDispense

_MAX_RAW_FRAMES = 5_000


@dataclass(frozen=True)
class OutboxItem:
    id: int
    external_txn_id: str
    payload_json: str
    status: str
    attempts: int
    last_error: str | None
    created_at: str
    next_retry_at: str


@dataclass(frozen=True)
class DispenseRow:
    id: int
    external_txn_id: str
    pump_address: int
    mode: str
    preset_ml: int | None
    dispensed_ml: int
    volume_liters: float
    price_kzt_per_liter: float
    final_state_code: str
    error_code: str
    started_at: str
    finished_at: str
    synced_to_vps: bool


class EdgeDatabase:
    """Потокобезопасное хранилище SQLite для станционного ПК (Windows / Linux)."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dispenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_txn_id TEXT NOT NULL UNIQUE,
                    pump_address INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    preset_ml INTEGER,
                    dispensed_ml INTEGER NOT NULL,
                    volume_liters REAL NOT NULL,
                    price_kzt_per_liter REAL NOT NULL,
                    final_state_code TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    last_raw_frame_hex TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS outbox_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_txn_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    server_response TEXT,
                    created_at TEXT NOT NULL,
                    next_retry_at TEXT NOT NULL,
                    sent_at TEXT
                );

                CREATE TABLE IF NOT EXISTS pump_live_state (
                    pump_address INTEGER PRIMARY KEY,
                    state_code TEXT NOT NULL,
                    state_name TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    price_kzt_per_liter REAL NOT NULL,
                    volume_ml INTEGER NOT NULL,
                    raw_hex TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS raw_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pump_address INTEGER NOT NULL,
                    request_hex TEXT NOT NULL,
                    response_hex TEXT NOT NULL,
                    valid INTEGER NOT NULL,
                    note TEXT,
                    recorded_at TEXT NOT NULL
                );
                """
            )

    def update_live_state(self, frame: IskraTelemetryFrame, *, observed_at: datetime | None = None) -> None:
        stamp = (observed_at or datetime.now(timezone.utc)).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pump_live_state (
                    pump_address, state_code, state_name, error_code,
                    price_kzt_per_liter, volume_ml, raw_hex, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pump_address) DO UPDATE SET
                    state_code = excluded.state_code,
                    state_name = excluded.state_name,
                    error_code = excluded.error_code,
                    price_kzt_per_liter = excluded.price_kzt_per_liter,
                    volume_ml = excluded.volume_ml,
                    raw_hex = excluded.raw_hex,
                    updated_at = excluded.updated_at
                """,
                (
                    frame.address,
                    frame.state_code,
                    frame.state_name,
                    frame.error_code,
                    frame.price_kzt_per_liter,
                    frame.volume_ml,
                    frame.raw_hex,
                    stamp,
                ),
            )

    def log_raw_frame(
        self,
        *,
        pump_address: int,
        request_bytes: bytes,
        response_bytes: bytes,
        valid: bool,
        note: str | None = None,
    ) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        req_hex = request_bytes.hex(" ").upper()
        resp_hex = response_bytes.hex(" ").upper()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_frames (pump_address, request_hex, response_hex, valid, note, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pump_address, req_hex, resp_hex, 1 if valid else 0, note, stamp),
            )
            conn.execute(
                """
                DELETE FROM raw_frames
                WHERE id NOT IN (
                    SELECT id FROM raw_frames ORDER BY id DESC LIMIT ?
                )
                """,
                (_MAX_RAW_FRAMES,),
            )

    def record_completed_dispense(
        self,
        dispense: CompletedDispense,
        *,
        station_id: str,
        dispenser_id: str,
        tank_id: str | None,
    ) -> bool:
        """Атомарно сохраняет закрытую заправку в `dispenses` и ставит пакет в `outbox_queue`.

        Возвращает True, если запись новая, или False, если такой `external_txn_id` уже был записан.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        raw_meta = {
            "source": "aska_02_iskra_1_72",
            "pump_address": dispense.pump_address,
            "mode": dispense.mode,
            "preset_ml": dispense.preset_ml,
            "dispensed_ml": dispense.dispensed_ml,
            "price_kzt_per_liter": dispense.price_kzt_per_liter,
            "final_state_code": dispense.final_state_code,
            "error_code": dispense.error_code,
            "frame_hex": dispense.last_raw_frame_hex,
        }
        ingest_payload: dict[str, object] = {
            "station_id": station_id,
            "dispenser_id": dispenser_id,
            "volume_liters": dispense.volume_liters,
            "started_at": dispense.started_at.isoformat(),
            "finished_at": dispense.finished_at.isoformat(),
            "external_txn_id": dispense.external_txn_id,
            "raw_payload": json.dumps(raw_meta, ensure_ascii=False),
        }
        if tank_id:
            ingest_payload["tank_id"] = tank_id

        payload_json = json.dumps(ingest_payload, ensure_ascii=False)

        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO dispenses (
                        external_txn_id, pump_address, mode, preset_ml,
                        dispensed_ml, volume_liters, price_kzt_per_liter,
                        final_state_code, error_code, started_at, finished_at,
                        last_raw_frame_hex, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dispense.external_txn_id,
                        dispense.pump_address,
                        dispense.mode,
                        dispense.preset_ml,
                        dispense.dispensed_ml,
                        dispense.volume_liters,
                        dispense.price_kzt_per_liter,
                        dispense.final_state_code,
                        dispense.error_code,
                        dispense.started_at.isoformat(),
                        dispense.finished_at.isoformat(),
                        dispense.last_raw_frame_hex,
                        now_iso,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO outbox_queue (
                        external_txn_id, payload_json, status, attempts,
                        created_at, next_retry_at
                    ) VALUES (?, ?, 'pending', 0, ?, ?)
                    """,
                    (dispense.external_txn_id, payload_json, now_iso, now_iso),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def fetch_due_outbox(self, *, limit: int = 25, now: datetime | None = None) -> list[OutboxItem]:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, external_txn_id, payload_json, status, attempts,
                       last_error, created_at, next_retry_at
                FROM outbox_queue
                WHERE status IN ('pending', 'retry') AND next_retry_at <= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
        return [
            OutboxItem(
                id=int(row["id"]),
                external_txn_id=str(row["external_txn_id"]),
                payload_json=str(row["payload_json"]),
                status=str(row["status"]),
                attempts=int(row["attempts"]),
                last_error=row["last_error"],
                created_at=str(row["created_at"]),
                next_retry_at=str(row["next_retry_at"]),
            )
            for row in rows
        ]

    def mark_outbox_sent(self, external_txn_id: str, server_response: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE outbox_queue
                SET status = 'sent',
                    attempts = attempts + 1,
                    last_error = NULL,
                    server_response = ?,
                    sent_at = ?
                WHERE external_txn_id = ?
                """,
                (server_response, now_iso, external_txn_id),
            )

    def mark_outbox_batch_sent(self, items: list[tuple[str, str]]) -> None:
        """Атомарно помечает пачку записей как отправленные в 1 транзакции SQLite."""
        if not items:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                UPDATE outbox_queue
                SET status = 'sent',
                    attempts = attempts + 1,
                    last_error = NULL,
                    server_response = ?,
                    sent_at = ?
                WHERE external_txn_id = ?
                """,
                [(resp, now_iso, txn_id) for txn_id, resp in items],
            )

    def mark_outbox_failed(
        self,
        external_txn_id: str,
        error_text: str,
        *,
        now: datetime | None = None,
    ) -> None:
        base_now = now or datetime.now(timezone.utc)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM outbox_queue WHERE external_txn_id = ?",
                (external_txn_id,),
            ).fetchone()
            attempts = (int(row["attempts"]) if row else 0) + 1
            # Экспоненциальная задержка повтора: от 5 секунд до 5 минут
            backoff_sec = min(300, 5 * (2 ** min(attempts - 1, 6)))
            next_retry = (base_now + timedelta(seconds=backoff_sec)).isoformat()
            conn.execute(
                """
                UPDATE outbox_queue
                SET status = 'retry',
                    attempts = ?,
                    last_error = ?,
                    next_retry_at = ?
                WHERE external_txn_id = ?
                """,
                (attempts, error_text[:1000], next_retry, external_txn_id),
            )

    def list_dispenses(self, *, limit: int = 50) -> list[DispenseRow]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.external_txn_id, d.pump_address, d.mode,
                       d.preset_ml, d.dispensed_ml, d.volume_liters,
                       d.price_kzt_per_liter, d.final_state_code, d.error_code,
                       d.started_at, d.finished_at,
                       q.status AS queue_status
                FROM dispenses d
                LEFT JOIN outbox_queue q ON q.external_txn_id = d.external_txn_id
                ORDER BY d.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            DispenseRow(
                id=int(row["id"]),
                external_txn_id=str(row["external_txn_id"]),
                pump_address=int(row["pump_address"]),
                mode=str(row["mode"]),
                preset_ml=None if row["preset_ml"] is None else int(row["preset_ml"]),
                dispensed_ml=int(row["dispensed_ml"]),
                volume_liters=float(row["volume_liters"]),
                price_kzt_per_liter=float(row["price_kzt_per_liter"]),
                final_state_code=str(row["final_state_code"]),
                error_code=str(row["error_code"]),
                started_at=str(row["started_at"]),
                finished_at=str(row["finished_at"]),
                synced_to_vps=(row["queue_status"] == "sent"),
            )
            for row in rows
        ]

    def summary(self) -> dict[str, object]:
        with self._lock, self._connect() as conn:
            totals = conn.execute(
                """
                SELECT COUNT(*) AS count_dispenses,
                       COALESCE(SUM(dispensed_ml), 0) AS total_dispensed_ml,
                       COALESCE(SUM(volume_liters), 0.0) AS total_liters
                FROM dispenses
                """
            ).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) AS cnt FROM outbox_queue WHERE status IN ('pending', 'retry')"
            ).fetchone()
            sent = conn.execute(
                "SELECT COUNT(*) AS cnt FROM outbox_queue WHERE status = 'sent'"
            ).fetchone()
            pumps = conn.execute(
                "SELECT * FROM pump_live_state ORDER BY pump_address ASC"
            ).fetchall()
        return {
            "total_dispenses": int(totals["count_dispenses"]) if totals else 0,
            "total_dispensed_ml": int(totals["total_dispensed_ml"]) if totals else 0,
            "total_liters": round(float(totals["total_liters"]) if totals else 0.0, 3),
            "outbox_pending": int(pending["cnt"]) if pending else 0,
            "outbox_sent": int(sent["cnt"]) if sent else 0,
            "pumps": [dict(row) for row in pumps],
        }
