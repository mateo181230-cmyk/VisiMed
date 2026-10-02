"""Llamadas previas, chequeo de reuniones y plazo del resumen independiente de la visita."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_preference",
        sa.Column("call_remind_before_min", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "call", sa.Column("purpose", sa.String(20), nullable=False, server_default="summary")
    )
    with op.batch_alter_table("call") as batch:
        batch.add_column(sa.Column("reminder_key", sa.String(100), nullable=True))
        batch.create_unique_constraint("uq_call_reminder_key", ["reminder_key"])
    for name in ("report_notified_at", "report_due_at", "report_invalid_at"):
        op.add_column("visit", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("visit", sa.Column("report_mode", sa.String(12), nullable=True))


def downgrade() -> None:
    for name in ("report_mode", "report_invalid_at", "report_due_at", "report_notified_at"):
        op.drop_column("visit", name)
    with op.batch_alter_table("call") as batch:
        batch.drop_constraint("uq_call_reminder_key", type_="unique")
        batch.drop_column("reminder_key")
        batch.drop_column("purpose")
    op.drop_column("notification_preference", "call_remind_before_min")
