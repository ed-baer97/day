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
        vps_base_url="http://93.171.232.47",
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
