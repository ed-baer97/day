"""Discrepancy / anomaly events from balance reconciliation."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DiscrepancyType(str, enum.Enum):
    shortage = "shortage"
    surplus = "surplus"
    measurement_error = "measurement_error"
    unregistered_receipt = "unregistered_receipt"
    unregistered_dispense = "unregistered_dispense"


class DiscrepancySeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class DiscrepancyEvent(Base):
    __tablename__ = "discrepancy_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False)
    tank_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tanks.id"))
    balance_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("balance_snapshots.id")
    )
    event_type: Mapped[DiscrepancyType] = mapped_column(
        Enum(DiscrepancyType, name="discrepancy_type"), nullable=False
    )
    severity: Mapped[DiscrepancySeverity] = mapped_column(
        Enum(DiscrepancySeverity, name="discrepancy_severity"), default=DiscrepancySeverity.warning
    )
    delta_liters: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
