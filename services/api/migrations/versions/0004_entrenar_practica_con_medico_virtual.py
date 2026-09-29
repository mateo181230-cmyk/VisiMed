"""entrenar: práctica con médico virtual (perfil, formulario, versiones publicadas, prácticas, turnos y evaluaciones)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29 02:04:24.133789
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('training_scenario_version',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scenario_slug', sa.String(length=60), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('prompt_version', sa.String(length=20), nullable=False),
    sa.Column('tavus_pal_id', sa.String(length=40), nullable=True),
    sa.Column('face_id', sa.String(length=40), nullable=False),
    sa.Column('voice_id', sa.String(length=60), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_training_scenario_version')),
    sa.UniqueConstraint('scenario_slug', 'version', name='uq_training_scenario_version_slug_ver')
    )
    op.create_index('ix_training_scenario_version_hash', 'training_scenario_version', ['scenario_slug', 'content_hash'], unique=False)
    op.create_table('practice_attempt',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('scenario_slug', sa.String(length=60), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('provider', sa.String(length=12), nullable=False),
    sa.Column('conversation_id', sa.String(length=80), nullable=True),
    sa.Column('conversation_url', sa.String(length=300), nullable=True),
    sa.Column('webhook_token_hash', sa.String(length=64), nullable=True),
    sa.Column('audio_only', sa.Boolean(), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('greeting', sa.String(length=200), nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('end_reason', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('starting','live','ended','evaluated','failed','no_transcript')", name=op.f('ck_practice_attempt_status')),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_practice_attempt_user_id_app_user'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['training_scenario_version.id'], name=op.f('fk_practice_attempt_version_id_training_scenario_version'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_attempt')),
    sa.UniqueConstraint('conversation_id', name=op.f('uq_practice_attempt_conversation_id')),
    sa.UniqueConstraint('webhook_token_hash', name=op.f('uq_practice_attempt_webhook_token_hash'))
    )
    op.create_index('ix_practice_attempt_status', 'practice_attempt', ['status'], unique=False)
    op.create_index('ix_practice_attempt_user_scenario', 'practice_attempt', ['user_id', 'scenario_slug', 'created_at'], unique=False)
    op.create_index('uq_practice_attempt_active', 'practice_attempt', ['user_id'], unique=True, postgresql_where=sa.text("status IN ('starting','live')"), sqlite_where=sa.text("status IN ('starting','live')"))
    op.create_table('training_profile',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('salutation', sa.String(length=10), nullable=False),
    sa.Column('consent_version', sa.String(length=40), nullable=True),
    sa.Column('consent_accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("salutation IN ('doctor','doctora')", name=op.f('ck_training_profile_salutation')),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_training_profile_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_training_profile'))
    )
    op.create_table('training_quiz_result',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('scenario_slug', sa.String(length=60), nullable=False),
    sa.Column('answers', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('correct', sa.Integer(), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_training_quiz_result_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_training_quiz_result'))
    )
    op.create_index('ix_training_quiz_result_user_scenario', 'training_quiz_result', ['user_id', 'scenario_slug', 'created_at'], unique=False)
    op.create_table('practice_evaluation',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('attempt_id', sa.Uuid(), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('band', sa.String(length=20), nullable=False),
    sa.Column('approved', sa.Boolean(), nullable=False),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['practice_attempt.id'], name=op.f('fk_practice_evaluation_attempt_id_practice_attempt'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_evaluation')),
    sa.UniqueConstraint('attempt_id', 'method', name='uq_practice_evaluation_attempt_method')
    )
    op.create_index(op.f('ix_practice_evaluation_attempt_id'), 'practice_evaluation', ['attempt_id'], unique=False)
    op.create_table('practice_turn',
    sa.Column('attempt_id', sa.Uuid(), nullable=False),
    sa.Column('idx', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('t', sa.Float(), nullable=True),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.CheckConstraint("role IN ('rep','doctor')", name=op.f('ck_practice_turn_role')),
    sa.ForeignKeyConstraint(['attempt_id'], ['practice_attempt.id'], name=op.f('fk_practice_turn_attempt_id_practice_attempt'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('attempt_id', 'idx', name=op.f('pk_practice_turn'))
    )


def downgrade() -> None:
    op.drop_table('practice_turn')
    op.drop_index(op.f('ix_practice_evaluation_attempt_id'), table_name='practice_evaluation')
    op.drop_table('practice_evaluation')
    op.drop_index('ix_training_quiz_result_user_scenario', table_name='training_quiz_result')
    op.drop_table('training_quiz_result')
    op.drop_table('training_profile')
    op.drop_index('uq_practice_attempt_active', table_name='practice_attempt', postgresql_where=sa.text("status IN ('starting','live')"), sqlite_where=sa.text("status IN ('starting','live')"))
    op.drop_index('ix_practice_attempt_user_scenario', table_name='practice_attempt')
    op.drop_index('ix_practice_attempt_status', table_name='practice_attempt')
    op.drop_table('practice_attempt')
    op.drop_index('ix_training_scenario_version_hash', table_name='training_scenario_version')
    op.drop_table('training_scenario_version')
