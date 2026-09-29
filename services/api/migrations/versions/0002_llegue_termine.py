"""llegué / terminé: hora del toque y ubicación de la llegada y del cierre en la visita

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Todas nullable: una visita agendada aún no tiene toque ni ubicación.
_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    ("arrived_at", sa.DateTime(timezone=True)),
    ("arrival_fix_ts", sa.DateTime(timezone=True)),
    ("arrival_lat", sa.Double()),
    ("arrival_lng", sa.Double()),
    ("arrival_precision_m", sa.Double()),
    ("arrival_source", sa.String(length=12)),
    ("arrival_geo_state", sa.String(length=16)),
    ("arrival_distance_m", sa.Integer()),
    ("finished_at", sa.DateTime(timezone=True)),
    ("finish_fix_ts", sa.DateTime(timezone=True)),
    ("finish_lat", sa.Double()),
    ("finish_lng", sa.Double()),
    ("finish_precision_m", sa.Double()),
    ("finish_source", sa.String(length=12)),
    ("finish_geo_state", sa.String(length=16)),
    ("finish_distance_m", sa.Integer()),
]


def upgrade() -> None:
    # ADD COLUMN nullable funciona igual en SQLite y en PostgreSQL.
    for name, type_ in _COLUMNS:
        op.add_column("visit", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    # SQLite no borra columnas con ALTER TABLE (según su versión): el modo «batch» reconstruye
    # la tabla allí y en PostgreSQL emite los DROP COLUMN normales.
    with op.batch_alter_table("visit") as batch:
        for name, _ in reversed(_COLUMNS):
            batch.drop_column(name)
