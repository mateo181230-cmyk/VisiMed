"""Pilot management profiles, sourced presentations and commercial cycles."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    with op.batch_alter_table("app_user") as batch:
        batch.add_column(sa.Column("management_profile", sa.String(20), nullable=True))
        batch.add_column(sa.Column("pilot_scope", json_type, nullable=True))
    op.create_table(
        "product_presentation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("product.id"), nullable=False),
        sa.Column("barcode", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("pack_units", sa.Integer(), nullable=True),
        sa.Column("sale_class", sa.String(20), nullable=True),
        sa.Column("source", json_type, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("change_seq", sa.Integer(), nullable=False),
    )
    op.create_index("ix_product_presentation_product_id", "product_presentation", ["product_id"])
    op.create_table(
        "commercial_cycle",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(24), nullable=False, unique=True),
        sa.Column("line_id", sa.Uuid(), sa.ForeignKey("product_line.id"), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("working_days", sa.Integer(), nullable=False),
        sa.Column("source", json_type, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_commercial_cycle_line_id", "commercial_cycle", ["line_id"])


def downgrade():
    op.drop_table("commercial_cycle")
    op.drop_table("product_presentation")
    with op.batch_alter_table("app_user") as batch:
        batch.drop_column("pilot_scope")
        batch.drop_column("management_profile")
