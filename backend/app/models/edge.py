"""ORM-модели реестра OTA-релизов, колец и статусов узлов station-edge."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EdgeReleaseRecord(Base):
    __tablename__ = "edge_releases"

    channel: Mapped[str] = mapped_column(String(16), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    min_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EdgeRingStationRecord(Base):
    __tablename__ = "edge_ring_stations"

    station_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    ring: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EdgeNodeStatusRecord(Base):
    __tablename__ = "edge_node_statuses"

    station_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stations.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_version: Mapped[str] = mapped_column(String(64), nullable=False)
    target_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="ring2")
    up_to_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    outbox_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_pumps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    update_status: Mapped[str] = mapped_column(String(64), nullable=False, default="ok")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
