"""Таблицы транзакций отпуска и приёмки с идемпотентностью, координаты газовозов и индексы масштабирования."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_high_scale_ingest_and_cleanup"
down_revision: Union[str, None] = "0002_account_store"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Координаты газовозов и индекс по статусу
    op.add_column("trucks", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("trucks", sa.Column("lon", sa.Float(), nullable=True))
    op.create_index("ix_trucks_status", "trucks", ["status"])

    # Индексы для быстрых выборок станций, резервуаров и замеров без Seq Scan
    op.create_index("ix_stations_is_active", "stations", ["is_active"])
    op.create_index("ix_tanks_station_id", "tanks", ["station_id"])
    op.create_unique_constraint("uq_tanks_station_code", "tanks", ["station_id", "code"])
    op.create_index("ix_level_readings_station_recorded", "level_readings", ["station_id", "recorded_at"])
    op.create_index("ix_station_users_username", "station_users", ["username"])

    # Таблица транзакций отпуска газа (ТРК / АСКА-02) с идемпотентностью по external_txn_id
    op.create_table(
        "dispense_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "station_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tank_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tanks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dispenser_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("volume_liters", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_txn_id", sa.String(128), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("external_txn_id", name="uq_dispense_records_external_txn"),
    )
    op.create_index("ix_dispense_records_tank_started", "dispense_records", ["tank_id", "started_at"])
    op.create_index("ix_dispense_records_station_started", "dispense_records", ["station_id", "started_at"])

    # Таблица транзакций приёмки (слив газовоза в резервуар) с идемпотентностью по source_event_id
    op.create_table(
        "receipt_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "station_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tank_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tanks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("volume_liters", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_event_id", name="uq_receipt_records_source_event"),
    )
    op.create_index("ix_receipt_records_tank_recorded", "receipt_records", ["tank_id", "recorded_at"])
    op.create_index("ix_receipt_records_station_recorded", "receipt_records", ["station_id", "recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_receipt_records_station_recorded", table_name="receipt_records")
    op.drop_index("ix_receipt_records_tank_recorded", table_name="receipt_records")
    op.drop_table("receipt_records")

    op.drop_index("ix_dispense_records_station_started", table_name="dispense_records")
    op.drop_index("ix_dispense_records_tank_started", table_name="dispense_records")
    op.drop_table("dispense_records")

    op.drop_index("ix_station_users_username", table_name="station_users")
    op.drop_index("ix_level_readings_station_recorded", table_name="level_readings")
    op.drop_constraint("uq_tanks_station_code", "tanks", type_="unique")
    op.drop_index("ix_tanks_station_id", table_name="tanks")
    op.drop_index("ix_stations_is_active", table_name="stations")

    op.drop_index("ix_trucks_status", table_name="trucks")
    op.drop_column("trucks", "lon")
    op.drop_column("trucks", "lat")
