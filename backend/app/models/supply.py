"""LPG supply — one shipment linking factory, truck, station, tank and volumes."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SupplyStatus(str, enum.Enum):
    loading = "loading"
    in_transit = "in_transit"
    unloading = "unloading"
    accepted = "accepted"
    selling = "selling"
    closed = "closed"


class Supply(Base):
    """Поставка LPG. Все объёмы цепочки относятся к одному supply_id."""

    __tablename__ = "supplies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supply_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[SupplyStatus] = mapped_column(
        Enum(SupplyStatus, name="supply_status"), default=SupplyStatus.loading
    )
    factory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("factories.id"))
    truck_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id"))
    station_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stations.id"))
    tank_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tanks.id"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("batches.id"))
    waybill: Mapped[str | None] = mapped_column(String(64))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_liters: Mapped[float | None] = mapped_column(Float)
    delivered_liters: Mapped[float | None] = mapped_column(Float)
    accepted_liters: Mapped[float | None] = mapped_column(Float)
    dispensed_liters: Mapped[float | None] = mapped_column(Float)
    fiscal_liters: Mapped[float | None] = mapped_column(Float)
    shipped_temp_c: Mapped[float | None] = mapped_column(Float)
    delivered_temp_c: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
