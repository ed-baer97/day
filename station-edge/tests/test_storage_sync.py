"""Тесты локальной БД SQLite, очереди outbox и идемпотентной синхронизации с VPS."""

import json
from datetime import datetime, timezone
from pathlib import Path

from agzs_edge.config import EdgeSettings
from agzs_edge.service import StationEdgeService
from agzs_edge.storage import EdgeDatabase
from agzs_edge.sync import OutboxSyncWorker, VpsSendResult
from agzs_edge.tracker import CompletedDispense


def test_sqlite_records_dispense_and_prevents_duplicates(tmp_path: Path) -> None:
    db = EdgeDatabase(tmp_path / "edge.db")
    disp = CompletedDispense(
        external_txn_id="aska02-akt12-p1-1000-1",
        pump_address=1,
        mode="dose",
        preset_ml=20000,
        dispensed_ml=7500,
        volume_liters=7.5,
        price_kzt_per_liter=100.0,
        final_state_code="03",
        error_code="00",
        started_at=datetime(2026, 11, 11, 8, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 11, 11, 8, 1, 0, tzinfo=timezone.utc),
        last_raw_frame_hex="01 31 34",
    )

    first = db.record_completed_dispense(
        disp,
        station_id="a2222222-2222-2222-2222-222222222201",
        dispenser_id="d2222222-2222-2222-2222-222222222201",
        tank_id="b2222222-2222-2222-2222-222222222201",
    )
    assert first is True

    # Повтор с тем же external_txn_id не создаёт вторую заправку
    second = db.record_completed_dispense(
        disp,
        station_id="a2222222-2222-2222-2222-222222222201",
        dispenser_id="d2222222-2222-2222-2222-222222222201",
        tank_id="b2222222-2222-2222-2222-222222222201",
    )
    assert second is False

    summary = db.summary()
    assert summary["total_dispenses"] == 1
    assert summary["total_dispensed_ml"] == 7500
    assert summary["total_liters"] == 7.5
    assert summary["outbox_pending"] == 1


def test_outbox_retry_and_duplicate_handling(tmp_path: Path) -> None:
    db = EdgeDatabase(tmp_path / "edge.db")
    t0 = datetime(2026, 11, 11, 8, 0, 0, tzinfo=timezone.utc)
    disp = CompletedDispense(
        external_txn_id="aska02-akt12-p2-2000-1",
        pump_address=2,
        mode="full_tank",
        preset_ml=None,
        dispensed_ml=14200,
        volume_liters=14.2,
        price_kzt_per_liter=105.0,
        final_state_code="04",
        error_code="00",
        started_at=t0,
        finished_at=t0,
        last_raw_frame_hex="01 32 34",
    )
    db.record_completed_dispense(
        disp,
        station_id="a2222222-2222-2222-2222-222222222201",
        dispenser_id="d2222222-2222-2222-2222-222222222202",
        tank_id="b2222222-2222-2222-2222-222222222201",
        now=t0,
    )

    calls: list[dict] = []

    def fake_sender_offline_then_online(url: str, token: str, payload_json: str) -> VpsSendResult:
        calls.append({"url": url, "token": token, "payload": json.loads(payload_json)})
        if len(calls) == 1:
            return VpsSendResult(ok=False, status_code=0, error_text="Connection timed out")
        return VpsSendResult(
            ok=True,
            duplicate=True,
            status_code=200,
            response_text='{"accepted":true,"message":"duplicate","duplicate":true}',
        )

    worker = OutboxSyncWorker(
        db,
        vps_base_url="https://vps.example.com",
        device_token="secret-tank-token",
        sender=fake_sender_offline_then_online,
    )

    # 1-я попытка: нет интернета -> остаётся в очереди со статусом retry
    sent, failed = worker.flush_due(now=t0)
    assert sent == 0
    assert failed == 1
    assert db.summary()["outbox_pending"] == 1

    # 2-я попытка спустя 10 секунд: интернет появился, сервер вернул duplicate=true -> помечено sent
    from datetime import timedelta

    sent, failed = worker.flush_due(now=t0 + timedelta(seconds=10))
    assert sent == 1
    assert failed == 0
    assert db.summary()["outbox_pending"] == 0
    assert db.summary()["outbox_sent"] == 1
    assert calls[-1]["payload"]["volume_liters"] == 14.2
    assert calls[-1]["payload"]["external_txn_id"] == "aska02-akt12-p2-2000-1"


def test_full_emulator_service_cycle(tmp_path: Path) -> None:
    settings = EdgeSettings(
        source_mode="emulator",
        pump_addresses=(1, 2),
        poll_interval_sec=0.0,
        db_path=tmp_path / "station.db",
        sync_enabled=True,
        sync_interval_sec=0.0,
        device_token="tok-123",
    )
    sent_payloads: list[dict] = []

    db = EdgeDatabase(settings.db_path)
    worker = OutboxSyncWorker(
        db,
        vps_base_url=settings.vps_base_url,
        device_token=settings.device_token,
        sender=lambda url, tok, body: (
            sent_payloads.append(json.loads(body))
            or VpsSendResult(ok=True, response_text='{"accepted":true}')
        ),
    )
    service = StationEdgeService(settings, db=db, sync_worker=worker)
    service.serve(max_cycles=8)

    info = db.summary()
    assert info["total_dispenses"] == 2  # колонка 1 (доза 20 л) и колонка 2 («до полного» 12.75 л)
    assert info["total_dispensed_ml"] == 20000 + 12750
    assert info["outbox_sent"] == 2
    assert info["outbox_pending"] == 0
    assert len(sent_payloads) == 2


def test_bulk_outbox_sync(tmp_path: Path) -> None:
    db = EdgeDatabase(tmp_path / "edge.db")
    t0 = datetime(2026, 11, 11, 9, 0, 0, tzinfo=timezone.utc)

    for i in range(1, 4):
        disp = CompletedDispense(
            external_txn_id=f"bulk-txn-{i}",
            pump_address=i,
            mode="dose",
            preset_ml=10000 * i,
            dispensed_ml=10000 * i,
            volume_liters=10.0 * i,
            price_kzt_per_liter=100.0,
            final_state_code="03",
            error_code="00",
            started_at=t0,
            finished_at=t0,
            last_raw_frame_hex="01 31 34",
        )
        db.record_completed_dispense(
            disp,
            station_id="a2222222-2222-2222-2222-222222222201",
            dispenser_id=f"d2222222-2222-2222-2222-22222222220{i}",
            tank_id="b2222222-2222-2222-2222-222222222201",
            now=t0,
        )

    batch_calls: list[list[dict]] = []

    def fake_batch_sender(url: str, token: str, items: list[dict]) -> VpsSendResult:
        batch_calls.append(items)
        return VpsSendResult(
            ok=True,
            status_code=200,
            response_text='{"accepted_count": 3, "duplicates_count": 0}',
        )

    worker = OutboxSyncWorker(
        db,
        vps_base_url="https://vps.example.com",
        device_token="secret-token",
        batch_sender=fake_batch_sender,
    )

    sent, failed = worker.flush_due(limit=10, now=t0)
    assert sent == 3
    assert failed == 0
    assert len(batch_calls) == 1
    assert len(batch_calls[0]) == 3
    assert db.summary()["outbox_sent"] == 3
    assert db.summary()["outbox_pending"] == 0


def test_bulk_outbox_sync_chunks_over_200_and_fallbacks_on_batch_error(tmp_path: Path) -> None:
    """Очередь > 200 записей режется на чанки <= MAX_BATCH_SIZE; ошибка чанка откатывает на поштучную отправку."""
    from datetime import timedelta

    from agzs_edge.sync import MAX_BATCH_SIZE

    db = EdgeDatabase(tmp_path / "chunk.db")
    t0 = datetime(2026, 11, 18, 8, 0, 0, tzinfo=timezone.utc)
    total_items = MAX_BATCH_SIZE + 5

    for i in range(total_items):
        disp = CompletedDispense(
            external_txn_id=f"chunk-txn-{i}",
            pump_address=1,
            mode="dose",
            preset_ml=5000,
            dispensed_ml=5000,
            volume_liters=5.0,
            price_kzt_per_liter=72.0,
            final_state_code="07",
            error_code="00",
            started_at=t0 + timedelta(seconds=i),
            finished_at=t0 + timedelta(seconds=i),
            last_raw_frame_hex="01 30 31",
        )
        db.record_completed_dispense(
            disp,
            station_id="a2222222-2222-2222-2222-222222222201",
            dispenser_id="d2222222-2222-2222-2222-222222222201",
            tank_id="b2222222-2222-2222-2222-222222222201",
            now=t0,
        )

    batch_sizes: list[int] = []
    single_txns: list[str] = []

    def batch_sender(url: str, token: str, items: list[dict]) -> VpsSendResult:
        batch_sizes.append(len(items))
        if len(items) == MAX_BATCH_SIZE:
            return VpsSendResult(ok=True, status_code=200, response_text='{"accepted_count": 200}')
        return VpsSendResult(ok=False, status_code=500, error_text="HTTP 500: temporary")

    def single_sender(url: str, token: str, payload_json: str) -> VpsSendResult:
        txn = json.loads(payload_json)["external_txn_id"]
        single_txns.append(txn)
        if txn.endswith("-204"):
            return VpsSendResult(ok=False, status_code=503, error_text="retry me")
        return VpsSendResult(ok=True, status_code=200, response_text='{"accepted":true}')

    worker = OutboxSyncWorker(
        db,
        vps_base_url="https://vps.example.com",
        device_token="tok",
        sender=single_sender,
        batch_sender=batch_sender,
    )
    sent, failed = worker.flush_due(limit=250, now=t0)
    assert batch_sizes == [200, 5]
    assert len(single_txns) == 5
    assert sent == 204
    assert failed == 1
    assert db.summary()["outbox_sent"] == 204
    assert db.summary()["outbox_pending"] == 1


def test_http_vps_sync_helpers(monkeypatch) -> None:
    """Проверка строгих ACK, TLS-запрета для открытого http:// и probe_vps_link."""
    import io
    import urllib.error

    from agzs_edge.sync import post_dispense_to_vps, post_dispenses_batch_to_vps, probe_vps_link

    # 1. Пустой tank_id -> ошибка без HTTP-вызова
    empty_probe = probe_vps_link("https://example.com", "tok", "")
    assert empty_probe.ok is False

    # 2. Открытый HTTP на публичный хост запрещён по умолчанию (без allow_insecure_http=True)
    insecure_res = post_dispense_to_vps("http://93.171.232.47", "tok", '{"external_txn_id":"1"}')
    assert insecure_res.ok is False and insecure_res.status_code == 0 and "https://" in insecure_res.error_text.lower()

    class _FakeResp:
        def __init__(self, body: str, status: int = 200) -> None:
            self._body = body.encode("utf-8")
            self.status = status

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return

    captured_headers: dict[str, str] = {}

    def _ok_urlopen(req, timeout=10.0):
        captured_headers.update(dict(req.header_items()))
        if req.full_url.endswith("/dispenses/batch"):
            return _FakeResp('{"accepted_count": 1, "duplicates_count": 0, "results": [{"accepted": true}]}')
        if "/tanks/" in req.full_url:
            return _FakeResp('{"actual_remainder_liters": 5000}')
        return _FakeResp('{"accepted": true, "duplicate": false}')

    monkeypatch.setattr("urllib.request.urlopen", _ok_urlopen)
    res_probe = probe_vps_link("https://example.com", "tok-1", "tank-1")
    assert res_probe.ok is True
    assert captured_headers.get("X-device-token") == "tok-1"

    res_single = post_dispense_to_vps("https://example.com", "tok-1", '{"external_txn_id":"1"}')
    assert res_single.ok is True and res_single.duplicate is False

    # http://127.0.0.1 и явный allow_insecure_http=True разрешены
    assert post_dispense_to_vps("http://127.0.0.1:8000", "tok-1", '{"external_txn_id":"1"}').ok is True
    assert (
        post_dispense_to_vps(
            "http://example.com", "tok-1", '{"external_txn_id":"1"}', allow_insecure_http=True
        ).ok
        is True
    )

    res_batch = post_dispenses_batch_to_vps("https://example.com", "tok-1", [{"external_txn_id": "1"}])
    assert res_batch.ok is True

    # 3. HTTP 200 без валидного JSON ACK (HTML прокси / пустое тело / нет accepted=true / неверный batch count) -> НЕ ок!
    for bad_body in ("", "<html>502 Bad Gateway</html>", "{}", '{"duplicate": false}', '{"accepted": false}'):
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=10.0, b=bad_body: _FakeResp(b))
        res_bad = post_dispense_to_vps("https://example.com", "tok", "{}")
        assert res_bad.ok is False, f"unexpected ok for body={bad_body!r}"

    for bad_batch in (
        "",
        "<html>proxy</html>",
        '{"accepted_count": 0, "duplicates_count": 0}',
        '{"accepted_count": 2, "duplicates_count": 0}',
        '{"accepted_count": 1, "duplicates_count": 0, "results": [{"accepted": false}]}',
    ):
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=10.0, b=bad_batch: _FakeResp(b))
        assert post_dispenses_batch_to_vps("https://example.com", "tok", [{"external_txn_id": "1"}]).ok is False

    # 4. HTTPError и сетевой сбой
    def _http_err(req, timeout=10.0):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"invalid token")
        )

    monkeypatch.setattr("urllib.request.urlopen", _http_err)
    res_401 = post_dispense_to_vps("https://example.com", "bad", "{}")
    assert res_401.ok is False and res_401.status_code == 401 and "invalid token" in res_401.error_text

    def _net_err(req, timeout=10.0):
        raise OSError("network unreachable")

    monkeypatch.setattr("urllib.request.urlopen", _net_err)
    res_net = post_dispense_to_vps("https://example.com", "tok", "{}")
    assert res_net.ok is False and res_net.status_code == 0


def test_storage_read_only_empty_sqlite_and_parse_iso_datetime(tmp_path: Path) -> None:
    """read_only на пустом SQLite без таблиц, amount_kzt, mark_outbox_batch_sent([]) и parse_iso_datetime."""
    import sqlite3

    from agzs_edge.storage import DispenseRow, parse_iso_datetime

    raw_db = tmp_path / "empty_tables.db"
    sqlite3.connect(raw_db).close()

    ro = EdgeDatabase(raw_db, read_only=True)
    assert ro.list_dispenses() == []
    assert ro.list_dispenses_between(datetime(2026, 1, 1, tzinfo=timezone.utc)) == []
    assert ro.summary()["total_dispenses"] == 0

    rw = EdgeDatabase(tmp_path / "rw.db")
    rw.mark_outbox_batch_sent([])

    row = DispenseRow(
        id=1,
        external_txn_id="t1",
        pump_address=1,
        mode="dose",
        preset_ml=10000,
        dispensed_ml=10000,
        volume_liters=10.0,
        price_kzt_per_liter=72.5,
        final_state_code="07",
        error_code="00",
        started_at="2026-11-18T10:00:00Z",
        finished_at="2026-11-18T10:01:00Z",
        synced_to_vps=True,
    )
    assert row.amount_kzt == 725.0
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime("not-a-date") is None
    assert parse_iso_datetime("2026-11-18T10:00:00Z") == datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
    assert parse_iso_datetime("2026-11-18T10:00:00") == datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
    assert parse_iso_datetime("2026-11-18T15:00:00+05:00") == datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
    assert parse_iso_datetime(datetime(2026, 11, 18, 10, 0, 0)) == datetime(
        2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc
    )


def test_outbox_dead_letter_on_422_and_corrupted_json(tmp_path: Path) -> None:
    """HTTP 422 и битый JSON переводят запись outbox в status='failed' и не блокируют пакеты."""
    import sqlite3

    db_path = tmp_path / "dead_letter.db"
    db = EdgeDatabase(db_path)
    t0 = datetime(2026, 11, 22, 9, 0, 0, tzinfo=timezone.utc)

    for idx in range(1, 4):
        disp = CompletedDispense(
            external_txn_id=f"dl-txn-{idx}",
            pump_address=1,
            mode="dose",
            preset_ml=5000,
            dispensed_ml=5000,
            volume_liters=5.0,
            price_kzt_per_liter=72.0,
            final_state_code="07",
            error_code="00",
            started_at=t0,
            finished_at=t0,
            last_raw_frame_hex="01 30 31",
        )
        db.record_completed_dispense(
            disp,
            station_id="a2222222-2222-2222-2222-222222222201",
            dispenser_id="d2222222-2222-2222-2222-222222222201",
            tank_id="b2222222-2222-2222-2222-222222222201",
            now=t0,
        )

    # Повреждаем JSON у первой записи
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE outbox_queue SET payload_json = '{broken' WHERE external_txn_id = 'dl-txn-1'")
    conn.commit()
    conn.close()

    batch_calls: list[list[str]] = []

    def _batch_sender(_url: str, _tok: str, items: list[dict]) -> VpsSendResult:
        batch_calls.append([str(it["external_txn_id"]) for it in items])
        return VpsSendResult(ok=False, status_code=422, error_text="HTTP 422: batch invalid")

    def _single_sender(_url: str, _tok: str, payload_json: str) -> VpsSendResult:
        txn = json.loads(payload_json)["external_txn_id"]
        if txn == "dl-txn-2":
            return VpsSendResult(ok=False, status_code=422, error_text="HTTP 422: bad field")
        return VpsSendResult(ok=True, status_code=200, response_text='{"accepted":true}')

    worker = OutboxSyncWorker(
        db,
        vps_base_url="https://vps.example.com",
        device_token="tok",
        sender=_single_sender,
        batch_sender=_batch_sender,
    )
    sent, failed = worker.flush_due(limit=10, now=t0)
    assert batch_calls == [["dl-txn-2", "dl-txn-3"]]
    assert sent == 1
    assert failed == 2
    assert db.fetch_due_outbox(limit=10, now=t0) == []

    conn = sqlite3.connect(db_path)
    statuses = dict(conn.execute("SELECT external_txn_id, status FROM outbox_queue").fetchall())
    conn.close()
    assert statuses == {
        "dl-txn-1": "failed",
        "dl-txn-2": "failed",
        "dl-txn-3": "sent",
    }


def test_outbox_401_stops_retry_storm_without_losing_sales_and_requeues(tmp_path: Path) -> None:
    """При 401/403 очередь переводится в auth_blocked одним шагом и восстанавливается после смены токена."""
    import sqlite3

    db_path = tmp_path / "auth_blocked.db"
    db = EdgeDatabase(db_path)
    t0 = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)

    for idx in range(1, 4):
        disp = CompletedDispense(
            external_txn_id=f"auth-txn-{idx}",
            pump_address=1,
            mode="dose",
            preset_ml=5000,
            dispensed_ml=5000,
            volume_liters=5.0,
            price_kzt_per_liter=72.0,
            final_state_code="07",
            error_code="00",
            started_at=t0,
            finished_at=t0,
            last_raw_frame_hex="01 30 31",
        )
        db.record_completed_dispense(
            disp,
            station_id="a2222222-2222-2222-2222-222222222201",
            dispenser_id="d2222222-2222-2222-2222-222222222201",
            tank_id="b2222222-2222-2222-2222-222222222201",
            now=t0,
        )

    single_calls = 0

    def _single_should_not_run(_url: str, _tok: str, _payload: str) -> VpsSendResult:
        nonlocal single_calls
        single_calls += 1
        return VpsSendResult(ok=True)

    worker = OutboxSyncWorker(
        db,
        vps_base_url="https://vps.example.com",
        device_token="rotated-old-token",
        sender=_single_should_not_run,
        batch_sender=lambda _u, _t, _items: VpsSendResult(
            ok=False, status_code=401, error_text="HTTP 401: invalid token"
        ),
    )
    sent, failed = worker.flush_due(limit=10, now=t0)
    assert sent == 0
    assert failed == 3
    assert single_calls == 0  # поштучного перебора не было
    assert db.fetch_due_outbox(limit=10, now=t0) == []
    info = db.summary()
    assert info["outbox_auth_blocked"] == 3
    assert info["outbox_pending"] == 0

    # После смены токена requeue_auth_blocked возвращает все 3 продажи в работу
    assert db.requeue_auth_blocked(now=t0) == 3
    ok_worker = OutboxSyncWorker(
        db,
        vps_base_url="https://vps.example.com",
        device_token="new-token",
        batch_sender=lambda _u, _t, items: VpsSendResult(
            ok=True, status_code=200, response_text='{"accepted_count":3,"duplicates_count":0}'
        ),
    )
    sent2, failed2 = ok_worker.flush_due(limit=10, now=t0)
    assert sent2 == 3
    assert failed2 == 0
    conn = sqlite3.connect(db_path)
    statuses = dict(conn.execute("SELECT external_txn_id, status FROM outbox_queue").fetchall())
    conn.close()
    assert statuses == {"auth-txn-1": "sent", "auth-txn-2": "sent", "auth-txn-3": "sent"}


