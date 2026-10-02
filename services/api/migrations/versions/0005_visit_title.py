"""Título opcional de una cita, separado de la identidad del médico."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visit", sa.Column("title", sa.String(160), nullable=True))


def downgrade() -> None:
    op.drop_column("visit", "title")
