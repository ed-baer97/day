"""Создание и правка заправок и газовозов."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.catalog import reset_catalog

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def _clean_catalog():
    reset_catalog()
    yield
    reset_catalog()


def test_stations_start_from_the_map_list():
    listed = client.get("/api/v1/stations")
    assert listed.status_code == 200
    codes = {row["code"] for row in listed.json()}
    assert codes == {"AGZS-AKT-12"}


def test_create_and_edit_station():
    created = client.post(
        "/api/v1/stations",
        json={
            "code": "AGZS-NEW-01",
            "name": "АГЗС Бейнеу",
            "address": "Бейнеу",
            "lat": 45.3167,
            "lon": 55.2,
        },
    )
    assert created.status_code == 201
    station_id = created.json()["id"]
    assert created.json()["is_active"] is True

    duplicate = client.post(
        "/api/v1/stations",
        json={"code": "AGZS-NEW-01", "name": "ещё", "lat": 43.0, "lon": 51.0},
    )
    assert duplicate.status_code == 409

    patched = client.patch(
        f"/api/v1/stations/{station_id}",
        json={"name": "АГЗС Бейнеу · трасса", "is_active": False},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "АГЗС Бейнеу · трасса"
    assert patched.json()["is_active"] is False
    assert patched.json()["code"] == "AGZS-NEW-01"

    detail = client.get(f"/api/v1/stations/{station_id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "АГЗС Бейнеу · трасса"
    assert detail.json()["tanks"] == []


def test_new_station_accepts_a_tank():
    created = client.post(
        "/api/v1/stations",
        json={"code": "AGZS-TANK-01", "name": "АГЗС с резервуаром", "lat": 43.7, "lon": 51.2},
    )
    station_id = created.json()["id"]
    tank = client.post(
        f"/api/v1/stations/{station_id}/devices",
        json={"code": "R-1", "capacity_liters": 15000},
    )
    assert tank.status_code == 201
    assert tank.json()["ingest_token"]


def test_create_and_edit_truck():
    listed = client.get("/api/v1/trucks")
    assert listed.status_code == 200
    assert any(row["plate_number"] == "705 ABA 12" for row in listed.json())

    created = client.post(
        "/api/v1/trucks",
        json={
            "plate_number": "777 ABA 12",
            "capacity_liters": 16000,
            "carrier_name": "Свой парк",
            "status": "idle",
            "lat": 43.65,
            "lon": 51.16,
        },
    )
    assert created.status_code == 201
    truck_id = created.json()["id"]

    duplicate = client.post(
        "/api/v1/trucks",
        json={"plate_number": "777 ABA 12", "capacity_liters": 1000},
    )
    assert duplicate.status_code == 409

    patched = client.patch(
        f"/api/v1/trucks/{truck_id}",
        json={"capacity_liters": 17000, "status": "arrived"},
    )
    assert patched.status_code == 200
    assert patched.json()["capacity_liters"] == 17000
    assert patched.json()["status"] == "arrived"
    assert patched.json()["plate_number"] == "777 ABA 12"

    detail = client.get(f"/api/v1/trucks/{truck_id}")
    assert detail.status_code == 200
    assert detail.json()["carrier_name"] == "Свой парк"
    assert detail.json()["lat"] == 43.65
