"""Тесты консольного монитора смены и вывода статистики на /dev/tty1."""

import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import build_test_response_frame, parse_iskra_frame
from agzs_edge.main import main
from agzs_edge.monitor import (
    build_shift_snapshot,
    install_kiosk_signal_handlers,
    render_shift_dashboard,
    resolve_shift_window,
)
from agzs_edge.storage import EdgeDatabase
from agzs_edge.tracker import CompletedDispense


def _tz_plus_5() -> timezone:
    return timezone(timedelta(hours=5))


def test_resolve_shift_window_day_night_and_24h() -> None:
    tz = _tz_plus_5()

    # Дневная смена: 08:00 - 20:00
    day_now = datetime(2026, 11, 18, 14, 25, 0, tzinfo=tz)
    day_win = resolve_shift_window(day_now, shift_start_hour=8, shift_hours=12)
    assert day_win.label == "Дневная смена"
    assert day_win.start == datetime(2026, 11, 18, 8, 0, 0, tzinfo=tz)
    assert day_win.end == datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz)

    # Ночная смена вечером: 20:00 - 08:00 следующего дня
    night_evening = datetime(2026, 11, 18, 22, 10, 0, tzinfo=tz)
    evening_win = resolve_shift_window(night_evening, shift_start_hour=8, shift_hours=12)
    assert evening_win.label == "Ночная смена"
    assert evening_win.start == datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz)
    assert evening_win.end == datetime(2026, 11, 19, 8, 0, 0, tzinfo=tz)

    # Ночная смена после полуночи (03:45 19-го относится к ночной смене с 18-го 20:00)
    night_morning = datetime(2026, 11, 19, 3, 45, 0, tzinfo=tz)
    morning_win = resolve_shift_window(night_morning, shift_start_hour=8, shift_hours=12)
    assert morning_win.label == "Ночная смена"
    assert morning_win.start == datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz)
    assert morning_win.end == datetime(2026, 11, 19, 8, 0, 0, tzinfo=tz)

    # Суточная смена: 24 часа
    full_win = resolve_shift_window(night_morning, shift_start_hour=8, shift_hours=24)
    assert full_win.label == "Суточная смена"
    assert full_win.start == datetime(2026, 11, 18, 8, 0, 0, tzinfo=tz)
    assert full_win.end == datetime(2026, 11, 19, 8, 0, 0, tzinfo=tz)


def test_shift_snapshot_filters_previous_shift_and_calculates_totals(tmp_path: Path) -> None:
    tz = _tz_plus_5()
    db_path = tmp_path / "station_edge.db"
    db = EdgeDatabase(db_path)

    # Обновляем живое состояние колонки #2 (цена 75.00), чтобы проверить fallback цены при 0.0 в кадре завершения
    frame_p2 = parse_iskra_frame(
        build_test_response_frame(address=2, state_code="05", price_digits=7500, volume_ml=0)
    )
    db.update_live_state(frame_p2, observed_at=datetime(2026, 11, 18, 12, 0, 0, tzinfo=tz))

    # Заправка из прошлой ночной смены (не должна попасть в дневную смену 08:00..20:00)
    prev_disp = CompletedDispense(
        external_txn_id="txn-prev-shift",
        pump_address=1,
        mode="dose",
        preset_ml=10000,
        dispensed_ml=10000,
        volume_liters=10.0,
        price_kzt_per_liter=70.0,
        final_state_code="07",
        error_code="00",
        started_at=datetime(2026, 11, 18, 7, 50, 0, tzinfo=tz),
        finished_at=datetime(2026, 11, 18, 7, 55, 0, tzinfo=tz),
        last_raw_frame_hex="01 31 34",
    )
    # Заправка колонки #1 в текущей дневной смене
    cur_disp_1 = CompletedDispense(
        external_txn_id="txn-cur-1",
        pump_address=1,
        mode="dose",
        preset_ml=20000,
        dispensed_ml=20000,
        volume_liters=20.0,
        price_kzt_per_liter=72.5,
        final_state_code="07",
        error_code="00",
        started_at=datetime(2026, 11, 18, 10, 14, 0, tzinfo=tz),
        finished_at=datetime(2026, 11, 18, 10, 15, 30, tzinfo=tz),
        last_raw_frame_hex="01 31 34",
    )
    # Заправка колонки #2 в текущей смене с price=0.0 -> подставится цена из pump_live_state (75.0)
    cur_disp_2 = CompletedDispense(
        external_txn_id="txn-cur-2",
        pump_address=2,
        mode="full_tank",
        preset_ml=None,
        dispensed_ml=12000,
        volume_liters=12.0,
        price_kzt_per_liter=0.0,
        final_state_code="07",
        error_code="00",
        started_at=datetime(2026, 11, 18, 11, 40, 0, tzinfo=tz),
        finished_at=datetime(2026, 11, 18, 11, 42, 10, tzinfo=tz),
        last_raw_frame_hex="01 32 34",
    )

    for item in (prev_disp, cur_disp_1, cur_disp_2):
        db.record_completed_dispense(
            item,
            station_id="a2222222-2222-2222-2222-222222222201",
            dispenser_id=f"d2222222-2222-2222-2222-22222222220{item.pump_address}",
            tank_id="b2222222-2222-2222-2222-222222222201",
        )

    settings = EdgeSettings(
        db_path=db_path,
        pump_addresses=(1, 2),
        station_code="AKT-12MKR",
        shift_start_hour=8,
        shift_hours=12,
        currency_symbol="₸",
    )
    ro_db = EdgeDatabase(db_path, read_only=True)
    now = datetime(2026, 11, 18, 12, 30, 0, tzinfo=tz)

    between = ro_db.list_dispenses_between(
        datetime(2026, 11, 18, 8, 0, 0, tzinfo=tz),
        datetime(2026, 11, 18, 20, 0, 0, tzinfo=tz),
    )
    assert [row.external_txn_id for row in between] == ["txn-cur-2", "txn-cur-1"]

    snapshot = build_shift_snapshot(ro_db, settings, now=now)
    assert snapshot.total_dispenses == 2
    assert snapshot.total_volume_liters == 32.0
    # 20 * 72.5 = 1450.0, 12 * 75.0 = 900.0 -> итого 2350.0
    assert snapshot.total_amount == 2350.0

    p1, p2 = snapshot.pumps
    assert p1.pump_address == 1
    assert p1.dispense_count == 1
    assert p1.total_volume_liters == 20.0
    assert p1.total_amount == 1450.0
    assert p1.last_time_str == "10:15:30"

    assert p2.pump_address == 2
    assert p2.dispense_count == 1
    assert p2.total_volume_liters == 12.0
    assert p2.total_amount == 900.0
    assert p2.last_time_str == "11:42:10"

    rendered = render_shift_dashboard(snapshot, kiosk=True)
    assert "AKT-12MKR" in rendered
    assert "#1" in rendered and "#2" in rendered
    assert "10:15:30" in rendered and "11:42:10" in rendered
    assert "20.00" in rendered and "12.00" in rendered
    assert "1 450.00 ₸" in rendered and "900.00 ₸" in rendered
    assert "ИТОГО ЗА СМЕНУ" in rendered
    assert "2 350.00 ₸" in rendered
    assert "Режим киоска tty1" in rendered
    for line in rendered.splitlines():
        assert len(line) <= 80, f"Строка превышает 80 символов ({len(line)}): {line}"


def test_read_only_missing_db_and_cli_monitor_once(tmp_path: Path, monkeypatch, capsys) -> None:
    missing_db = tmp_path / "not_created_yet.db"
    ro_db = EdgeDatabase(missing_db, read_only=True)

    # Read-only обращение не создаёт файл БД и не падает
    assert ro_db.list_dispenses() == []
    assert ro_db.list_dispenses_between(datetime.now(timezone.utc) - timedelta(hours=12)) == []
    assert ro_db.summary()["total_dispenses"] == 0
    assert not missing_db.exists()

    env_file = tmp_path / ".env"
    env_file.write_text(
        f"AGZS_DB_PATH={missing_db}\nAGZS_STATION_CODE=TEST-AZS\nAGZS_PUMP_ADDRESSES=1,2\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AGZS_DB_PATH", raising=False)
    monkeypatch.delenv("AGZS_STATION_CODE", raising=False)
    monkeypatch.delenv("AGZS_PUMP_ADDRESSES", raising=False)

    rc = main(["--env-file", str(env_file), "monitor", "--once", "--currency", "₽"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "TEST-AZS" in out
    assert "ИТОГО ЗА СМЕНУ" in out
    assert "0.00 ₽" in out
    assert not missing_db.exists()


def test_install_kiosk_signal_handlers(monkeypatch) -> None:
    recorded: list[tuple[int, object]] = []
    monkeypatch.setattr(signal, "signal", lambda sig, handler: recorded.append((sig, handler)))

    install_kiosk_signal_handlers()

    sigs = {sig for sig, _ in recorded}
    assert signal.SIGINT in sigs
    assert all(handler == signal.SIG_IGN for _, handler in recorded)
