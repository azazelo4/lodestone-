"""documentation pages, import jobs and links to imported objects

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 11:00:00
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('pages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('position', sa.Float(), nullable=False),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('updated_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_id'], ['pages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pages_parent_id'), 'pages', ['parent_id'], unique=False)
    op.create_index(op.f('ix_pages_project_id'), 'pages', ['project_id'], unique=False)
    op.create_table('import_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('secrets', sa.Text(), nullable=True),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('log', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('project_key', sa.String(length=10), nullable=True),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_table('import_links',
    sa.Column('source', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('local_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('source', 'kind', 'external_id'),
    )
    op.create_index(op.f('ix_import_links_project_id'), 'import_links', ['project_id'], unique=False)
    op.execute("UPDATE roles SET permissions = array_append(permissions, 'docs.edit') "
               "WHERE builtin AND key IN ('admin', 'member') AND NOT ('docs.edit' = ANY(permissions))")


def downgrade() -> None:
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'docs.edit')")
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'imports.run')")
    op.drop_index(op.f('ix_import_links_project_id'), table_name='import_links')
    op.drop_table('import_links')
    op.drop_table('import_jobs')
    op.drop_index(op.f('ix_pages_project_id'), table_name='pages')
    op.drop_index(op.f('ix_pages_parent_id'), table_name='pages')
    op.drop_table('pages')
