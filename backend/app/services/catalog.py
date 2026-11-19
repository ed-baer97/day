"""Справочник заправок и газовозов в памяти процесса."""

from __future__ import annotations

import threading
from uuid import UUID, uuid4

from app.domain.entities import TRUCK_STATUSES, StationCard, TruckCard
from app.domain.errors import ConflictError, NotFoundError
from app.services.account_helpers import (
    clean_optional_text,
    require_columns_count,
    require_columns_mode,
    require_non_empty,
    require_truck_status,
    reset_gps_seen,
)
from app.services.board_cache import invalidate_public_board_cache
from app.services.memory_state import persist, register_store

_lock = threading.Lock()


def _default_columns_mode(code: str, name: str) -> str:
    c = code.strip().lower()
    n = name.strip().lower()
    if "rekon" in n or c in {"agzs-akt-12", "akt-12mkr"}:
        return "virtual"
    return "none"


def _stations() -> list[StationCard]:
    rows = [
        ("a1111111-1111-1111-1111-111111111101", "AGZS-AKT-12", "АГЗС Актау · 12 мкр", "Актау, 12 микрорайон", 43.6479, 51.2480, "virtual", 2),
    ]
    return [
        StationCard(UUID(sid), code, name, address, lat, lon, True, columns_mode, columns_count)
        for sid, code, name, address, lat, lon, columns_mode, columns_count in rows
    ]


def _trucks() -> list[TruckCard]:
    return []


_station_cards: list[StationCard] = _stations()
_truck_cards: list[TruckCard] = _trucks()


def reset_catalog() -> None:
    global _station_cards, _truck_cards
    with _lock:
        _station_cards = _stations()
        _truck_cards = _trucks()
    reset_gps_seen()
    invalidate_public_board_cache()


def list_stations() -> list[StationCard]:
    with _lock:
        return list(_station_cards)


def get_station(station_id: UUID) -> StationCard:
    with _lock:
        for station in _station_cards:
            if station.id == station_id:
                return station
    raise NotFoundError("Station not found")


def create_station(
    *,
    code: str,
    name: str,
    address: str | None,
    lat: float,
    lon: float,
    is_active: bool,
    columns_mode: str = "none",
    columns_count: int = 2,
) -> StationCard:
    cleaned_code = require_non_empty(code, "код заправки")
    cleaned_name = require_non_empty(name, "название заправки")
    valid_mode = require_columns_mode(columns_mode)
    valid_count = require_columns_count(columns_count)
    with _lock:
        if any(station.code == cleaned_code for station in _station_cards):
            raise ConflictError("заправка с таким кодом уже есть")
        station = StationCard(
            id=uuid4(),
            code=cleaned_code,
            name=cleaned_name,
            address=clean_optional_text(address),
            lat=lat,
            lon=lon,
            is_active=is_active,
            columns_mode=valid_mode,
            columns_count=valid_count,
        )
        _station_cards.append(station)
    persist()
    return station


def update_station(
    station_id: UUID,
    *,
    code: str | None = None,
    name: str | None = None,
    address: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    is_active: bool | None = None,
    columns_mode: str | None = None,
    columns_count: int | None = None,
    address_set: bool = False,
) -> StationCard:
    with _lock:
        station = next((item for item in _station_cards if item.id == station_id), None)
        if station is None:
            raise NotFoundError("Station not found")
        if code is not None:
            cleaned = require_non_empty(code, "код заправки")
            if any(item.code == cleaned and item.id != station_id for item in _station_cards):
                raise ConflictError("заправка с таким кодом уже есть")
            station.code = cleaned
        if name is not None:
            station.name = require_non_empty(name, "название заправки")
        if address_set:
            station.address = clean_optional_text(address)
        if lat is not None:
            station.lat = lat
        if lon is not None:
            station.lon = lon
        if is_active is not None:
            station.is_active = is_active
        if columns_mode is not None:
            station.columns_mode = require_columns_mode(columns_mode)
        if columns_count is not None:
            station.columns_count = require_columns_count(columns_count)
    persist()
    return station


def delete_station(station_id: UUID) -> None:
    with _lock:
        index = next((i for i, item in enumerate(_station_cards) if item.id == station_id), None)
        if index is None:
            raise NotFoundError("Station not found")
        _station_cards.pop(index)
    persist()


def list_trucks() -> list[TruckCard]:
    with _lock:
        return list(_truck_cards)


def get_truck(truck_id: UUID) -> TruckCard:
    with _lock:
        for truck in _truck_cards:
            if truck.id == truck_id:
                return truck
    raise NotFoundError("Truck not found")


def create_truck(
    *,
    plate_number: str,
    capacity_liters: float,
    carrier_name: str | None,
    status: str,
    lat: float | None,
    lon: float | None,
) -> TruckCard:
    plate = require_non_empty(plate_number, "номер газовоза")
    valid_status = require_truck_status(status)
    with _lock:
        if any(truck.plate_number == plate for truck in _truck_cards):
            raise ConflictError("газовоз с таким номером уже есть")
        truck = TruckCard(
            id=uuid4(),
            plate_number=plate,
            capacity_liters=capacity_liters,
            carrier_name=clean_optional_text(carrier_name),
            status=valid_status,
            lat=lat,
            lon=lon,
        )
        _truck_cards.append(truck)
    persist()
    return truck


def update_truck(
    truck_id: UUID,
    *,
    plate_number: str | None = None,
    capacity_liters: float | None = None,
    carrier_name: str | None = None,
    status: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    carrier_set: bool = False,
    lat_set: bool = False,
    lon_set: bool = False,
) -> TruckCard:
    with _lock:
        truck = next((item for item in _truck_cards if item.id == truck_id), None)
        if truck is None:
            raise NotFoundError("Truck not found")
        if plate_number is not None:
            plate = require_non_empty(plate_number, "номер газовоза")
            if any(item.plate_number == plate and item.id != truck_id for item in _truck_cards):
                raise ConflictError("газовоз с таким номером уже есть")
            truck.plate_number = plate
        if capacity_liters is not None:
            truck.capacity_liters = capacity_liters
        if carrier_set:
            truck.carrier_name = clean_optional_text(carrier_name)
        if status is not None:
            truck.status = require_truck_status(status)
        if lat_set:
            truck.lat = lat
        if lon_set:
            truck.lon = lon
    persist()
    return truck


def delete_truck(truck_id: UUID) -> None:
    with _lock:
        index = next((i for i, item in enumerate(_truck_cards) if item.id == truck_id), None)
        if index is None:
            raise NotFoundError("Truck not found")
        _truck_cards.pop(index)
    persist()


def snapshot() -> dict:
    with _lock:
        return {
            "stations": [
                {
                    "id": str(station.id),
                    "code": station.code,
                    "name": station.name,
                    "address": station.address,
                    "lat": station.lat,
                    "lon": station.lon,
                    "is_active": station.is_active,
                    "columns_mode": station.columns_mode,
                    "columns_count": station.columns_count,
                }
                for station in _station_cards
            ],
            "trucks": [
                {
                    "id": str(truck.id),
                    "plate_number": truck.plate_number,
                    "capacity_liters": truck.capacity_liters,
                    "carrier_name": truck.carrier_name,
                    "status": truck.status,
                    "lat": truck.lat,
                    "lon": truck.lon,
                }
                for truck in _truck_cards
            ],
        }


def restore_snapshot(data: dict) -> None:
    """Подменяет справочник содержимым файла. Без ключей список не трогает."""
    global _station_cards, _truck_cards
    if not isinstance(data, dict) or ("stations" not in data and "trucks" not in data):
        return
    stations = [
        StationCard(
            id=UUID(row["id"]),
            code=row["code"],
            name=row["name"],
            address=row.get("address"),
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            is_active=bool(row["is_active"]),
            columns_mode=str(
                row.get("columns_mode")
                or _default_columns_mode(str(row.get("code") or ""), str(row.get("name") or ""))
            ),
            columns_count=int(row["columns_count"]) if row.get("columns_count") is not None else 2,
        )
        for row in data.get("stations") or []
    ]
    trucks = [
        TruckCard(
            id=UUID(row["id"]),
            plate_number=row["plate_number"],
            capacity_liters=float(row["capacity_liters"]),
            carrier_name=row.get("carrier_name"),
            status=row["status"],
            lat=None if row.get("lat") is None else float(row["lat"]),
            lon=None if row.get("lon") is None else float(row["lon"]),
        )
        for row in data.get("trucks") or []
    ]
    with _lock:
        if "stations" in data:
            _station_cards = stations
        if "trucks" in data:
            _truck_cards = trucks


register_store("catalog", snapshot, restore_snapshot)

__all__ = [
    "TRUCK_STATUSES",
    "StationCard",
    "TruckCard",
    "create_station",
    "create_truck",
    "delete_station",
    "delete_truck",
    "get_station",
    "get_truck",
    "list_stations",
    "list_trucks",
    "reset_catalog",
    "restore_snapshot",
    "snapshot",
    "update_station",
    "update_truck",
]
