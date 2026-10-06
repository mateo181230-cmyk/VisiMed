"""llamadas de resumen y fichas de visita

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28 23:40:16.147006
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('call',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('representative_id', sa.Uuid(), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_closing', sa.Boolean(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_conversation_id', sa.String(length=80), nullable=True),
    sa.Column('provider_call_id', sa.String(length=80), nullable=True),
    sa.Column('dialed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_s', sa.Integer(), nullable=True),
    sa.Column('failure_reason', sa.String(length=30), nullable=True),
    sa.Column('transcript', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('analysis', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('summary', sa.String(length=2000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("direction IN ('outbound','inbound')", name=op.f('ck_call_direction')),
    sa.CheckConstraint("status IN ('queued','dialing','completed','failed','cancelled')", name=op.f('ck_call_status')),
    sa.ForeignKeyConstraint(['representative_id'], ['app_user.id'], name=op.f('fk_call_representative_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_call')),
    sa.UniqueConstraint('provider_conversation_id', name=op.f('uq_call_provider_conversation_id'))
    )
    op.create_index(op.f('ix_call_representative_id'), 'call', ['representative_id'], unique=False)
    op.create_index('ix_call_status_scheduled', 'call', ['status', 'scheduled_for'], unique=False)
    op.create_table('call_visit',
    sa.Column('call_id', sa.Uuid(), nullable=False),
    sa.Column('visit_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('live', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['call_id'], ['call.id'], name=op.f('fk_call_visit_call_id_call'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['visit_id'], ['visit.id'], name=op.f('fk_call_visit_visit_id_visit')),
    sa.PrimaryKeyConstraint('call_id', 'visit_id', name=op.f('pk_call_visit')),
    sa.UniqueConstraint('call_id', 'position', name='uq_call_visit_call_id_position')
    )
    op.create_index('uq_call_visit_live', 'call_visit', ['visit_id'], unique=True, postgresql_where=sa.text('live'), sqlite_where=sa.text('live'))
    op.create_table('visit_report',
    sa.Column('visit_id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('fields', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('complete', sa.Boolean(), nullable=False),
    sa.Column('problems', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('extractor_version', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('change_seq', sa.Integer(), nullable=False),
    sa.CheckConstraint("status IN ('ready','confirmed')", name=op.f('ck_visit_report_status')),
    sa.ForeignKeyConstraint(['call_id'], ['call.id'], name=op.f('fk_visit_report_call_id_call'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['visit_id'], ['visit.id'], name=op.f('fk_visit_report_visit_id_visit')),
    sa.PrimaryKeyConstraint('visit_id', name=op.f('pk_visit_report'))
    )
    op.create_index('ix_visit_report_change', 'visit_report', ['change_seq'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_visit_report_change', table_name='visit_report')
    op.drop_table('visit_report')
    op.drop_index('uq_call_visit_live', table_name='call_visit', postgresql_where=sa.text('live'), sqlite_where=sa.text('live'))
    op.drop_table('call_visit')
    op.drop_index('ix_call_status_scheduled', table_name='call')
    op.drop_index(op.f('ix_call_representative_id'), table_name='call')
    op.drop_table('call')
