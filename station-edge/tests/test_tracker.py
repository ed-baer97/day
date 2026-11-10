"""Тесты расчёта объёма налива (обычная доза с убыванием остатка и режим «до полного»)."""

from datetime import datetime, timedelta, timezone

from agzs_edge.iskra import (
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_STOPPED,
    build_test_response_frame,
    parse_iskra_frame,
)
from agzs_edge.tracker import MODE_DOSE, MODE_FULL_TANK, PumpDispenseTracker


def _frame(addr: int, state: str, volume_ml: int, *, flags: str = "00", price: int = 10000):
    raw = build_test_response_frame(
        address=addr,
        state_code=state,
        error_code="00",
        price_digits=price,
        volume_ml=volume_ml,
        flags=flags,
    )
    return parse_iskra_frame(raw)


def test_ordinary_dose_countdown_example_from_spec() -> None:
    """Пример из ТЗ: задали 20,000 л (20000 мл), в кадре 12,500 — налито 7,500 мл."""
    tracker = PumpDispenseTracker(station_code="AKT-12")
    t0 = datetime(2026, 11, 11, 8, 0, 0, tzinfo=timezone.utc)

    # 1. На пульте набрали дозу 20 000 мл
    assert tracker.process_frame(_frame(1, STATE_DOSE_SET, 20000), observed_at=t0) is None

    # 2. Включили пуск на колонке: в кадре остаток 16 000 мл (налито 4 000 мл)
    assert tracker.process_frame(_frame(1, STATE_DISPENSING, 16000), observed_at=t0 + timedelta(seconds=5)) is None
    session = tracker.active_session(1)
    assert session is not None
    assert session.mode == MODE_DOSE
    assert session.current_dispensed_ml == 4000

    # 3. В кадре остаток 12 500 мл -> налито 20 000 - 12 500 = 7 500 мл
    assert tracker.process_frame(_frame(1, STATE_DISPENSING, 12500), observed_at=t0 + timedelta(seconds=10)) is None
    assert tracker.active_session(1).current_dispensed_ml == 7500

    # 4. Остановили кнопкой Стоп на остатке 12 500 мл -> заправка закрывается с dispensed_ml = 7500
    done = tracker.process_frame(_frame(1, STATE_STOPPED, 12500), observed_at=t0 + timedelta(seconds=12))
    assert done is not None
    assert done.pump_address == 1
    assert done.mode == MODE_DOSE
    assert done.preset_ml == 20000
    assert done.dispensed_ml == 7500
    assert done.volume_liters == 7.5
    assert done.price_kzt_per_liter == 100.0


def test_ordinary_dose_detected_without_prior_dose_set_frame() -> None:
    """Если первый пойманный кадр сразу DISPENSING с 20 000 мл, а затем 12 500 ->0."""
    tracker = PumpDispenseTracker(station_code="AKT-12")
    t0 = datetime(2026, 11, 11, 9, 0, 0, tzinfo=timezone.utc)

    assert tracker.process_frame(_frame(1, STATE_DISPENSING, 20000), observed_at=t0) is None
    assert tracker.process_frame(_frame(1, STATE_DISPENSING, 12500), observed_at=t0 + timedelta(seconds=10)) is None
    assert tracker.process_frame(_frame(1, STATE_DISPENSING, 0), observed_at=t0 + timedelta(seconds=25)) is None

    done = tracker.process_frame(_frame(1, STATE_COMPLETED, 0), observed_at=t0 + timedelta(seconds=26))
    assert done is not None
    assert done.mode == MODE_DOSE
    assert done.preset_ml == 20000
    assert done.dispensed_ml == 20000
    assert done.volume_liters == 20.0


def test_full_tank_mode_accumulates_dispensed_ml() -> None:
    """Режим «До полного»: дозы заранее нет, поле объёма уже содержит отпущенные миллилитры."""
    tracker = PumpDispenseTracker(station_code="AKT-12")
    t0 = datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc)

    assert tracker.process_frame(_frame(2, STATE_IDLE, 0), observed_at=t0) is None
    assert tracker.process_frame(_frame(2, STATE_DISPENSING, 0), observed_at=t0 + timedelta(seconds=1)) is None
    assert tracker.process_frame(_frame(2, STATE_DISPENSING, 5400), observed_at=t0 + timedelta(seconds=8)) is None
    assert tracker.process_frame(_frame(2, STATE_DISPENSING, 18350), observed_at=t0 + timedelta(seconds=20)) is None

    # Остановка по ослаблению струи или кнопке
    done = tracker.process_frame(_frame(2, STATE_COMPLETED, 18350), observed_at=t0 + timedelta(seconds=22))
    assert done is not None
    assert done.pump_address == 2
    assert done.mode == MODE_FULL_TANK
    assert done.preset_ml is None
    assert done.dispensed_ml == 18350
    assert done.volume_liters == 18.35
