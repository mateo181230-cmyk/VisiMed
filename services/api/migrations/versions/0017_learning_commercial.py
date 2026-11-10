"""Contextual learning and traceable commercial cuts."""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = depends_on = None


def upgrade():
    from uno.modules.workflows.models import VisitLearning
    from uno.modules.marketing.models import CommercialBatch
    for model in (VisitLearning, CommercialBatch):
        model.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("commercial_batch")
    op.drop_table("visit_learning")
