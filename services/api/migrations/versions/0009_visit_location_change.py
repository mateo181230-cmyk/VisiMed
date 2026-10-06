"""Conserva el punto planeado al aceptar una ubicación distinta para una visita."""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visit", sa.Column("location_changed_at", sa.DateTime(timezone=True)))
    op.add_column("visit", sa.Column("location_change_label", sa.String(160)))
    op.add_column("visit", sa.Column("planned_location_name", sa.String(160)))
    op.add_column("visit", sa.Column("planned_location_lat", sa.Double()))
    op.add_column("visit", sa.Column("planned_location_lng", sa.Double()))
    op.add_column("visit", sa.Column("planned_location_radius_m", sa.Integer()))


def downgrade() -> None:
    with op.batch_alter_table("visit") as batch:
        for name in (
            "planned_location_radius_m",
            "planned_location_lng",
            "planned_location_lat",
            "planned_location_name",
            "location_change_label",
            "location_changed_at",
        ):
            batch.drop_column(name)
