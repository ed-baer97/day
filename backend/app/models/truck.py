"""Gas truck and trips."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TripStatus(str, enum.Enum):
    loading = "loading"
    in_transit = "in_transit"
    arrived = "arrived"
    unloading = "unloading"
    completed = "completed"
    cancelled = "cancelled"


class Truck(Base):
    __tablename__ = "trucks"
    __table_args__ = (
        Index("ix_trucks_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    capacity_liters: Mapped[float] = mapped_column(Float, nullable=False)
    carrier_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="idle")
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trips = relationship("TruckTrip", back_populates="truck", cascade="all, delete-orphan")


class TruckTrip(Base):
    __tablename__ = "truck_trips"
    __table_args__ = (
        Index("ix_truck_trips_truck_status", "truck_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("batches.id"))
    origin_factory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    destination_station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id")
    )
    loaded_volume_liters: Mapped[float | None] = mapped_column(Float)
    loaded_mass_kg: Mapped[float | None] = mapped_column(Float)
    status: Mapped[TripStatus] = mapped_column(
        Enum(TripStatus, name="trip_status"), default=TripStatus.loading
    )
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    route_geojson: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    truck = relationship("Truck", back_populates="trips")
