"""Truck schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TruckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plate_number: str
    capacity_liters: float
    carrier_name: str | None
    status: str


class TruckTripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID | None
    origin_factory_id: UUID | None
    destination_station_id: UUID | None
    loaded_volume_liters: float | None
    loaded_mass_kg: float | None
    status: str
    departed_at: datetime | None
    arrived_at: datetime | None


class TruckDetailOut(TruckOut):
    lat: float | None = None
    lon: float | None = None
    recorded_at: datetime | None = None
    supplier_name: str | None = None
    origin_name: str | None = None
    destination_name: str | None = None
    cargo_volume_liters: float | None = None
    departed_at: datetime | None = None
    arrived_at: datetime | None = None
    trip_status: str | None = None
    route_geojson: str | None = None
    active_trip: TruckTripOut | None = None
    recent_positions: list[dict] = Field(default_factory=list)
