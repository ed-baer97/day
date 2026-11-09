"""Пульт колонок: доза, эмулятор, журнал и запись отпуска в книгу."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.catalog import reset_catalog
from app.services.device_ingest import reset_device_ingest
from app.services.pump_console import (
    advance_for_tests,
    console_close_shift,
    console_journal,
    console_open_shift,
    console_set_price,
    console_snapshot,
    console_start,
    console_stop,
    cost_kzt,
    max_ml_for_prepaid,
    preset_kzt,
    reset_consoles,
    use_manual_clock,
)

STATION = UUID("a1111111-1111-1111-1111-111111111101")
client = TestClient(create_app())


@pytest.fixture(autouse=True)
def _clean():
    reset_catalog()
    reset_device_ingest()
    reset_consoles()
    yield
    reset_consoles()


def test_cabinet_takes_price_and_finished_dose():
    use_manual_clock(STATION)
    priced = console_set_price(STATION, 80)
    assert priced["price_kzt_per_liter"] == 80
    assert priced["delivered_ml"] == 0
    assert len(priced["pumps"]) == 2

    console_open_shift(STATION)
    face = console_snapshot(STATION)
    pump_id = UUID(face["pumps"][0]["pump_id"])
    assert face["pumps"][0]["price_kzt_per_liter"] == 80
    console_start(STATION, pump_id, "money", "80")
    advance_for_tests(STATION, 6_000)

    cabinet = client.get(f"/api/v1/stations/{STATION}/console/cabinet")
    assert cabinet.status_code == 200
    body = cabinet.json()
    delivered = body["pumps"][0]["delivered_ml"]
    assert delivered == max_ml_for_prepaid(80, 80)
    assert body["pumps"][0]["amount_kzt"] == cost_kzt(delivered, 80)
    assert body["pumps"][1]["delivered_ml"] == 0
    assert body["amount_kzt"] == body["pumps"][0]["amount_kzt"]
    assert body["recent"][0]["pump_name"] == "Колонка 1"
    assert body["recent"][0]["price_kzt_per_liter"] == 80

    rejected = client.put(
        f"/api/v1/stations/{STATION}/console/cabinet/price",
        json={"price_kzt_per_liter": 0},
    )
    assert rejected.status_code == 422


def test_prepaid_limit_does_not_exceed_money():
    for amount in (1, 90, 100, 500, 2500):
        ml = max_ml_for_prepaid(amount, 100)
        assert cost_kzt(ml, 100) <= amount
        assert cost_kzt(ml + 1, 100) > amount


def test_liters_become_tenge_by_column_price():
    assert preset_kzt("2.5", "volume", 100) == 250
    assert preset_kzt("400", "money", 100) == 400


def test_fill_runs_to_prepaid_and_lands_in_the_tank_book():
    created = client.post(
        f"/api/v1/stations/{STATION}/devices",
        json={"code": "R-1", "capacity_liters": 10000},
    )
    assert created.status_code == 201
    tank_id = created.json()["id"]
    level = client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": str(STATION),
            "tank_id": tank_id,
            "actual_remainder_liters": 8000,
            "recorded_at": "2026-11-09T06:00:00Z",
            "source_event_id": "console-open",
        },
    )
    assert level.status_code == 200

    use_manual_clock(STATION)
    console_open_shift(STATION)
    face = console_snapshot(STATION)
    pump_id = UUID(face["pumps"][0]["pump_id"])
    message, started = console_start(STATION, pump_id, "money", "500")
    assert message.startswith("Пуск")
    assert started["pumps"][0]["status"] == "DISPENSING"

    advance_for_tests(STATION, 1_000)
    mid = console_snapshot(STATION)
    assert mid["pumps"][0]["dose_ml"] == 200
    assert mid["pumps"][0]["provisional_kzt"] == 20

    done = advance_for_tests(STATION, 30_000)
    pump = done["pumps"][0]
    assert pump["status"] == "IDLE"
    assert pump["dose_ml"] == max_ml_for_prepaid(500, 100)
    assert pump["provisional_kzt"] == 500
    assert pump["totalizer_ml"] == max_ml_for_prepaid(500, 100)

    titles = [row["title"] for row in console_journal(STATION)]
    assert "Отпуск" in titles
    assert "Расчёт" in titles

    book = client.get(f"/api/v1/ingest/tanks/{tank_id}")
    assert book.status_code == 200
    assert book.json()["dispense_liters"] == pytest.approx(max_ml_for_prepaid(500, 100) / 1000)


def test_early_stop_keeps_the_shortfall_and_blocks_a_busy_shift():
    use_manual_clock(STATION)
    console_open_shift(STATION)
    pump_id = UUID(console_snapshot(STATION)["pumps"][0]["pump_id"])
    console_start(STATION, pump_id, "money", "500")
    advance_for_tests(STATION, 1_000)
    with pytest.raises(Exception) as busy:
        console_close_shift(STATION)
    assert busy.value.status_code == 409

    text, stopped = console_stop(STATION, pump_id)
    assert "остановлен" in text
    assert stopped["pumps"][0]["status"] == "IDLE"
    settlement = next(row for row in console_journal(STATION) if row["title"] == "Расчёт")
    assert "расхождение" in settlement["change"]
    closed, face = console_close_shift(STATION)
    assert "закрыта" in closed
    assert face["shift"]["status"] == "closed"


def test_http_console_refuses_start_without_a_dose_and_after_the_link_drops():
    opened = client.post(f"/api/v1/stations/{STATION}/console/shift/open")
    assert opened.status_code == 200
    pump_id = opened.json()["pumps"][0]["pump_id"]

    empty = client.post(
        f"/api/v1/stations/{STATION}/console/pumps/{pump_id}/start",
        json={"mode": "money", "buffer": ""},
    )
    assert empty.status_code == 409
    assert "дозу" in empty.json()["detail"]

    cut = client.post(f"/api/v1/stations/{STATION}/console/link", json={"up": False})
    assert cut.status_code == 200
    assert cut.json()["desk"]["pumps"][0]["observation_quality"] == "UNKNOWN"
    blocked = client.post(
        f"/api/v1/stations/{STATION}/console/pumps/{pump_id}/start",
        json={"mode": "money", "buffer": "100"},
    )
    assert blocked.status_code == 409

    client.post(f"/api/v1/stations/{STATION}/console/link", json={"up": True})
    client.post(f"/api/v1/stations/{STATION}/console/commands", json={"latched": True})
    latched = client.post(
        f"/api/v1/stations/{STATION}/console/pumps/{pump_id}/start",
        json={"mode": "money", "buffer": "100"},
    )
    assert latched.status_code == 409
    assert "запрещ" in latched.json()["detail"]
