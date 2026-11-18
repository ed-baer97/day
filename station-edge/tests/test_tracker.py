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


def _live_frame(state: str, price: str, volume: str, status: int) -> bytes:
    body = b"01" + b"4" + bytes([0x02]) + price.encode() + volume.encode() + bytes([0x50, status]) + state.encode() + bytes([0x03])
    bcc = 0
    for b in body:
        bcc ^= b
    return bytes([0x01]) + body + bytes([bcc])


def test_live_aska02_fill_closed_by_completed_frame_with_total_in_price_field() -> None:
    """УЗСГ-01 через АСКА-02: при уставке 090000 (900 л) в Price итог 9 л берётся из Volume (009000)."""
    tracker = PumpDispenseTracker(station_code="AGZS-AKT-12")
    t0 = datetime(2026, 11, 17, 9, 30, 0, tzinfo=timezone.utc)

    frames = [
        _live_frame("05", "007200", "000000", 0x89),
        _live_frame("03", "007200", "000410", 0x8F),
        _live_frame("03", "007200", "004740", 0x8F),
        _live_frame("03", "007200", "008880", 0x8F),
    ]
    for i, raw in enumerate(frames):
        assert tracker.process_frame(parse_iskra_frame(raw), observed_at=t0 + timedelta(seconds=i)) is None

    done = tracker.process_frame(
        parse_iskra_frame(_live_frame("07", "090000", "009000", 0x8F)),
        observed_at=t0 + timedelta(seconds=10),
    )
    assert done is not None
    assert done.dispensed_ml == 9000
    assert done.volume_liters == 9.0
    assert done.price_kzt_per_liter == 72.0


def test_live_aska02_preserves_idle_price_when_dispensing_carries_volume_in_price_field() -> None:
    """Холостой пуск с уставкой 090000 и Volume=0 не создаёт запись 9 л; реальный налив закрывается по Volume."""
    tracker = PumpDispenseTracker(station_code="AKT-12MKR")
    t0 = datetime(2026, 11, 17, 15, 27, 40, tzinfo=timezone.utc)

    idle_raw = bytes.fromhex("01 30 31 34 02 30 30 37 32 30 30 30 30 30 30 30 30 50 92 30 35 03 F6")
    dry_disp_raw = bytes.fromhex("01 30 31 34 02 30 39 30 30 30 30 30 30 30 30 30 30 D0 92 30 33 03 7C")
    dry_done_raw = bytes.fromhex("01 30 31 34 02 30 39 30 30 30 30 30 30 30 30 30 30 50 92 30 37 03 F8")

    # 1. Холостое нажатие «ПУСК» (газ не проливался, Volume=000000) -> None (нельзя писать 9 л в БД)
    assert tracker.process_frame(parse_iskra_frame(idle_raw), observed_at=t0) is None
    assert tracker.process_frame(parse_iskra_frame(dry_disp_raw), observed_at=t0 + timedelta(seconds=2)) is None
    assert tracker.process_frame(parse_iskra_frame(dry_done_raw), observed_at=t0 + timedelta(seconds=4)) is None

    # 2. Реальный налив 9000 мл при той же уставке 090000 в Price
    real_disp_raw = _live_frame("03", "090000", "004500", 0x92)
    real_done_raw = _live_frame("07", "090000", "009000", 0x92)
    assert tracker.process_frame(parse_iskra_frame(idle_raw), observed_at=t0 + timedelta(seconds=10)) is None
    assert tracker.process_frame(parse_iskra_frame(real_disp_raw), observed_at=t0 + timedelta(seconds=12)) is None

    done = tracker.process_frame(parse_iskra_frame(real_done_raw), observed_at=t0 + timedelta(seconds=14))
    assert done is not None
    assert done.dispensed_ml == 9000
    assert done.volume_liters == 9.0
    assert done.price_kzt_per_liter == 72.0
    assert done.error_code == "00"


def test_cancelled_dose_set_does_not_leak_into_next_full_tank_fill() -> None:
    """Набранная доза '01', сброшенная в '05' до пуска, не должна искажать следующий налив 'до полного'."""
    tracker = PumpDispenseTracker(station_code="AKT-12")
    t0 = datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)

    assert tracker.process_frame(_frame(1, STATE_DOSE_SET, 20000), observed_at=t0) is None
    assert tracker.process_frame(_frame(1, STATE_IDLE, 0), observed_at=t0 + timedelta(seconds=2)) is None

    # Следующий налив — режим «до полного» (растущий объём 0 -> 3500)
    assert tracker.process_frame(_frame(1, STATE_DISPENSING, 0), observed_at=t0 + timedelta(seconds=5)) is None
    assert tracker.process_frame(_frame(1, STATE_DISPENSING, 3500), observed_at=t0 + timedelta(seconds=8)) is None
    done = tracker.process_frame(_frame(1, STATE_COMPLETED, 3500), observed_at=t0 + timedelta(seconds=10))
    assert done is not None
    assert done.mode == MODE_FULL_TANK
    assert done.dispensed_ml == 3500


def test_single_live_frame_03_then_idle_05_preserves_volume() -> None:
    """Единственный пойманный живой кадр '03' (P92, 4500 мл) перед сбросом '05' (0 мл) не теряет 4500 мл."""
    tracker = PumpDispenseTracker(station_code="AKT-12MKR")
    t0 = datetime(2026, 11, 18, 11, 0, 0, tzinfo=timezone.utc)

    assert tracker.process_frame(parse_iskra_frame(_live_frame("05", "007200", "000000", 0x92)), observed_at=t0) is None
    assert tracker.process_frame(parse_iskra_frame(_live_frame("03", "090000", "004500", 0x92)), observed_at=t0 + timedelta(seconds=1)) is None

    done = tracker.process_frame(
        parse_iskra_frame(_live_frame("05", "007200", "000000", 0x92)),
        observed_at=t0 + timedelta(seconds=2),
    )
    assert done is not None
    assert done.mode == MODE_FULL_TANK
    assert done.dispensed_ml == 4500
    assert done.price_kzt_per_liter == 72.0


def test_tracker_preserves_column_error_code_from_sost_byte19() -> None:
    """Аппаратный код ошибки колонки 01..04 из Sost[19] сохраняется в CompletedDispense.error_code."""
    from agzs_edge.iskra import CMD_TEST_ASCII, ETX, SOH, STX, compute_bcc

    tracker = PumpDispenseTracker(station_code="AKT-12")
    t0 = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)

    assert tracker.process_frame(parse_iskra_frame(_live_frame("03", "007200", "002100", 0x8F)), observed_at=t0) is None

    body = b"01" + bytes([CMD_TEST_ASCII, STX]) + b"090000" + b"002100" + bytes([0x50, 0x8F, 0xB2, ord("7"), ETX])
    err_raw = bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])
    done = tracker.process_frame(parse_iskra_frame(err_raw), observed_at=t0 + timedelta(seconds=3))
    assert done is not None
    assert done.dispensed_ml == 2100
    assert done.error_code == "02"
