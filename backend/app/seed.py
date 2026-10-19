"""Demo data: `python -m app.seed`. Idempotent — does nothing if project DEMO exists."""
import random
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
    Module,
    Page,
    Priority,
    Project,
    ProjectMember,
    Role,
    Sprint,
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
        p.issue_seq = _planning(db, p, users, states, created)
        db.add(Comment(issue_id=created[4].id, author_id=users[0].id,
                       body="Fails on `hr.employee_history` — disk on segment 3 fills up during the dump."))
        db.add(Comment(issue_id=created[4].id, author_id=users[1].id,
                       body="Moved temp dir to the data volume, re-running tonight."))
        _docs(db, p, users[0])
        db.commit()
        print("demo data created: project DEMO, users aigerim/daniyar/olga (password: demo-password)")


DOCS = [
    # title, parent idx, body
    ("Platform handbook", None, "How the platform team works: where things run, who is on call, and how to change "
     "them safely.\n\n## Contents\n\n- [On-call runbook](#)\n- Services and owners\n- Change process\n\n"
     "> **Rule of thumb**\n>\n> If a change needs a maintenance window, it needs an issue in DEMO first."),
    ("On-call runbook", 0, "## Before the shift\n\n1. Check the *Incidents* label on the board.\n"
     "2. Make sure you can reach the bastion: `ssh bastion.corp.local`.\n\n## Greenplum backup failed\n\n"
     "| Symptom | First step |\n| --- | --- |\n| `No space left on device` | Move the dump temp dir to the data "
     "volume |\n| Lock timeout | Re-run after the nightly ETL finishes |\n\n```bash\n"
     "gpbackup --dbname dwh --backup-dir /data/backup --jobs 4\n```"),
    ("Services and owners", 0, "| Service | Host | Owner |\n| --- | --- | --- |\n| Nexus | nexus.corp.local | "
     "Daniyar |\n| GitLab | gitlab.corp.local | Olga |\n| Greenplum | gp-master.corp.local | Aigerim |"),
    ("Change process", 0, "- [ ] Issue with the plan and the rollback\n- [ ] Review by a second engineer\n"
     "- [ ] Announce in the team channel\n- [ ] Close the issue with the result"),
]


def _docs(db, p: Project, author: User):
    made: list[Page] = []
    for n, (title, parent, body) in enumerate(DOCS):
        pg = Page(project_id=p.id, title=title, body=body, position=(n + 1) * 1024,
                  parent_id=made[parent].id if parent is not None else None,
                  created_by_id=author.id, updated_by_id=author.id)
        db.add(pg)
        db.flush()
        made.append(pg)
    made[0].body = made[0].body.replace("(#)", f"(/p/{p.key}/docs/{made[1].id})")


HISTORY_TITLES = ["Upgrade node exporter", "Alert on WAL archive lag", "Grafana dashboard for PXF",
                  "Clean old MinIO buckets", "Pin base images by digest", "Ansible role for VM hardening",
                  "Rotate TLS certificates",
                  "Move CI runners to new subnet", "Fix flaky integration test", "Quota for team namespaces",
                  "Retention policy for Loki", "Patch OpenSSL on bastion", "Vault audit log shipping",
                  "Terraform state migration", "Disk usage report for Greenplum", "Kafka topic cleanup"]


def _planning(db, p, users, states, issues: list[Issue]) -> int:
    """Cycles, modules and six weeks of history so the burndown and analytics have something to show."""
    rng = random.Random(42)
    today = date.today()
    now = utcnow()
    past = Sprint(project_id=p.id, name="Cycle 41", goal="Stabilise backups", start_date=today - timedelta(days=21),
                  end_date=today - timedelta(days=8), closed=True, closed_at=now - timedelta(days=7))
    current = Sprint(project_id=p.id, name="Cycle 42", goal="Nexus off Kubernetes",
                     start_date=today - timedelta(days=7), end_date=today + timedelta(days=6))
    nxt = Sprint(project_id=p.id, name="Cycle 43", start_date=today + timedelta(days=7),
                 end_date=today + timedelta(days=20))
    nexus = Module(project_id=p.id, name="Nexus migration", status="in_progress", lead_id=users[1].id,
                   start_date=today - timedelta(days=28), target_date=today + timedelta(days=20),
                   description="Nexus moves from Kubernetes to a dedicated VM.")
    backup = Module(project_id=p.id, name="Backup hardening", status="planned", lead_id=users[0].id,
                    target_date=today + timedelta(days=35))
    db.add_all([past, current, nxt, nexus, backup])
    db.flush()
    for n, i in enumerate(issues):
        i.created_at = now - timedelta(days=30 - n)
        if n <= 3:
            i.modules = [nexus]
        elif n in (4, 5, 9):
            i.modules = [backup]
        i.sprint_id = past.id if n == 9 else current.id if n in (1, 2, 3, 4, 5, 8) else None
    order = ["Backlog", "To Do", "In Progress", "In Review", "Done"]
    number = len(issues)
    for title in HISTORY_TITLES * 2:
        number += 1
        created = now - timedelta(days=rng.uniform(1, 42), hours=rng.uniform(0, 8))
        steps = rng.choice([1, 2, 3, 4, 4, 5, 5])  # how far along the workflow it got
        i = Issue(project_id=p.id, number=number, title=title, state_id=states["Backlog"].id, reporter_id=users[0].id,
                  priority=rng.choice(list(Priority)), position=number * 1024, created_at=created,
                  estimate=rng.choice([None, 1, 2, 3, 5]))
        i.assignees = [rng.choice(users)] if rng.random() > 0.15 else []
        db.add(i)
        db.flush()
        db.add(Activity(issue_id=i.id, actor_id=users[0].id, field="created", new_value=title, created_at=created))
        at = created
        for k in range(1, steps):
            at = min(at + timedelta(days=rng.uniform(0.5, 5)), now - timedelta(minutes=5 * (steps - k)))
            old, new = states[order[k - 1]], states[order[k]]
            db.add(Activity(issue_id=i.id, actor_id=i.assignees[0].id if i.assignees else users[0].id, field="state",
                            old_value=old.name, new_value=new.name, old_ref=str(old.id), new_ref=str(new.id),
                            created_at=at))
            i.state_id = new.id
            if order[k] == "In Progress":
                i.started_at = at
            if order[k] == "Done":
                i.completed_at = at
        age = (today - created.date()).days
        i.sprint_id = past.id if age > 8 and steps == 5 else (current.id if age <= 14 else None)
        if "Nexus" in title or rng.random() < 0.25:
            i.modules = [nexus]
        elif rng.random() < 0.2:
            i.modules = [backup]
    return number


if __name__ == "__main__":
    run()
