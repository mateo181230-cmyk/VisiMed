"""Reservas atómicas de autenticación y cuotas separadas para registro."""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_attempt_lock",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("touched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_auth_attempt_lock")),
    )
    op.create_index("ix_auth_attempt_lock_touched_at", "auth_attempt_lock", ["touched_at"])
    op.add_column(
        "login_attempt", sa.Column("purpose", sa.String(12), nullable=False, server_default="login")
    )
    op.add_column(
        "login_attempt", sa.Column("finished", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "login_attempt",
        sa.Column("counts_for_phone", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_login_attempt_purpose_ip_at", "login_attempt", ["purpose", "ip", "at"]
    )
    # Respeta los reinicios del contador anteriores al despliegue. Con hora idéntica
    # se conserva el fallo, pues el registro histórico no permite conocer su orden.
    op.execute(
        "UPDATE login_attempt SET counts_for_phone = false WHERE success = false AND at < "
        "(SELECT MAX(ok.at) FROM login_attempt AS ok "
        "WHERE ok.phone = login_attempt.phone AND ok.success = true)"
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempt_purpose_ip_at", table_name="login_attempt")
    with op.batch_alter_table("login_attempt") as batch:
        batch.drop_column("counts_for_phone")
        batch.drop_column("finished")
        batch.drop_column("purpose")
    op.drop_index("ix_auth_attempt_lock_touched_at", table_name="auth_attempt_lock")
    op.drop_table("auth_attempt_lock")
