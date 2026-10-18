"""analytics schema: flat views for BI tools (Power BI, Metabase, Grafana)

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ISSUES = """
CREATE OR REPLACE VIEW analytics.issues AS
SELECT i.id                                   AS issue_id,
       p.key || '-' || i.number               AS issue_key,
       p.key                                  AS project_key,
       p.name                                 AS project_name,
       i.title,
       i.type::text                           AS issue_type,
       i.priority::text                       AS priority,
       s.name                                 AS state,
       s.category::text                       AS state_category,
       s.category NOT IN ('done', 'cancelled') AS is_open,
       sp.name                                AS sprint,
       par_p.key || '-' || par.number         AS parent_key,
       r.display_name                         AS reporter,
       (SELECT string_agg(u.display_name, ', ' ORDER BY u.display_name)
          FROM issue_assignees ia JOIN users u ON u.id = ia.user_id
         WHERE ia.issue_id = i.id)            AS assignees,
       i.estimate,
       i.created_at, i.started_at, i.completed_at, i.updated_at,
       i.start_date, i.due_date,
       CASE WHEN s.category NOT IN ('done', 'cancelled') AND i.due_date < current_date THEN true ELSE false END
                                              AS is_overdue,
       CASE WHEN i.completed_at IS NOT NULL
            THEN round(extract(epoch FROM i.completed_at - i.created_at) / 86400.0, 2) END AS lead_time_days,
       CASE WHEN i.completed_at IS NOT NULL AND i.started_at IS NOT NULL
            THEN round(extract(epoch FROM i.completed_at - i.started_at) / 86400.0, 2) END AS cycle_time_days,
       round(extract(epoch FROM coalesce(i.completed_at, now()) - i.created_at) / 86400.0, 2) AS age_days
FROM issues i
JOIN projects p   ON p.id = i.project_id
JOIN states s     ON s.id = i.state_id
LEFT JOIN sprints sp  ON sp.id = i.sprint_id
LEFT JOIN issues par  ON par.id = i.parent_id
LEFT JOIN projects par_p ON par_p.id = par.project_id
LEFT JOIN users r ON r.id = i.reporter_id
"""

ASSIGNEES = """
CREATE OR REPLACE VIEW analytics.issue_assignees AS
SELECT ia.issue_id, u.id AS user_id, u.username, u.display_name,
       1.0 / count(*) OVER (PARTITION BY ia.issue_id) AS share
FROM issue_assignees ia JOIN users u ON u.id = ia.user_id
"""

TRANSITIONS = """
CREATE OR REPLACE VIEW analytics.state_transitions AS
SELECT a.issue_id, a.created_at AS changed_at, u.display_name AS actor,
       a.old_value AS from_state, fs.category::text AS from_category,
       a.new_value AS to_state, ts.category::text AS to_category,
       round(extract(epoch FROM a.created_at - lag(a.created_at, 1, i.created_at)
             OVER (PARTITION BY a.issue_id ORDER BY a.created_at, a.id)) / 86400.0, 2) AS days_in_from_state
FROM activities a
JOIN issues i ON i.id = a.issue_id
LEFT JOIN users u ON u.id = a.actor_id
LEFT JOIN states fs ON fs.id::text = a.old_ref
LEFT JOIN states ts ON ts.id::text = a.new_ref
WHERE a.field = 'state'
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    op.execute(ISSUES)
    op.execute(ASSIGNEES)
    op.execute(TRANSITIONS)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS analytics CASCADE")
