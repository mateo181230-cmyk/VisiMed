"""Imported doctor-site contacts and independently confirmed receiving hours."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    data_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "panel_contact",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("representative_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), sa.ForeignKey("doctor.id"), nullable=False),
        sa.Column("institution_id", sa.Uuid(), sa.ForeignKey("institution.id"), nullable=False),
        sa.Column("source_key", sa.String(120), nullable=False, unique=True),
        sa.Column("data", data_type, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("representative_id", "doctor_id", "institution_id"):
        op.create_index("ix_panel_contact_" + col, "panel_contact", [col])
    op.create_table(
        "reception_availability",
        sa.Column("doctor_id", sa.Uuid(), sa.ForeignKey("doctor.id"), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), sa.ForeignKey("institution.id"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", data_type, nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("visit_requirement") as batch:
        batch.add_column(sa.Column("institution_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_visit_requirement_institution_id_institution",
            "institution",
            ["institution_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("visit_requirement") as batch:
        batch.drop_constraint("fk_visit_requirement_institution_id_institution", type_="foreignkey")
        batch.drop_column("institution_id")
    op.drop_table("reception_availability")
    op.drop_table("panel_contact")
