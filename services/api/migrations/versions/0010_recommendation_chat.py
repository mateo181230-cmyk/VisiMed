"""Segundo chat privado para Recomendaciones; conserva visitas y preparación."""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_message",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), sa.ForeignKey("doctor.id", ondelete="SET NULL")),
        sa.Column("audience", sa.String(4), nullable=False),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("answer", sa.String(5000)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','answered','failed')", name=op.f("ck_recommendation_message_status")),
        sa.CheckConstraint("audience IN ('own','team')", name=op.f("ck_recommendation_message_audience")),
    )
    op.create_index("ix_recommendation_message_user_created", "recommendation_message", ["user_id", "audience", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_recommendation_message_user_created", table_name="recommendation_message")
    op.drop_table("recommendation_message")
