"""Тесты высоконагруженного пакетного приёма (Bulk Ingest) и кэширования витрины."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.device_ingest import reset_device_ingest
from app.services.public_board import invalidate_public_board_cache, list_public_stations

client = TestClient(create_app())

STATION = "a2222222-2222-2222-2222-222222222201"
TANK = "b2222222-2222-2222-2222-222222222201"
DISPENSER = "d2222222-2222-2222-2222-222222222201"


@pytest.fixture(autouse=True)
def _clean():
    reset_device_ingest()
    invalidate_public_board_cache()
    yield
    reset_device_ingest()
    invalidate_public_board_cache()


def test_dispenses_batch_ingest_and_idempotency():
    # 1. Стартовый замер уровня
    client.post(
        "/api/v1/ingest/level",
        json={
            "station_id": STATION,
            "tank_id": TANK,
            "actual_remainder_liters": 15000,
            "recorded_at": "2026-10-04T08:00:00Z",
            "source_event_id": "lvl-start",
        },
    )

    batch_payload = {
        "items": [
            {
                "station_id": STATION,
                "dispenser_id": DISPENSER,
                "tank_id": TANK,
                "volume_liters": 45.5,
                "started_at": "2026-10-04T08:10:00Z",
                "external_txn_id": "batch-txn-001",
            },
            {
                "station_id": STATION,
                "dispenser_id": DISPENSER,
                "tank_id": TANK,
                "volume_liters": 60.0,
                "started_at": "2026-10-04T08:15:00Z",
                "external_txn_id": "batch-txn-002",
            },
            {
                "station_id": STATION,
                "dispenser_id": DISPENSER,
                "tank_id": TANK,
                "volume_liters": 30.25,
                "started_at": "2026-10-04T08:20:00Z",
                "external_txn_id": "batch-txn-003",
            },
        ]
    }

    # Отправка пакета из 3 заправок
    resp = client.post("/api/v1/ingest/dispenses/batch", json=batch_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted_count"] == 3
    assert data["duplicates_count"] == 0
    assert abs(data["total_volume_liters"] - 135.75) < 0.001
    assert len(data["results"]) == 3

    # Проверка, что книга остатка списала объём пакета: 15000 - 135.75 = 14864.25
    state = client.get(f"/api/v1/ingest/tanks/{TANK}").json()
    assert abs(state["calculated_remainder_liters"] - 14864.25) < 0.01

    # Повторная отправка того же пакета (идемпотентность, защита от дублей)
    dup_resp = client.post("/api/v1/ingest/dispenses/batch", json=batch_payload)
    assert dup_resp.status_code == 200
    dup_data = dup_resp.json()
    assert dup_data["accepted_count"] == 0
    assert dup_data["duplicates_count"] == 3

    # Остаток не изменился повторно
    state2 = client.get(f"/api/v1/ingest/tanks/{TANK}").json()
    assert abs(state2["calculated_remainder_liters"] - 14864.25) < 0.01


def test_levels_batch_ingest():
    levels_payload = {
        "items": [
            {
                "station_id": STATION,
                "tank_id": TANK,
                "actual_remainder_liters": 12000,
                "recorded_at": "2026-10-04T09:00:00Z",
                "source_event_id": "bulk-lvl-001",
            },
            {
                "station_id": STATION,
                "tank_id": TANK,
                "actual_remainder_liters": 11800,
                "recorded_at": "2026-10-04T09:30:00Z",
                "source_event_id": "bulk-lvl-002",
            },
        ]
    }

    resp = client.post("/api/v1/ingest/levels/batch", json=levels_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted_count"] == 2
    assert data["duplicates_count"] == 0
    assert len(data["results"]) == 2


def test_public_board_cache_invalidation():
    # Первый вызов прогревает кэш
    first = list_public_stations()
    assert len(first) > 0

    # Повторный вызов возвращает тот же объект из кэша памяти
    second = list_public_stations()
    assert second is first

    # Сброс кэша
    invalidate_public_board_cache()
    third = list_public_stations()
    assert third is not first
