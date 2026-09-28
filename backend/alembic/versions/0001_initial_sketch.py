"""Initial schema sketch — create domain tables.

Run after Postgres is up:
  alembic revision --autogenerate -m "initial"
  alembic upgrade head

This file is a hand-written sketch of the target schema for MVP-1.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_sketch"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("contact", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "factories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "stations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("balance_tolerance_liters", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "tanks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("station_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stations.id"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("capacity_liters", sa.Float(), nullable=False),
        sa.Column("has_electronic_sensor", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("actual_remainder_liters", sa.Float()),
        sa.Column("calculated_remainder_liters", sa.Float()),
        sa.Column("level_source", sa.String(32), server_default="manual"),
        sa.Column("last_measured_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "trucks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plate_number", sa.String(32), unique=True, nullable=False),
        sa.Column("capacity_liters", sa.Float(), nullable=False),
        sa.Column("carrier_name", sa.String(255)),
        sa.Column("status", sa.String(32), server_default="idle"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trail_code", sa.String(64), unique=True, nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id")),
        sa.Column("factory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("factories.id")),
        sa.Column("product_grade", sa.String(64)),
        sa.Column("density_kg_per_liter", sa.Float()),
        sa.Column("volume_liters", sa.Float(), nullable=False),
        sa.Column("mass_kg", sa.Float()),
        sa.Column("status", sa.String(32), server_default="formed"),
        sa.Column("formed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "supplies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supply_id", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.String(32), server_default="loading"),
        sa.Column("factory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("factories.id")),
        sa.Column("truck_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trucks.id")),
        sa.Column("station_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stations.id")),
        sa.Column("tank_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tanks.id")),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id")),
        sa.Column("waybill", sa.String(64)),
        sa.Column("shipped_at", sa.DateTime(timezone=True)),
        sa.Column("shipped_liters", sa.Float()),
        sa.Column("delivered_liters", sa.Float()),
        sa.Column("accepted_liters", sa.Float()),
        sa.Column("dispensed_liters", sa.Float()),
        sa.Column("fiscal_liters", sa.Float()),
        sa.Column("shipped_temp_c", sa.Float()),
        sa.Column("delivered_temp_c", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Remaining tables (dispensers, dispense_records, trips, positions,
    # trail_events, balance_snapshots, discrepancy_events, sales) —
    # see SQLAlchemy models in app/models/; autogenerate in MVP-1.


def downgrade() -> None:
    op.drop_table("supplies")
    op.drop_table("batches")
    op.drop_table("trucks")
    op.drop_table("tanks")
    op.drop_table("stations")
    op.drop_table("factories")
    op.drop_table("suppliers")
