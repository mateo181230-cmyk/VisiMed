"""Conversaciones independientes; conserva los mensajes anteriores en el historial."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conversations = op.create_table(
        "recommendation_conversation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("doctor_id", sa.Uuid(), sa.ForeignKey("doctor.id", ondelete="SET NULL")),
        sa.Column("audience", sa.String(4), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "audience IN ('own','team')", name=op.f("ck_recommendation_conversation_audience")
        ),
    )
    op.create_index(
        "ix_recommendation_conversation_user_updated",
        "recommendation_conversation",
        ["user_id", "audience", "updated_at"],
    )
    op.add_column("recommendation_message", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    messages = sa.Table(
        "recommendation_message",
        sa.MetaData(),
        sa.Column("conversation_id", sa.Uuid()),
        autoload_with=op.get_bind(),
    )
    rows = (
        op.get_bind()
        .execute(sa.select(messages).order_by(messages.c.created_at, messages.c.request_id))
        .mappings()
        .all()
    )
    groups = {}
    for row in rows:
        key = (row["user_id"], row["audience"], row["doctor_id"])
        groups.setdefault(key, []).append(row)
    for (user_id, audience, doctor_id), history in groups.items():
        conversation_id = uuid.uuid4()
        op.get_bind().execute(
            conversations.insert().values(
                id=conversation_id,
                user_id=uuid.UUID(str(user_id)),
                audience=audience,
                doctor_id=uuid.UUID(str(doctor_id)) if doctor_id else None,
                title=" ".join(history[0]["question"].split())[:80],
                created_at=history[0]["created_at"],
                updated_at=max(row["updated_at"] for row in history),
            )
        )
        op.get_bind().execute(
            messages.update()
            .where(messages.c.request_id.in_([row["request_id"] for row in history]))
            .values(conversation_id=conversation_id)
        )
    with op.batch_alter_table("recommendation_message") as batch:
        batch.alter_column("conversation_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            op.f("fk_recommendation_message_conversation_id_recommendation_conversation"),
            "recommendation_conversation",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_recommendation_message_conversation_created", ["conversation_id", "created_at"]
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendation_message") as batch:
        batch.drop_index("ix_recommendation_message_conversation_created")
        batch.drop_constraint(
            op.f("fk_recommendation_message_conversation_id_recommendation_conversation"),
            type_="foreignkey",
        )
        batch.drop_column("conversation_id")
    op.drop_index(
        "ix_recommendation_conversation_user_updated", table_name="recommendation_conversation"
    )
    op.drop_table("recommendation_conversation")
