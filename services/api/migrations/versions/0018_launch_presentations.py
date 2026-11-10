"""Preserve unknown barcodes for source-approved launch presentations."""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("product_presentation") as batch:
        batch.alter_column("barcode", existing_type=sa.String(32), nullable=True)


def downgrade():
    # Do not invent barcodes or delete launch presentations during a rollback.
    missing = op.get_bind().scalar(sa.text("SELECT count(*) FROM product_presentation WHERE barcode IS NULL"))
    if missing:
        raise RuntimeError("Supply verified barcodes before downgrading launch presentations")
    with op.batch_alter_table("product_presentation") as batch:
        batch.alter_column("barcode", existing_type=sa.String(32), nullable=False)
