"""Справочник заправок и газовозов.

Пока остальной API на демо-данных, карточки тоже живут в памяти процесса.
Список при старте совпадает с точками на карте, чтобы их можно было править.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import HTTPException

_lock = threading.Lock()

TRUCK_STATUSES = ("idle", "loading", "in_transit", "arrived", "unloading")


@dataclass
class StationCard:
    id: UUID
    code: str
    name: str
    address: str | None
    lat: float
    lon: float
    is_active: bool


@dataclass
class TruckCard:
    id: UUID
    plate_number: str
    capacity_liters: float
    carrier_name: str | None
    status: str
    lat: float | None
    lon: float | None


def _stations() -> list[StationCard]:
    rows = [
        ("a1111111-1111-1111-1111-111111111101", "AGZS-AKT-12", "АГЗС Актау · 12 мкр", "Актау, 12 микрорайон", 43.6479, 51.2480),
    ]
    return [
        StationCard(UUID(sid), code, name, address, lat, lon, True)
        for sid, code, name, address, lat, lon in rows
    ]


def _trucks() -> list[TruckCard]:
    return [
        TruckCard(
            UUID("c1111111-1111-1111-1111-111111111101"),
            "705 ABA 12",
            18000,
            "ГазТранс Мангыстау",
            "in_transit",
            43.55,
            52.05,
        ),
        TruckCard(
            UUID("c1111111-1111-1111-1111-111111111102"),
            "701 ABA 12",
            20000,
            "ЛПГ Мангыстау",
            "in_transit",
            43.45,
            52.35,
        ),
    ]


_station_cards: list[StationCard] = _stations()
_truck_cards: list[TruckCard] = _trucks()


def reset_catalog() -> None:
    global _station_cards, _truck_cards
    with _lock:
        _station_cards = _stations()
        _truck_cards = _trucks()


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _require_code(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"укажите {label}")
    return cleaned


def _require_status(value: str) -> str:
    if value not in TRUCK_STATUSES:
        raise HTTPException(status_code=422, detail="неизвестный статус газовоза")
    return value


def list_stations() -> list[StationCard]:
    with _lock:
        return list(_station_cards)


def get_station(station_id: UUID) -> StationCard:
    with _lock:
        for station in _station_cards:
            if station.id == station_id:
                return station
    raise HTTPException(status_code=404, detail="Station not found")


def create_station(
    *,
    code: str,
    name: str,
    address: str | None,
    lat: float,
    lon: float,
    is_active: bool,
) -> StationCard:
    cleaned_code = _require_code(code, "код заправки")
    cleaned_name = _require_code(name, "название заправки")
    with _lock:
        if any(station.code == cleaned_code for station in _station_cards):
            raise HTTPException(status_code=409, detail="заправка с таким кодом уже есть")
        station = StationCard(
            id=uuid4(),
            code=cleaned_code,
            name=cleaned_name,
            address=_text(address),
            lat=lat,
            lon=lon,
            is_active=is_active,
        )
        _station_cards.append(station)
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
    address_set: bool = False,
) -> StationCard:
    with _lock:
        station = next((item for item in _station_cards if item.id == station_id), None)
        if station is None:
            raise HTTPException(status_code=404, detail="Station not found")
        if code is not None:
            cleaned = _require_code(code, "код заправки")
            if any(item.code == cleaned and item.id != station_id for item in _station_cards):
                raise HTTPException(status_code=409, detail="заправка с таким кодом уже есть")
            station.code = cleaned
        if name is not None:
            station.name = _require_code(name, "название заправки")
        if address_set:
            station.address = _text(address)
        if lat is not None:
            station.lat = lat
        if lon is not None:
            station.lon = lon
        if is_active is not None:
            station.is_active = is_active
        return station


def list_trucks() -> list[TruckCard]:
    with _lock:
        return list(_truck_cards)


def get_truck(truck_id: UUID) -> TruckCard:
    with _lock:
        for truck in _truck_cards:
            if truck.id == truck_id:
                return truck
    raise HTTPException(status_code=404, detail="Truck not found")


def create_truck(
    *,
    plate_number: str,
    capacity_liters: float,
    carrier_name: str | None,
    status: str,
    lat: float | None,
    lon: float | None,
) -> TruckCard:
    plate = _require_code(plate_number, "номер газовоза")
    status = _require_status(status)
    with _lock:
        if any(truck.plate_number == plate for truck in _truck_cards):
            raise HTTPException(status_code=409, detail="газовоз с таким номером уже есть")
        truck = TruckCard(
            id=uuid4(),
            plate_number=plate,
            capacity_liters=capacity_liters,
            carrier_name=_text(carrier_name),
            status=status,
            lat=lat,
            lon=lon,
        )
        _truck_cards.append(truck)
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
            raise HTTPException(status_code=404, detail="Truck not found")
        if plate_number is not None:
            plate = _require_code(plate_number, "номер газовоза")
            if any(item.plate_number == plate and item.id != truck_id for item in _truck_cards):
                raise HTTPException(status_code=409, detail="газовоз с таким номером уже есть")
            truck.plate_number = plate
        if capacity_liters is not None:
            truck.capacity_liters = capacity_liters
        if carrier_set:
            truck.carrier_name = _text(carrier_name)
        if status is not None:
            truck.status = _require_status(status)
        if lat_set:
            truck.lat = lat
        if lon_set:
            truck.lon = lon
        return truck
