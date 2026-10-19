"""modules, cycle closing, analytics views for cycles and modules

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19 06:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

CYCLES = """
CREATE OR REPLACE VIEW analytics.cycles AS
SELECT sp.id AS cycle_id, p.key AS project_key, sp.name, sp.goal, sp.start_date, sp.end_date, sp.closed, sp.closed_at,
       count(i.id)                                                   AS issues_total,
       count(i.id) FILTER (WHERE s.category = 'done')                AS issues_done,
       count(i.id) FILTER (WHERE s.category = 'cancelled')           AS issues_cancelled,
       count(i.id) FILTER (WHERE s.category = 'in_progress')         AS issues_in_progress,
       coalesce(sum(i.estimate), 0)                                  AS estimate_total,
       coalesce(sum(i.estimate) FILTER (WHERE s.category = 'done'), 0) AS estimate_done
FROM sprints sp
JOIN projects p ON p.id = sp.project_id
LEFT JOIN issues i ON i.sprint_id = sp.id
LEFT JOIN states s ON s.id = i.state_id
GROUP BY sp.id, p.key
"""

MODULES = """
CREATE OR REPLACE VIEW analytics.modules AS
SELECT m.id AS module_id, p.key AS project_key, m.name, m.status, u.display_name AS lead,
       m.start_date, m.target_date, m.created_at,
       count(i.id)                                                   AS issues_total,
       count(i.id) FILTER (WHERE s.category = 'done')                AS issues_done,
       count(i.id) FILTER (WHERE s.category = 'cancelled')           AS issues_cancelled,
       count(i.id) FILTER (WHERE s.category = 'in_progress')         AS issues_in_progress,
       coalesce(sum(i.estimate), 0)                                  AS estimate_total,
       coalesce(sum(i.estimate) FILTER (WHERE s.category = 'done'), 0) AS estimate_done
FROM modules m
JOIN projects p ON p.id = m.project_id
LEFT JOIN users u ON u.id = m.lead_id
LEFT JOIN issue_modules im ON im.module_id = m.id
LEFT JOIN issues i ON i.id = im.issue_id
LEFT JOIN states s ON s.id = i.state_id
GROUP BY m.id, p.key, u.display_name
"""

ISSUE_MODULES = """
CREATE OR REPLACE VIEW analytics.issue_modules AS
SELECT im.issue_id, m.id AS module_id, m.name AS module
FROM issue_modules im JOIN modules m ON m.id = im.module_id
"""


def upgrade() -> None:
    op.add_column('sprints', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('modules',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('lead_id', sa.UUID(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lead_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'name'),
    sa.CheckConstraint("status IN ('backlog','planned','in_progress','paused','completed','cancelled')",
                       name='ck_modules_status'),
    )
    op.create_index(op.f('ix_modules_project_id'), 'modules', ['project_id'], unique=False)
    op.create_table('issue_modules',
    sa.Column('issue_id', sa.UUID(), nullable=False),
    sa.Column('module_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('issue_id', 'module_id'),
    )
    op.create_index(op.f('ix_issue_modules_module_id'), 'issue_modules', ['module_id'], unique=False)
    # builtin project roles get the new permission (existing installs keep their role rows)
    op.execute("UPDATE roles SET permissions = array_append(permissions, 'modules.manage') "
               "WHERE builtin AND key IN ('admin', 'member') AND NOT ('modules.manage' = ANY(permissions))")
    op.execute(CYCLES)
    op.execute(MODULES)
    op.execute(ISSUE_MODULES)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics.issue_modules")
    op.execute("DROP VIEW IF EXISTS analytics.modules")
    op.execute("DROP VIEW IF EXISTS analytics.cycles")
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'modules.manage')")
    op.drop_index(op.f('ix_issue_modules_module_id'), table_name='issue_modules')
    op.drop_table('issue_modules')
    op.drop_index(op.f('ix_modules_project_id'), table_name='modules')
    op.drop_table('modules')
    op.drop_column('sprints', 'closed_at')
