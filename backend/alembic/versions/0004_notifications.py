"""notifications: messenger channels, personal e-mail settings, outbox

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18 13:00:00
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('notification_channels',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('events', postgresql.ARRAY(sa.String(length=30)), nullable=False),
    sa.Column('lang', sa.String(length=5), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('secrets', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_channels_project_id'), 'notification_channels', ['project_id'])
    op.create_table('notification_prefs',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('email_enabled', sa.Boolean(), nullable=False),
    sa.Column('events', postgresql.ARRAY(sa.String(length=30)), nullable=False),
    sa.Column('lang', sa.String(length=5), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('notification_outbox',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('recipient', sa.String(length=320), nullable=False),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # the worker only scans due pending messages
    op.create_index('ix_notification_outbox_due', 'notification_outbox', ['next_attempt_at'],
                    postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index('ix_notification_outbox_due', table_name='notification_outbox')
    op.drop_table('notification_outbox')
    op.drop_table('notification_prefs')
    op.drop_index(op.f('ix_notification_channels_project_id'), table_name='notification_channels')
    op.drop_table('notification_channels')
