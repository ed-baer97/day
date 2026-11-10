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
from app.schemas.ingest import LevelIngest
from app.schemas.station import TankOut
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
    assert ack.balance_status == "shortage"

    state = build_tank_ingest_state(book, station_id=station_id, tank_id=tank_id, calibrated=False)
    assert state.calculated_remainder_liters == 11500.0
    assert state.dispense_liters == 500.0
    assert state.receipts_liters == 2000.0


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
    assert status == "shortage"
