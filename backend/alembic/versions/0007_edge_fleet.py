"""Таблицы парка и OTA-релизов station-edge (edge_releases, edge_ring_stations, edge_node_statuses)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_edge_fleet"
down_revision: Union[str, None] = "0006_station_shifts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "edge_releases",
        sa.Column("channel", sa.String(16), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("artifact_url", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("min_version", sa.String(64), nullable=True),
        sa.Column("notes", sa.String(1024), nullable=False, server_default=""),
        sa.Column("signature", sa.String(256), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "edge_ring_stations",
        sa.Column("station_code", sa.String(64), primary_key=True),
        sa.Column("ring", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edge_ring_stations_ring", "edge_ring_stations", ["ring"])

    op.create_table(
        "edge_node_statuses",
        sa.Column("station_code", sa.String(64), primary_key=True),
        sa.Column(
            "station_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("current_version", sa.String(64), nullable=False),
        sa.Column("target_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("channel", sa.String(16), nullable=False, server_default="ring2"),
        sa.Column("up_to_date", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("outbox_pending", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_pumps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("update_status", sa.String(64), nullable=False, server_default="ok"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("edge_node_statuses")
    op.drop_index("ix_edge_ring_stations_ring", table_name="edge_ring_stations")
    op.drop_table("edge_ring_stations")
    op.drop_table("edge_releases")
