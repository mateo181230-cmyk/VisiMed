"""Marketing activities linked to the existing territory and management reporting."""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = depends_on = None


def upgrade():
    from uno.modules.marketing.models import MarketingActivity, MarketingRevision

    for model in (MarketingActivity, MarketingRevision):
        model.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("marketing_revision")
    op.drop_table("marketing_activity")
