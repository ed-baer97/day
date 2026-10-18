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
    lat: float | None = None
    lon: float | None = None


class TruckCreate(BaseModel):
    plate_number: str = Field(min_length=1, max_length=32)
    capacity_liters: float = Field(gt=0)
    carrier_name: str | None = None
    status: str = "idle"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class TruckUpdate(BaseModel):
    plate_number: str | None = Field(default=None, min_length=1, max_length=32)
    capacity_liters: float | None = Field(default=None, gt=0)
    carrier_name: str | None = None
    status: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


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
