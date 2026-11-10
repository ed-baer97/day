"""AGZS station, tank, level reading, and station user models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LevelSource(str, enum.Enum):
    manual = "manual"  # mechanical float gauge reading
    electronic = "electronic"  # EX-rated industrial sensor
    calculated = "calculated"


class Station(Base):
    __tablename__ = "stations"
    __table_args__ = (
        Index("ix_stations_is_active", "is_active"),
    )

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


class Tank(Base):
    __tablename__ = "tanks"
    __table_args__ = (
        UniqueConstraint("station_id", "code", name="uq_tanks_station_code"),
        Index("ix_tanks_station_id", "station_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    capacity_liters: Mapped[float] = mapped_column(Float, nullable=False)
    has_electronic_sensor: Mapped[bool] = mapped_column(Boolean, default=False)
    actual_remainder_liters: Mapped[float | None] = mapped_column(Float)
    calculated_remainder_liters: Mapped[float | None] = mapped_column(Float)
    level_source: Mapped[LevelSource] = mapped_column(
        Enum(LevelSource, name="level_source", native_enum=False), default=LevelSource.manual
    )
    last_measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingest_token: Mapped[str | None] = mapped_column(String(128), unique=True)
    cal_low_volts: Mapped[float | None] = mapped_column(Float)
    cal_low_percent: Mapped[float | None] = mapped_column(Float)
    cal_high_volts: Mapped[float | None] = mapped_column(Float)
    cal_high_percent: Mapped[float | None] = mapped_column(Float)
    opening_liters: Mapped[float | None] = mapped_column(Float)
    receipts_liters: Mapped[float] = mapped_column(Float, default=0.0)
    dispense_liters: Mapped[float] = mapped_column(Float, default=0.0)
    pending_dispense_liters: Mapped[float] = mapped_column(Float, default=0.0)
    pending_receipt_liters: Mapped[float] = mapped_column(Float, default=0.0)
    last_volts: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    station = relationship("Station", back_populates="tanks")
    readings = relationship("LevelReading", back_populates="tank", cascade="all, delete-orphan")


class LevelReading(Base):
    __tablename__ = "level_readings"
    __table_args__ = (
        Index("ix_level_readings_tank_recorded", "tank_id", "recorded_at"),
        Index("ix_level_readings_station_recorded", "station_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tank_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tanks.id", ondelete="CASCADE"), nullable=False
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    volts: Mapped[float | None] = mapped_column(Float)
    remainder_liters: Mapped[float] = mapped_column(Float, nullable=False)
    fill_percent: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tank = relationship("Tank", back_populates="readings")


class StationUser(Base):
    __tablename__ = "station_users"
    __table_args__ = (
        UniqueConstraint("station_id", "username", name="uq_station_users_station_username"),
        Index("ix_station_users_username", "username"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
