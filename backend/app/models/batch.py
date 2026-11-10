"""LPG batch and digital trail events."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BatchStatus(str, enum.Enum):
    formed = "formed"
    in_transit = "in_transit"
    delivered = "delivered"
    partially_sold = "partially_sold"
    closed = "closed"


class TrailNodeType(str, enum.Enum):
    supplier = "supplier"
    factory = "factory"
    batch = "batch"
    truck = "truck"
    route = "route"
    station = "station"
    tank = "tank"
    dispense = "dispense"
    sale = "sale"


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        Index("ix_batches_status_formed_at", "status", "formed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trail_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    factory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    product_grade: Mapped[str | None] = mapped_column(String(64))
    density_kg_per_liter: Mapped[float | None] = mapped_column(Float)
    volume_liters: Mapped[float] = mapped_column(Float, nullable=False)
    mass_kg: Mapped[float | None] = mapped_column(Float)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="batch_status"), default=BatchStatus.formed
    )
    formed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trail_events = relationship("BatchTrailEvent", back_populates="batch", cascade="all, delete-orphan")


class BatchTrailEvent(Base):
    """Chronological nodes of the digital trail for a batch."""

    __tablename__ = "batch_trail_events"
    __table_args__ = (
        Index("ix_batch_trail_events_batch_occurred", "batch_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    node_type: Mapped[TrailNodeType] = mapped_column(
        Enum(TrailNodeType, name="trail_node_type"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    ref_entity_type: Mapped[str | None] = mapped_column(String(64))
    ref_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    volume_liters: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("Batch", back_populates="trail_events")
