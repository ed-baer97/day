"""Модель кассовой смены АГЗС."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StationShiftRecord(Base):
    __tablename__ = "station_shifts"
    __table_args__ = (
        Index("ix_station_shifts_station_opened", "station_id", "opened_at"),
        Index("ix_station_shifts_station_status", "station_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    opened_by: Mapped[str] = mapped_column(String(64), nullable=False)
    closed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opening_tank_liters: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_tanks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    closing_tank_liters: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_tanks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipts_liters: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dispensed_liters: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dispense_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    columns_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tank_delta_liters: Mapped[float | None] = mapped_column(Float, nullable=True)
    discrepancy_liters: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
