"""project finance: budget, hourly rates, worklogs, expenses, analytics views

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-15 14:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

# The rate of a worklog: the person's latest project rate not after the work date; for work before their first
# rate, that first rate; for people without a rate, the project default. app/finance.py does the same for the API.
WORKLOGS = """
CREATE OR REPLACE VIEW analytics.worklogs AS
SELECT w.id AS worklog_id, p.key AS project_key, p.key || '-' || i.number AS issue_key, i.title AS issue_title,
       u.username, u.display_name AS person, w.work_date, round(w.minutes / 60.0, 2) AS hours, w.note,
       r.rate, round(w.minutes / 60.0 * r.rate, 2) AS cost, coalesce(pf.currency, 'USD') AS currency
FROM worklogs w
JOIN issues i ON i.id = w.issue_id
JOIN projects p ON p.id = w.project_id
LEFT JOIN users u ON u.id = w.user_id
LEFT JOIN project_finance pf ON pf.project_id = w.project_id
CROSS JOIN LATERAL (
    SELECT coalesce((SELECT mr.rate FROM member_rates mr
                      WHERE mr.project_id = w.project_id AND mr.user_id = w.user_id AND mr.valid_from <= w.work_date
                      ORDER BY mr.valid_from DESC LIMIT 1),
                    (SELECT mr.rate FROM member_rates mr
                      WHERE mr.project_id = w.project_id AND mr.user_id = w.user_id
                      ORDER BY mr.valid_from LIMIT 1),
                    pf.default_rate) AS rate) r
"""

EXPENSES = """
CREATE OR REPLACE VIEW analytics.expenses AS
SELECT e.id AS expense_id, p.key AS project_key, e.spent_on, e.amount, coalesce(pf.currency, 'USD') AS currency,
       e.category, e.description, p.key || '-' || i.number AS issue_key, m.name AS module,
       u.display_name AS created_by, e.created_at
FROM expenses e
JOIN projects p ON p.id = e.project_id
LEFT JOIN project_finance pf ON pf.project_id = e.project_id
LEFT JOIN issues i ON i.id = e.issue_id
LEFT JOIN modules m ON m.id = e.module_id
LEFT JOIN users u ON u.id = e.created_by_id
"""

BUDGETS = """
CREATE OR REPLACE VIEW analytics.project_budgets AS
SELECT p.key AS project_key, p.name AS project_name, pf.currency, pf.budget, pf.budget_hours, pf.default_rate,
       pf.start_date, pf.end_date,
       coalesce((SELECT sum(w.hours) FROM analytics.worklogs w WHERE w.project_key = p.key), 0) AS hours_logged,
       coalesce((SELECT sum(w.cost) FROM analytics.worklogs w WHERE w.project_key = p.key), 0) AS labor_cost,
       coalesce((SELECT sum(e.amount) FROM expenses e WHERE e.project_id = p.id), 0) AS expenses
FROM project_finance pf
JOIN projects p ON p.id = pf.project_id
"""


def upgrade() -> None:
    op.create_table('project_finance',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('budget', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('budget_hours', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('default_rate', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id'),
    )
    op.create_table('member_rates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('rate', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.CheckConstraint('rate >= 0', name='ck_member_rates_rate'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'user_id', 'valid_from'),
    )
    op.create_index(op.f('ix_member_rates_project_id'), 'member_rates', ['project_id'], unique=False)
    op.create_table('worklogs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('issue_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('minutes', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('minutes > 0 AND minutes <= 1440', name='ck_worklogs_minutes'),
    sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_worklogs_issue_id'), 'worklogs', ['issue_id'], unique=False)
    op.create_index(op.f('ix_worklogs_project_id'), 'worklogs', ['project_id'], unique=False)
    op.create_index(op.f('ix_worklogs_user_id'), 'worklogs', ['user_id'], unique=False)
    op.create_table('expenses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('spent_on', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('issue_id', sa.UUID(), nullable=True),
    sa.Column('module_id', sa.UUID(), nullable=True),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('amount >= 0', name='ck_expenses_amount'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_expenses_project_id'), 'expenses', ['project_id'], unique=False)
    op.execute(WORKLOGS)
    op.execute(EXPENSES)
    op.execute(BUDGETS)
    for perm, roles in (("time.log", "('admin', 'member')"), ("finance.view", "('admin')"),
                        ("finance.manage", "('admin')")):
        op.execute(f"UPDATE roles SET permissions = array_append(permissions, '{perm}') "
                   f"WHERE builtin AND key IN {roles} AND NOT ('{perm}' = ANY(permissions))")


def downgrade() -> None:
    for perm in ("time.log", "finance.view", "finance.manage"):
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{perm}')")
    op.execute("DROP VIEW IF EXISTS analytics.project_budgets")
    op.execute("DROP VIEW IF EXISTS analytics.expenses")
    op.execute("DROP VIEW IF EXISTS analytics.worklogs")
    op.drop_index(op.f('ix_expenses_project_id'), table_name='expenses')
    op.drop_table('expenses')
    op.drop_index(op.f('ix_worklogs_user_id'), table_name='worklogs')
    op.drop_index(op.f('ix_worklogs_project_id'), table_name='worklogs')
    op.drop_index(op.f('ix_worklogs_issue_id'), table_name='worklogs')
    op.drop_table('worklogs')
    op.drop_index(op.f('ix_member_rates_project_id'), table_name='member_rates')
    op.drop_table('member_rates')
    op.drop_table('project_finance')
