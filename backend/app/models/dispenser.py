"""Транзакции отпуска (ТРК / АСКА-02) и приёмки (слив газовозов) с ключами идемпотентности."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DispenseRecord(Base):
    """Запись завершённого отпуска газа через ТРК (УЗГС-01 / АСКА-02, только чтение)."""

    __tablename__ = "dispense_records"
    __table_args__ = (
        Index("ix_dispense_records_tank_started", "tank_id", "started_at"),
        Index("ix_dispense_records_station_started", "station_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    tank_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tanks.id", ondelete="SET NULL")
    )
    dispenser_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    volume_liters: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_txn_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    raw_payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReceiptRecord(Base):
    """Запись приёмки (слива партии газа в резервуар АГЗС)."""

    __tablename__ = "receipt_records"
    __table_args__ = (
        Index("ix_receipt_records_tank_recorded", "tank_id", "recorded_at"),
        Index("ix_receipt_records_station_recorded", "station_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    tank_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tanks.id", ondelete="CASCADE"), nullable=False
    )
    volume_liters: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
