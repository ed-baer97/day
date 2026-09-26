"""AGZS station and tank models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LevelSource(str, enum.Enum):
    manual = "manual"  # mechanical float gauge reading
    electronic = "electronic"  # EX-rated industrial sensor
    calculated = "calculated"


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    balance_tolerance_liters: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tanks = relationship("Tank", back_populates="station", cascade="all, delete-orphan")
    dispensers = relationship("Dispenser", back_populates="station", cascade="all, delete-orphan")


class Tank(Base):
    __tablename__ = "tanks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    capacity_liters: Mapped[float] = mapped_column(Float, nullable=False)
    # Mechanical float remains primary physical gauge; electronic is optional.
    has_electronic_sensor: Mapped[bool] = mapped_column(Boolean, default=False)
    actual_remainder_liters: Mapped[float | None] = mapped_column(Float)
    calculated_remainder_liters: Mapped[float | None] = mapped_column(Float)
    level_source: Mapped[LevelSource] = mapped_column(
        Enum(LevelSource, name="level_source"), default=LevelSource.manual
    )
    last_measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    station = relationship("Station", back_populates="tanks")
