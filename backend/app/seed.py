"""Demo data: `python -m app.seed`. Idempotent — does nothing if project DEMO exists."""
from datetime import date, timedelta

from sqlalchemy import select

from .db import session_factory
from .models import (
    DEFAULT_STATES,
    Activity,
    Comment,
    Issue,
    IssueType,
    Label,
    Priority,
    Project,
    ProjectMember,
    Role,
    State,
    User,
    utcnow,
)
from .security import hash_password

PEOPLE = [("aigerim", "Aigerim Sadykova"), ("daniyar", "Daniyar Bekov"), ("olga", "Olga Kim")]

ISSUES = [
    # title, state, priority, type, assignee idx, due offset, labels, parent idx
    ("Move Nexus out of Kubernetes to a VM", "In Progress", Priority.high, IssueType.epic, 1, 10, ["infra"], None),
    ("Provision VM and disks for Nexus", "Done", Priority.medium, IssueType.task, 1, -3, ["infra"], 0),
    ("Migrate blob store and repos config", "In Progress", Priority.high, IssueType.task, 1, 4, ["infra"], 0),
    ("Switch DNS and pip/npm proxies to the new host", "To Do", Priority.medium, IssueType.task, 2, 9, [], 0),
    ("Greenplum nightly backup fails on large tables", "In Review", Priority.urgent, IssueType.bug, 0, -1,
     ["db", "incident"], None),
    ("Restore drill: prod backup to dev", "To Do", Priority.high, IssueType.task, 0, 6, ["db"], None),
    ("GitLab offline upgrade 15.4 → 16.x", "Backlog", Priority.medium, IssueType.story, 2, 30, ["infra"], None),
    ("Webhook bridge: GitLab MR links in issues", "Backlog", Priority.low, IssueType.story, None, None, [], None),
    ("Document on-call runbook for PXF errors", "To Do", Priority.low, IssueType.task, 2, 14, ["docs"], None),
    ("Rotate service account passwords", "Done", Priority.high, IssueType.task, 0, -10, ["security"], None),
]


def run():
    with session_factory()() as db:
        if db.scalar(select(Project).where(Project.key == "DEMO")):
            print("demo data already present")
            return
        users = []
        for username, name in PEOPLE:
            u = db.scalar(select(User).where(User.username == username))
            if not u:
                u = User(username=username, display_name=name, email=f"{username}@example.com", source="local",
                         password_hash=hash_password("demo-password"), is_active=True, is_admin=False)
                db.add(u)
            users.append(u)
        db.flush()
        p = Project(key="DEMO", name="Platform team", description="Infrastructure and data platform work",
                    is_private=False, lead_id=users[0].id, issue_seq=0)
        p.states = [State(name=n, category=c, position=i) for i, (n, c) in enumerate(DEFAULT_STATES)]
        roles = {r.key: r.id for r in db.scalars(select(Role).where(Role.scope == "project")).all()}
        p.members = [ProjectMember(user_id=u.id, role_id=roles["admin"] if i == 0 else roles["member"])
                     for i, u in enumerate(users)]
        admin = db.scalar(select(User).where(User.is_admin.is_(True), User.source == "local"))
        if admin:
            p.members.append(ProjectMember(user_id=admin.id, role_id=roles["admin"]))
        db.add(p)
        db.flush()
        states = {s.name: s for s in p.states}
        labels = {n: Label(project_id=p.id, name=n, color=c) for n, c in
                  [("infra", "#3a47d5"), ("db", "#0f7f8c"), ("incident", "#d93b3b"), ("docs", "#8a6d00"),
                   ("security", "#7b3fb5")]}
        db.add_all(labels.values())
        created: list[Issue] = []
        for n, (title, st, prio, typ, who, due, lbls, parent) in enumerate(ISSUES, start=1):
            s = states[st]
            i = Issue(project_id=p.id, number=n, title=title, state_id=s.id, priority=prio, type=typ,
                      reporter_id=users[0].id, position=n * 1024,
                      due_date=date.today() + timedelta(days=due) if due is not None else None,
                      parent_id=created[parent].id if parent is not None else None,
                      description="Context, links and acceptance criteria go here.\n\n- [ ] step one\n- [ ] step two"
                      if n == 1 else "")
            i.assignees = [users[who]] if who is not None else []
            i.labels = [labels[x] for x in lbls]
            if s.category.value in ("in_progress", "done"):
                i.started_at = utcnow() - timedelta(days=3)
            if s.category.value in ("done", "cancelled"):
                i.completed_at = utcnow()
            db.add(i)
            db.flush()
            db.add(Activity(issue_id=i.id, actor_id=users[0].id, field="created", new_value=title))
            created.append(i)
        p.issue_seq = len(ISSUES)
        db.add(Comment(issue_id=created[4].id, author_id=users[0].id,
                       body="Fails on `hr.employee_history` — disk on segment 3 fills up during the dump."))
        db.add(Comment(issue_id=created[4].id, author_id=users[1].id,
                       body="Moved temp dir to the data volume, re-running tonight."))
        db.commit()
        print("demo data created: project DEMO, users aigerim/daniyar/olga (password: demo-password)")


if __name__ == "__main__":
    run()
