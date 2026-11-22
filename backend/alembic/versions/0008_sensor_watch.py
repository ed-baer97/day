"""Окно наблюдения датчика резервуара: якорь для слива без документа и ухода без колонки."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_sensor_watch"
down_revision: Union[str, None] = "0007_edge_fleet"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tanks", sa.Column("sensor_watch_liters", sa.Float(), nullable=True))
    op.add_column("tanks", sa.Column("sensor_watch_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tanks",
        sa.Column("sensor_watch_receipts", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tanks",
        sa.Column("sensor_watch_dispense", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tanks", "sensor_watch_dispense")
    op.drop_column("tanks", "sensor_watch_receipts")
    op.drop_column("tanks", "sensor_watch_at")
    op.drop_column("tanks", "sensor_watch_liters")
