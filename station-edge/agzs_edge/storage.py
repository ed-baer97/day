"""Локальная база данных станции (SQLite в режиме WAL).

Хранит:
  1. `dispenses`      — закрытые заправки с полем `dispensed_ml`, ценой, режимом и временем.
  2. `outbox_queue`   — локальная очередь исходящих пакетов на центральный VPS (гарантия доставки без дублей).
  3. `pump_live_state`— последнее известное состояние каждой колонки (для мониторинга на станции).
  4. `raw_frames`     — диагностический кольцевой буфер сырых кадров/ошибок АСКА-02.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import overload

from agzs_edge.iskra import (
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_REMAINDER,
    IskraTelemetryFrame,
)
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

    @property
    def amount_kzt(self) -> float:
        return round(self.volume_liters * self.price_kzt_per_liter, 2)


@overload
def parse_iso_datetime(raw: datetime) -> datetime: ...


@overload
def parse_iso_datetime(raw: str) -> datetime | None: ...


def parse_iso_datetime(raw: str | datetime) -> datetime | None:
    """Приводит ISO-строку или datetime к timezone-aware UTC (или None для некорректной строки)."""
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=timezone.utc) if raw.tzinfo is None else raw.astimezone(timezone.utc)
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_to_dispense(row: sqlite3.Row) -> DispenseRow:
    return DispenseRow(
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


_SELECT_DISPENSES_BASE = """
SELECT d.id, d.external_txn_id, d.pump_address, d.mode,
       d.preset_ml, d.dispensed_ml, d.volume_liters,
       d.price_kzt_per_liter, d.final_state_code, d.error_code,
       d.started_at, d.finished_at,
       q.status AS queue_status
FROM dispenses d
LEFT JOIN outbox_queue q ON q.external_txn_id = d.external_txn_id
"""


class EdgeDatabase:
    """Потокобезопасное хранилище SQLite для станционного ПК (Windows / Linux)."""

    def __init__(self, db_path: Path | str, *, read_only: bool = False) -> None:
        self.db_path = Path(db_path)
        self._read_only = read_only
        self._lock = threading.Lock()
        if not self._read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        if self._read_only:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=5000")
        else:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextlib.contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            if self._read_only:
                yield conn
            else:
                with conn:
                    yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._session() as conn:
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
                    updated_at TEXT NOT NULL,
                    recorded_stop_volume_ml INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS counter_audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pump_address INTEGER NOT NULL,
                    total_counter_liters REAL NOT NULL,
                    prev_counter_liters REAL,
                    counter_delta_liters REAL,
                    db_dispenses_liters REAL NOT NULL,
                    discrepancy_liters REAL,
                    recorded_at TEXT NOT NULL
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

                CREATE INDEX IF NOT EXISTS ix_dispenses_finished_at
                    ON dispenses(finished_at);

                CREATE INDEX IF NOT EXISTS ix_outbox_status_retry
                    ON outbox_queue(status, next_retry_at);
                """
            )
            cols = {
                str(r["name"])
                for r in conn.execute("PRAGMA table_info(pump_live_state)").fetchall()
            }
            if "recorded_stop_volume_ml" not in cols:
                conn.execute(
                    "ALTER TABLE pump_live_state ADD COLUMN recorded_stop_volume_ml INTEGER NOT NULL DEFAULT 0"
                )

    def update_live_state(self, frame: IskraTelemetryFrame, *, observed_at: datetime | None = None) -> None:
        stamp = (observed_at or datetime.now(timezone.utc)).isoformat()
        is_idle = 1 if frame.state_code == STATE_IDLE else 0
        is_disp = 1 if frame.is_dispensing else 0
        with self._lock, self._session() as conn:
            conn.execute(
                """
                INSERT INTO pump_live_state (
                    pump_address, state_code, state_name, error_code,
                    price_kzt_per_liter, volume_ml, raw_hex, updated_at,
                    recorded_stop_volume_ml
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(pump_address) DO UPDATE SET
                    state_code = excluded.state_code,
                    state_name = excluded.state_name,
                    error_code = excluded.error_code,
                    price_kzt_per_liter = CASE
                        WHEN excluded.price_kzt_per_liter > 0 THEN excluded.price_kzt_per_liter
                        ELSE pump_live_state.price_kzt_per_liter
                    END,
                    volume_ml = excluded.volume_ml,
                    raw_hex = excluded.raw_hex,
                    updated_at = excluded.updated_at,
                    recorded_stop_volume_ml = CASE
                        WHEN ? THEN 0
                        WHEN ? AND excluded.volume_ml < pump_live_state.recorded_stop_volume_ml THEN 0
                        ELSE pump_live_state.recorded_stop_volume_ml
                    END
                """,
                (
                    frame.address,
                    frame.state_code,
                    frame.state_name,
                    frame.error_code,
                    frame.price_kzt_per_liter,
                    frame.effective_volume_ml,
                    frame.raw_hex,
                    stamp,
                    is_idle,
                    is_disp,
                ),
            )

    def mark_stop_volume_recorded(self, pump_address: int, volume_ml: int) -> None:
        """Запоминает зафиксированный в БД объём текущего останова до сброса в '05'."""
        with self._lock, self._session() as conn:
            conn.execute(
                "UPDATE pump_live_state SET recorded_stop_volume_ml = ? WHERE pump_address = ?",
                (max(0, int(volume_ml)), pump_address),
            )

    def get_recorded_stop_volumes(self) -> dict[int, int]:
        """Возвращает карту `{pump_address: recorded_stop_volume_ml}` для защиты от дублей после рестарта."""
        if self._read_only and not self.db_path.is_file():
            return {}
        try:
            with self._lock, self._session() as conn:
                rows = conn.execute(
                    "SELECT pump_address, recorded_stop_volume_ml FROM pump_live_state WHERE recorded_stop_volume_ml > 0"
                ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {int(row["pump_address"]): int(row["recorded_stop_volume_ml"]) for row in rows}

    def record_counter_audit(
        self,
        pump_address: int,
        total_counter_liters: float,
        *,
        observed_at: datetime | None = None,
    ) -> tuple[float | None, float | None]:
        """Сохраняет сверку суммарного счётчика (0.11) с закрытыми заправками в SQLite."""
        stamp_dt = parse_iso_datetime(observed_at or datetime.now(timezone.utc))
        stamp_iso = stamp_dt.isoformat()
        with self._lock, self._session() as conn:
            prev = conn.execute(
                "SELECT total_counter_liters, recorded_at FROM counter_audits WHERE pump_address = ? ORDER BY id DESC LIMIT 1",
                (pump_address,),
            ).fetchone()

            if prev is None:
                prev_val: float | None = None
                counter_delta: float | None = None
                rows = conn.execute(
                    "SELECT COALESCE(SUM(volume_liters), 0.0) AS total_vol FROM dispenses WHERE pump_address = ?",
                    (pump_address,),
                ).fetchone()
                db_liters = round(float(rows["total_vol"]) if rows else 0.0, 3)
                discrepancy: float | None = None
            else:
                prev_val = float(prev["total_counter_liters"])
                prev_dt = parse_iso_datetime(str(prev["recorded_at"]))
                counter_delta = round(total_counter_liters - prev_val, 3)
                disp_rows = conn.execute(
                    "SELECT finished_at, volume_liters FROM dispenses WHERE pump_address = ?",
                    (pump_address,),
                ).fetchall()
                acc = 0.0
                for d_row in disp_rows:
                    fin_dt = parse_iso_datetime(str(d_row["finished_at"]))
                    if fin_dt is None:
                        continue
                    if prev_dt is not None and fin_dt <= prev_dt:
                        continue
                    if fin_dt > stamp_dt:
                        continue
                    acc += float(d_row["volume_liters"])
                db_liters = round(acc, 3)
                discrepancy = round(counter_delta - db_liters, 3)

            conn.execute(
                """
                INSERT INTO counter_audits (
                    pump_address, total_counter_liters, prev_counter_liters,
                    counter_delta_liters, db_dispenses_liters, discrepancy_liters, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pump_address,
                    round(float(total_counter_liters), 3),
                    prev_val,
                    counter_delta,
                    db_liters,
                    discrepancy,
                    stamp_iso,
                ),
            )
            return counter_delta, discrepancy

    def mark_no_response(self, pump_address: int, *, observed_at: datetime | None = None) -> None:
        """Помечает колонку как NO_RESPONSE без постановки фиктивного объёма в outbox/VPS.

        Не затирает volume_ml предыдущего успешного кадра: обновляет только статус связи и время.
        """
        stamp = (observed_at or datetime.now(timezone.utc)).isoformat()
        with self._lock, self._session() as conn:
            conn.execute(
                """
                INSERT INTO pump_live_state (
                    pump_address, state_code, state_name, error_code,
                    price_kzt_per_liter, volume_ml, raw_hex, updated_at
                ) VALUES (?, 'NR', 'NO_RESPONSE', '00', 0, 0, '', ?)
                ON CONFLICT(pump_address) DO UPDATE SET
                    state_code = 'NR',
                    state_name = 'NO_RESPONSE',
                    updated_at = excluded.updated_at
                """,
                (pump_address, stamp),
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
        with self._lock, self._session() as conn:
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
        now: datetime | None = None,
    ) -> bool:
        """Атомарно сохраняет закрытую заправку в `dispenses` и ставит пакет в `outbox_queue`.

        Возвращает True, если запись новая, или False, если такой `external_txn_id` уже был записан.
        """
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
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

        with self._lock, self._session() as conn:
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
        with self._lock, self._session() as conn:
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
        with self._lock, self._session() as conn:
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
        with self._lock, self._session() as conn:
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
        with self._lock, self._session() as conn:
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

    @staticmethod
    def _empty_summary() -> dict[str, object]:
        return {
            "total_dispenses": 0,
            "total_dispensed_ml": 0,
            "total_liters": 0.0,
            "outbox_pending": 0,
            "outbox_sent": 0,
            "pumps": [],
        }

    def list_dispenses(self, *, limit: int = 50) -> list[DispenseRow]:
        if self._read_only and not self.db_path.is_file():
            return []
        try:
            with self._lock, self._session() as conn:
                rows = conn.execute(
                    f"{_SELECT_DISPENSES_BASE}\nORDER BY d.id DESC\nLIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if self._read_only and "no such table" in str(exc).lower():
                return []
            raise
        return [_row_to_dispense(row) for row in rows]

    def list_dispenses_between(
        self,
        since: datetime,
        until: datetime | None = None,
    ) -> list[DispenseRow]:
        """Возвращает закрытые заправки в интервале [since, until), от новых к старым."""
        if self._read_only and not self.db_path.is_file():
            return []
        since_utc = parse_iso_datetime(since)
        until_utc = parse_iso_datetime(until) if until is not None else None
        since_sql = (since_utc - timedelta(seconds=1)).isoformat()
        where_clauses = ["datetime(d.finished_at) >= datetime(?)"]
        params: list[object] = [since_sql]
        if until_utc is not None:
            until_sql = (until_utc + timedelta(seconds=1)).isoformat()
            where_clauses.append("datetime(d.finished_at) <= datetime(?)")
            params.append(until_sql)
        where_sql = " AND ".join(where_clauses)
        try:
            with self._lock, self._session() as conn:
                rows = conn.execute(
                    f"{_SELECT_DISPENSES_BASE}\nWHERE {where_sql}\nORDER BY d.id DESC",
                    params,
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if self._read_only and "no such table" in str(exc).lower():
                return []
            raise

        result: list[DispenseRow] = []
        for row in rows:
            finished_utc = parse_iso_datetime(str(row["finished_at"]))
            if finished_utc is None:
                continue
            if finished_utc < since_utc:
                continue
            if until_utc is not None and finished_utc >= until_utc:
                continue
            result.append(_row_to_dispense(row))
        return result

    def summary(self) -> dict[str, object]:
        if self._read_only and not self.db_path.is_file():
            return self._empty_summary()
        try:
            with self._lock, self._session() as conn:
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
        except sqlite3.OperationalError as exc:
            if self._read_only and "no such table" in str(exc).lower():
                return self._empty_summary()
            raise
        return {
            "total_dispenses": int(totals["count_dispenses"]) if totals else 0,
            "total_dispensed_ml": int(totals["total_dispensed_ml"]) if totals else 0,
            "total_liters": round(float(totals["total_liters"]) if totals else 0.0, 3),
            "outbox_pending": int(pending["cnt"]) if pending else 0,
            "outbox_sent": int(sent["cnt"]) if sent else 0,
            "pumps": [dict(row) for row in pumps],
        }

    def active_dispensing_pumps(
        self,
        *,
        max_age_sec: float = 30.0,
        now: datetime | None = None,
    ) -> list[int]:
        """Возвращает отсортированный список адресов колонок, на которых идёт налив или набрана доза."""
        if self._read_only and not self.db_path.is_file():
            return []
        active_states = (STATE_DOSE_SET, STATE_REMAINDER, STATE_DISPENSING)
        try:
            with self._lock, self._session() as conn:
                rows = conn.execute(
                    """
                    SELECT pump_address, updated_at
                    FROM pump_live_state
                    WHERE state_code IN (?, ?, ?)
                    ORDER BY pump_address ASC
                    """,
                    active_states,
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if self._read_only and "no such table" in str(exc).lower():
                return []
            raise

        if max_age_sec <= 0:
            return [int(row["pump_address"]) for row in rows]

        ref_now = parse_iso_datetime(now or datetime.now(timezone.utc))
        cutoff = ref_now - timedelta(seconds=max_age_sec)
        active: list[int] = []
        for row in rows:
            updated = parse_iso_datetime(str(row["updated_at"]))
            if updated is not None and updated >= cutoff:
                active.append(int(row["pump_address"]))
        return active

    def seconds_since_last_dispense(self, *, now: datetime | None = None) -> float | None:
        """Возвращает количество секунд с момента последней закрытой заправки (или None, если их ещё не было)."""
        if self._read_only and not self.db_path.is_file():
            return None
        try:
            with self._lock, self._session() as conn:
                row = conn.execute(
                    "SELECT finished_at FROM dispenses ORDER BY id DESC LIMIT 1"
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if self._read_only and "no such table" in str(exc).lower():
                return None
            raise
        if row is None:
            return None
        finished_utc = parse_iso_datetime(str(row["finished_at"]))
        if finished_utc is None:
            return None
        ref_now = parse_iso_datetime(now or datetime.now(timezone.utc))
        return max(0.0, (ref_now - finished_utc).total_seconds())

    def is_station_idle_for_update(
        self,
        *,
        min_quiet_sec: float = 60.0,
        active_max_age_sec: float = 30.0,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """Проверяет, находится ли АГЗС в простое и безопасна ли для обновления."""
        active = self.active_dispensing_pumps(max_age_sec=active_max_age_sec, now=now)
        if active:
            return False, f"идёт налив или задана доза на колонках {active}"
        if min_quiet_sec > 0:
            elapsed = self.seconds_since_last_dispense(now=now)
            if elapsed is not None and elapsed < min_quiet_sec:
                return (
                    False,
                    f"после последнего налива прошло {elapsed:.0f} с (нужно {min_quiet_sec:.0f} с простоя)",
                )
        return True, "станция в простое, колонки свободны"
