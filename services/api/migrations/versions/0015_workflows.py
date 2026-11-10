"""Pending reports, actionable commitments and versioned knowledge."""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "visit", sa.Column("report_pending_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE visit SET report_pending_at = report_invalid_at, report_invalid_at = NULL WHERE report_invalid_at IS NOT NULL"
    )
    # These tables have no predecessors; create with the same portable SQL types as runtime.
    from uno.modules.workflows.models import FollowupTask, RouteIncident, KnowledgeDocument

    for model in (FollowupTask, RouteIncident, KnowledgeDocument):
        model.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    for table in ("knowledge_document", "route_incident", "followup_task"):
        op.drop_table(table)
    op.drop_column("visit", "report_pending_at")
