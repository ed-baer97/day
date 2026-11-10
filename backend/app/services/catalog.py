"""Справочник заправок и газовозов.

Карточки живут в памяти процесса. На старте — живая АГЗС с датчиком.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.schemas.ingest import IngestAck

_lock = threading.Lock()


def _commit() -> None:
    from app.services.memory_state import persist

    persist()

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
    return []


_station_cards: list[StationCard] = _stations()
_truck_cards: list[TruckCard] = _trucks()
_seen_gps: set[str] = set()
_MAX_SEEN_GPS = 10_000


def reset_catalog() -> None:
    global _station_cards, _truck_cards
    with _lock:
        _station_cards = _stations()
        _truck_cards = _trucks()
        _seen_gps.clear()


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
    _commit()
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
    _commit()
    return station


def delete_station(station_id: UUID) -> None:
    from app.services.device_ingest import delete_station_devices

    with _lock:
        index = next((i for i, item in enumerate(_station_cards) if item.id == station_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail="Station not found")
        _station_cards.pop(index)
    delete_station_devices(station_id)
    _commit()


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
    _commit()
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
    _commit()
    return truck


def delete_truck(truck_id: UUID) -> None:
    with _lock:
        index = next((i for i, item in enumerate(_truck_cards) if item.id == truck_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail="Truck not found")
        _truck_cards.pop(index)
    _commit()


def record_truck_position(
    truck_id: UUID,
    *,
    lat: float,
    lon: float,
    recorded_at: datetime,
    source_event_id: str | None,
) -> IngestAck:
    """Пишет координату газовоза. Повтор того же source_event_id координату не двигает."""
    key = source_event_id or f"gps:{truck_id}:{recorded_at.isoformat()}"
    with _lock:
        if key in _seen_gps:
            return IngestAck(accepted=True, message="duplicate", duplicate=True, entity_id=truck_id)
    update_truck(truck_id, lat=lat, lon=lon, lat_set=True, lon_set=True)
    with _lock:
        if len(_seen_gps) >= _MAX_SEEN_GPS:
            _seen_gps.clear()
        _seen_gps.add(key)
    return IngestAck(accepted=True, message="gps accepted", entity_id=truck_id)


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
    if "stations" not in data and "trucks" not in data:
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
