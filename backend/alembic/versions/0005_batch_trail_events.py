"""Таблица узлов цифрового следа партий и индекс статуса партий."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_batch_trail_events"
down_revision: Union[str, None] = "0004_station_columns_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_batches_status_formed_at", "batches", ["status", "formed_at"])
    op.create_table(
        "batch_trail_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ref_entity_type", sa.String(64), nullable=True),
        sa.Column("ref_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("volume_liters", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_batch_trail_events_batch_occurred",
        "batch_trail_events",
        ["batch_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_batch_trail_events_batch_occurred", table_name="batch_trail_events")
    op.drop_table("batch_trail_events")
    op.drop_index("ix_batches_status_formed_at", table_name="batches")
