"""Учёт станций и резервуаров: токен, шкала, книга, замеры, вход АГЗС."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_account_store"
down_revision: Union[str, None] = "0001_initial_sketch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tanks", sa.Column("ingest_token", sa.String(128), nullable=True))
    op.add_column("tanks", sa.Column("cal_low_volts", sa.Float(), nullable=True))
    op.add_column("tanks", sa.Column("cal_low_percent", sa.Float(), nullable=True))
    op.add_column("tanks", sa.Column("cal_high_volts", sa.Float(), nullable=True))
    op.add_column("tanks", sa.Column("cal_high_percent", sa.Float(), nullable=True))
    op.add_column("tanks", sa.Column("opening_liters", sa.Float(), nullable=True))
    op.add_column("tanks", sa.Column("receipts_liters", sa.Float(), server_default="0", nullable=False))
    op.add_column("tanks", sa.Column("dispense_liters", sa.Float(), server_default="0", nullable=False))
    op.add_column("tanks", sa.Column("pending_dispense_liters", sa.Float(), server_default="0", nullable=False))
    op.add_column("tanks", sa.Column("pending_receipt_liters", sa.Float(), server_default="0", nullable=False))
    op.add_column("tanks", sa.Column("last_volts", sa.Float(), nullable=True))
    op.create_index("ix_tanks_ingest_token", "tanks", ["ingest_token"], unique=True)

    op.create_table(
        "level_readings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tank_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tanks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("station_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("volts", sa.Float(), nullable=True),
        sa.Column("remainder_liters", sa.Float(), nullable=False),
        sa.Column("fill_percent", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_event_id", name="uq_level_readings_source_event"),
    )
    op.create_index("ix_level_readings_tank_recorded", "level_readings", ["tank_id", "recorded_at"])

    op.create_table(
        "station_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("station_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), server_default="owner", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("station_id", "username", name="uq_station_users_station_username"),
    )


def downgrade() -> None:
    op.drop_table("station_users")
    op.drop_index("ix_level_readings_tank_recorded", table_name="level_readings")
    op.drop_table("level_readings")
    op.drop_index("ix_tanks_ingest_token", table_name="tanks")
    op.drop_column("tanks", "last_volts")
    op.drop_column("tanks", "pending_receipt_liters")
    op.drop_column("tanks", "pending_dispense_liters")
    op.drop_column("tanks", "dispense_liters")
    op.drop_column("tanks", "receipts_liters")
    op.drop_column("tanks", "opening_liters")
    op.drop_column("tanks", "cal_high_percent")
    op.drop_column("tanks", "cal_high_volts")
    op.drop_column("tanks", "cal_low_percent")
    op.drop_column("tanks", "cal_low_volts")
    op.drop_column("tanks", "ingest_token")
