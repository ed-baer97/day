"""Balance snapshots for physical vs calculated remainder."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BalanceSnapshot(Base):
    """Point-in-time balance: previous + receipts - dispense vs actual reading."""

    __tablename__ = "balance_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False)
    tank_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tanks.id"), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_remainder_liters: Mapped[float] = mapped_column(Float, nullable=False)
    receipts_liters: Mapped[float] = mapped_column(Float, default=0.0)
    dispense_liters: Mapped[float] = mapped_column(Float, default=0.0)
    calculated_remainder_liters: Mapped[float] = mapped_column(Float, nullable=False)
    actual_remainder_liters: Mapped[float | None] = mapped_column(Float)
    delta_liters: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="ok")  # ok | shortage | surplus | measurement_error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
