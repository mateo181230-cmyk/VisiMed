"""Preparación persistente, consultas privadas y aviso de la agenda de mañana."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visit_preparation",
        sa.Column(
            "visit_id", sa.Uuid(), sa.ForeignKey("visit.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("objective", sa.String(500)),
        sa.Column("rep_commitment", sa.String(500)),
        sa.Column("objective_edited", sa.Boolean(), nullable=False),
        sa.Column("rep_commitment_edited", sa.Boolean(), nullable=False),
        sa.Column("active_seconds", sa.Integer(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True)),
        sa.Column("prepared_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("active_seconds >= 0", name=op.f("ck_visit_preparation_active_seconds")),
    )
    op.create_table(
        "preparation_activity",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "visit_id", sa.Uuid(), sa.ForeignKey("visit.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_seconds", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "seconds >= 0 AND seconds <= 60", name=op.f("ck_preparation_activity_seconds")
        ),
    )
    op.create_index(
        "ix_preparation_activity_visit_start", "preparation_activity", ["visit_id", "started_at"]
    )
    op.create_table(
        "preparation_message",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "visit_id", sa.Uuid(), sa.ForeignKey("visit.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("answer", sa.String(5000)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','answered','failed')", name=op.f("ck_preparation_message_status")
        ),
    )
    op.create_index(
        "ix_preparation_message_visit_created", "preparation_message", ["visit_id", "created_at"]
    )
    op.add_column(
        "notification_preference",
        sa.Column("preparation_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "notification_preference",
        sa.Column("preparation_time", sa.String(5), nullable=False, server_default="18:30"),
    )


def downgrade() -> None:
    with op.batch_alter_table("notification_preference") as batch:
        batch.drop_column("preparation_time")
        batch.drop_column("preparation_enabled")
    op.drop_index("ix_preparation_message_visit_created", table_name="preparation_message")
    op.drop_table("preparation_message")
    op.drop_index("ix_preparation_activity_visit_start", table_name="preparation_activity")
    op.drop_table("preparation_activity")
    op.drop_table("visit_preparation")
