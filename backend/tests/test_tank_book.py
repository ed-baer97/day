"""Модульные тесты единого доменного ядра книги резервуара (app.domain.tank_book)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.tank_book import (
    apply_dispense_volume,
    apply_level_reading,
    apply_receipt_volume,
    build_ingest_ack,
    build_tank_ingest_state,
    recompute_tank_book,
    summarize_station_tanks,
)
from app.schemas.ingest import DispenseIngest, LevelIngest
from app.schemas.station import TankOut
from app.services import account, device_ingest
from app.services.calibration import LevelCalibration
from app.services.device_ingest import TankBook


def test_tank_book_lifecycle_and_recompute():
    station_id = uuid4()
    tank_id = uuid4()
    book = TankBook(station_id=station_id, tank_id=tank_id)

    # До первого уровня отпуски и приёмки уходят в pending_*
    apply_dispense_volume(book, 120.0)
    apply_receipt_volume(book, 500.0)
    assert book.opening_liters is None
    assert book.pending_dispense_liters == 120.0
    assert book.pending_receipt_liters == 500.0
    calc, delta, status = recompute_tank_book(book)
    assert calc is None
    assert delta is None
    assert status == "unknown"

    # Первое показание уровня задаёт старт книги (opening_liters)
    now = datetime.now(timezone.utc)
    changed, liters, fill = apply_level_reading(
        book,
        LevelIngest(
            station_id=station_id,
            tank_id=tank_id,
            actual_remainder_liters=10000.0,
            recorded_at=now,
            source_event_id="open-1",
        ),
        calibration=None,
        capacity_liters=20000.0,
        heard_at=now,
    )
    assert changed is True
    assert liters == 10000.0
    assert fill == 50.0
    assert book.opening_liters == 10000.0
    assert book.calculated_remainder_liters == 10000.0
    assert book.balance_status == "ok"

    # Отпуск и приёмка после старта двигают расчётный остаток
    apply_receipt_volume(book, 2000.0)
    apply_dispense_volume(book, 500.0)
    ack = build_ingest_ack(book, message="dispense accepted")
    assert ack.calculated_remainder_liters == 11500.0
    assert ack.actual_remainder_liters == 10000.0
    assert ack.delta_liters == -1500.0
    assert ack.balance_status == "outside_band"

    state = build_tank_ingest_state(book, station_id=station_id, tank_id=tank_id, calibrated=False)
    assert state.calculated_remainder_liters == 11500.0
    assert state.dispense_liters == 500.0
    assert state.receipts_liters == 2000.0


def test_level_only_simulation_follows_the_gauge():
    """Без приёмки и отпуска следующий уровень симуляции не создаёт излишек."""
    station_id = uuid4()
    tank_id = uuid4()
    book = TankBook(station_id=station_id, tank_id=tank_id)
    now = datetime.now(timezone.utc)
    apply_level_reading(
        book,
        LevelIngest(
            station_id=station_id,
            tank_id=tank_id,
            actual_remainder_liters=1050.0,
            recorded_at=now,
            source_event_id="sim-1",
        ),
        calibration=None,
        capacity_liters=21000.0,
        heard_at=now,
    )
    apply_level_reading(
        book,
        LevelIngest(
            station_id=station_id,
            tank_id=tank_id,
            actual_remainder_liters=9030.0,
            recorded_at=now,
            source_event_id="sim-2",
        ),
        calibration=None,
        capacity_liters=21000.0,
        heard_at=now,
    )
    assert book.opening_liters == 9030.0
    assert book.calculated_remainder_liters == 9030.0
    assert book.delta_liters == 0
    assert book.balance_status == "ok"


def test_volts_noise_filtering_and_calibration():
    station_id = uuid4()
    tank_id = uuid4()
    cal = LevelCalibration(
        capacity_liters=10000.0,
        low_volts=1.0,
        low_percent=0.0,
        high_volts=5.0,
        high_percent=100.0,
    )
    book = TankBook(station_id=station_id, tank_id=tank_id, calibration=cal)
    now = datetime.now(timezone.utc)

    changed1, liters1, fill1 = apply_level_reading(
        book,
        LevelIngest(
            station_id=station_id,
            tank_id=tank_id,
            volts=3.0,
            recorded_at=now,
            source_event_id="v-1",
        ),
        calibration=cal,
        heard_at=now,
    )
    assert changed1 is True
    assert liters1 == pytest.approx(5000.0)
    assert fill1 == 50.0

    # Микроскопический дрейф напряжения в пределах того же процента не считается сменой уровня
    changed2, liters2, _ = apply_level_reading(
        book,
        LevelIngest(
            station_id=station_id,
            tank_id=tank_id,
            volts=3.005,
            recorded_at=now,
            source_event_id="v-2",
        ),
        calibration=cal,
        heard_at=now,
    )
    assert changed2 is False
    assert liters2 == pytest.approx(5000.0)


def test_summarize_station_tanks():
    t1 = TankOut(
        id=uuid4(),
        code="R-1",
        capacity_liters=10000.0,
        has_electronic_sensor=True,
        actual_remainder_liters=4500.0,
        calculated_remainder_liters=5000.0,
        level_source="electronic",
        last_measured_at=None,
    )
    t2 = TankOut(
        id=uuid4(),
        code="R-2",
        capacity_liters=15000.0,
        has_electronic_sensor=True,
        actual_remainder_liters=10000.0,
        calculated_remainder_liters=10000.0,
        level_source="electronic",
        last_measured_at=None,
    )
    remainder, capacity, delta, status = summarize_station_tanks([t1, t2])
    assert remainder == 14500.0
    assert capacity == 25000.0
    assert delta == -500.0
    assert status == "ok"


def test_accept_dispense_and_list_dispense_records_roundtrip():
    import json

    device_ingest.reset_device_ingest()
    station_id = uuid4()
    tank_id = uuid4()
    disp1_id = uuid4()
    t0 = datetime(2026, 11, 18, 9, 15, 0, tzinfo=timezone.utc)

    ack = account.accept_dispense(
        DispenseIngest(
            station_id=station_id,
            dispenser_id=disp1_id,
            tank_id=tank_id,
            volume_liters=18.5,
            started_at=t0,
            finished_at=t0,
            external_txn_id="aska02-akt12-p2-1",
            raw_payload=json.dumps(
                {
                    "source": "aska_02_iskra_1_72",
                    "pump_address": 2,
                    "mode": "full_tank",
                    "price_kzt_per_liter": 72.0,
                }
            ),
        )
    )
    assert ack.duplicate is False

    rows = account.list_dispense_records(station_id)
    assert len(rows) == 1
    assert rows[0].pump_address == 2
    assert rows[0].mode == "full_tank"
    assert rows[0].volume_liters == 18.5
    assert rows[0].price_kzt_per_liter == 72.0

    # Проверка сохранения/восстановления снимка памяти
    snap = device_ingest.snapshot()
    device_ingest.reset_device_ingest()
    assert account.list_dispense_records(station_id) == []
    device_ingest.restore_snapshot(snap)
    restored = account.list_dispense_records(station_id)
    assert len(restored) == 1
    assert restored[0].external_txn_id == "aska02-akt12-p2-1"

    # Колонка с адресом 8 (многопостовая АГЗС) не сбрасывается на 1/2
    ack_p8 = account.accept_dispense(
        DispenseIngest(
            station_id=station_id,
            dispenser_id=uuid4(),
            tank_id=tank_id,
            volume_liters=11.0,
            started_at=datetime(2026, 11, 18, 9, 16, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 11, 18, 9, 17, 0, tzinfo=timezone.utc),
            external_txn_id="aska02-akt12-p8-1",
            raw_payload=json.dumps({"pump_address": 8, "mode": "dose", "price_kzt_per_liter": 72.0}),
        )
    )
    assert ack_p8.duplicate is False
    rows_with_p8 = account.list_dispense_records(station_id)
    assert any(r.pump_address == 8 and r.volume_liters == 11.0 for r in rows_with_p8)
