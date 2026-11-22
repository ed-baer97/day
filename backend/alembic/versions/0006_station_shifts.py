"""Таблица кассовых смен АГЗС (station_shifts)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_station_shifts"
down_revision: Union[str, None] = "0005_batch_trail_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "station_shifts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "station_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("opened_by", sa.String(64), nullable=False),
        sa.Column("closed_by", sa.String(64), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opening_tank_liters", sa.Float(), nullable=True),
        sa.Column("opening_tanks_json", sa.Text(), nullable=True),
        sa.Column("closing_tank_liters", sa.Float(), nullable=True),
        sa.Column("closing_tanks_json", sa.Text(), nullable=True),
        sa.Column("receipts_liters", sa.Float(), nullable=False, server_default="0"),
        sa.Column("dispensed_liters", sa.Float(), nullable=False, server_default="0"),
        sa.Column("dispense_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount_kzt", sa.Float(), nullable=True),
        sa.Column("columns_summary_json", sa.Text(), nullable=True),
        sa.Column("tank_delta_liters", sa.Float(), nullable=True),
        sa.Column("discrepancy_liters", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_station_shifts_station_opened", "station_shifts", ["station_id", "opened_at"])
    op.create_index("ix_station_shifts_station_status", "station_shifts", ["station_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_station_shifts_station_status", table_name="station_shifts")
    op.drop_index("ix_station_shifts_station_opened", table_name="station_shifts")
    op.drop_table("station_shifts")
