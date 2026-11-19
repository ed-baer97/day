"""Добавление настройки режима колонок (виртуальные / реальные edge / отключены) для АГЗС."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_station_columns_config"
down_revision: Union[str, None] = "0003_high_scale_ingest_and_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stations",
        sa.Column("columns_mode", sa.String(16), nullable=False, server_default="none"),
    )
    op.add_column(
        "stations",
        sa.Column("columns_count", sa.Integer(), nullable=False, server_default="2"),
    )
    op.execute(
        """
        UPDATE stations
        SET columns_mode = 'virtual', columns_count = 2
        WHERE lower(code) IN ('agzs-akt-12', 'akt-12mkr')
           OR lower(name) LIKE '%rekon%'
        """
    )


def downgrade() -> None:
    op.drop_column("stations", "columns_count")
    op.drop_column("stations", "columns_mode")
