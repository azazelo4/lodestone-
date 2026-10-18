import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .. import rbac
from ..db import get_db
from ..deps import current_user, project_for
from ..models import (
    CLOSED,
    Activity,
    Comment,
    Issue,
    IssueType,
    Label,
    Priority,
    Project,
    Sprint,
    State,
    StateCategory,
    User,
    issue_assignees,
    utcnow,
)
from ..schemas import (
    ActivityOut,
    CommentIn,
    CommentOut,
    IssueDetail,
    IssueIn,
    IssueOut,
    IssuePatch,
)

router = APIRouter(prefix="/api", tags=["issues"])

KEY = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,9})-(\d+)$")
LOAD = (selectinload(Issue.project), selectinload(Issue.state), selectinload(Issue.assignees),
        selectinload(Issue.labels), selectinload(Issue.parent).selectinload(Issue.project),
        selectinload(Issue.reporter))


# ---------- helpers
def _subtask_counts(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    if not ids:
        return {}
    rows = db.execute(
        select(Issue.parent_id, func.count(), func.count().filter(State.category.in_(CLOSED)))
        .join(State, State.id == Issue.state_id).where(Issue.parent_id.in_(ids)).group_by(Issue.parent_id))
    return {pid: (total, done) for pid, total, done in rows}


def _out(issue: Issue, counts: dict, cls=IssueOut):
    o = cls.model_validate(issue, from_attributes=True)
    o.parent_key = issue.parent.key if issue.parent else None
    o.subtasks_total, o.subtasks_done = counts.get(issue.id, (0, 0))
    return o


def _load(db: Session, key: str, user: User, need: str = rbac.PROJECT_READ) -> tuple[Issue, set[str]]:
    m = KEY.match(key.strip())
    if not m:
        raise HTTPException(404, "Issue not found")
    project, perms = project_for(db, m.group(1), user, need)
    issue = db.scalar(select(Issue).options(*LOAD).where(Issue.project_id == project.id,
                                                         Issue.number == int(m.group(2))))
    if not issue:
        raise HTTPException(404, "Issue not found")
    return issue, perms


def _resolve_parent(db: Session, project: Project, parent_key: str | None, self_id: uuid.UUID | None = None):
    if not parent_key:
        return None
    m = KEY.match(parent_key.strip())
    if not m or m.group(1).upper() != project.key:
        raise HTTPException(422, "Parent must be an issue in the same project")
    parent = db.scalar(select(Issue).where(Issue.project_id == project.id, Issue.number == int(m.group(2))))
    if not parent:
        raise HTTPException(422, f"Parent {parent_key} not found")
    # no cycles: walk up from the parent
    cur, hops = parent, 0
    while cur is not None and hops < 50:
        if self_id and cur.id == self_id:
            raise HTTPException(422, "An issue cannot be its own ancestor")
        cur = db.get(Issue, cur.parent_id) if cur.parent_id else None
        hops += 1
    return parent


def _members(db: Session, project: Project, ids: list[uuid.UUID]) -> list[User]:
    if not ids:
        return []
    users = db.scalars(select(User).where(User.id.in_(rbac.project_user_ids(project.id)), User.id.in_(ids),
                                          User.is_active.is_(True))).all()
    if len(users) != len(set(ids)):
        raise HTTPException(422, "Assignees must be active project members")
    return list(users)


def _labels(db: Session, project: Project, ids: list[uuid.UUID]) -> list[Label]:
    if not ids:
        return []
    labels = db.scalars(select(Label).where(Label.project_id == project.id, Label.id.in_(ids))).all()
    if len(labels) != len(set(ids)):
        raise HTTPException(422, "Unknown label")
    return list(labels)


def _state(db: Session, project: Project, state_id: uuid.UUID | None) -> State:
    if state_id is None:
        st = db.scalar(select(State).where(State.project_id == project.id).order_by(State.position).limit(1))
    else:
        st = db.get(State, state_id)
    if not st or st.project_id != project.id:
        raise HTTPException(422, "Unknown state")
    return st


def _sprint(db: Session, project: Project, sprint_id: uuid.UUID | None) -> Sprint | None:
    if sprint_id is None:
        return None
    sp = db.get(Sprint, sprint_id)
    if not sp or sp.project_id != project.id:
        raise HTTPException(422, "Unknown sprint")
    return sp


def _apply_state_times(issue: Issue, st: State):
    if st.category == StateCategory.in_progress and issue.started_at is None:
        issue.started_at = utcnow()
    if st.category in CLOSED:
        issue.completed_at = issue.completed_at or utcnow()
    else:
        issue.completed_at = None


def _log(db: Session, issue: Issue, actor: User, field: str, old, new, old_ref=None, new_ref=None):
    def s(v):
        if v is None or v == "" or v == []:
            return None
        return str(v)[:500]
    db.add(Activity(issue_id=issue.id, actor_id=actor.id, field=field, old_value=s(old), new_value=s(new),
                    old_ref=old_ref, new_ref=new_ref))


# ---------- list / create
@router.get("/projects/{key}/issues", response_model=list[IssueOut])
def list_issues(
    key: str,
    q: str = "",
    state_id: list[uuid.UUID] = Query(default=[]),
    category: list[StateCategory] = Query(default=[]),
    assignee: list[str] = Query(default=[], description="user id or 'me' or 'none'"),
    priority: list[Priority] = Query(default=[]),
    label_id: list[uuid.UUID] = Query(default=[]),
    sprint_id: str | None = Query(default=None, description="sprint id or 'none'"),
    type: list[IssueType] = Query(default=[]),
    parent: str | None = Query(default=None, description="parent key, or 'none' for top-level only"),
    open_only: bool = False,
    limit: int = Query(default=500, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project, _ = project_for(db, key, user)
    stmt = select(Issue).options(*LOAD).join(State, State.id == Issue.state_id).where(Issue.project_id == project.id)
    if q:
        m = KEY.match(q.strip())
        if m and m.group(1).upper() == project.key:
            stmt = stmt.where(Issue.number == int(m.group(2)))
        else:
            like = f"%{q}%"
            stmt = stmt.where(or_(Issue.title.ilike(like), Issue.description.ilike(like)))
    if state_id:
        stmt = stmt.where(Issue.state_id.in_(state_id))
    if category:
        stmt = stmt.where(State.category.in_(category))
    if open_only:
        stmt = stmt.where(State.category.notin_(CLOSED))
    if assignee:
        conds = []
        ids = []
        for a in assignee:
            if a == "none":
                conds.append(~Issue.assignees.any())
            else:
                ids.append(user.id if a == "me" else uuid.UUID(a))
        if ids:
            conds.append(Issue.assignees.any(User.id.in_(ids)))
        stmt = stmt.where(or_(*conds))
    if priority:
        stmt = stmt.where(Issue.priority.in_(priority))
    if label_id:
        stmt = stmt.where(Issue.labels.any(Label.id.in_(label_id)))
    if sprint_id == "none":
        stmt = stmt.where(Issue.sprint_id.is_(None))
    elif sprint_id:
        stmt = stmt.where(Issue.sprint_id == uuid.UUID(sprint_id))
    if type:
        stmt = stmt.where(Issue.type.in_(type))
    if parent == "none":
        stmt = stmt.where(Issue.parent_id.is_(None))
    elif parent:
        par = _resolve_parent(db, project, parent)
        stmt = stmt.where(Issue.parent_id == par.id)
    issues = db.scalars(stmt.order_by(State.position, Issue.position, Issue.number).limit(limit)).all()
    counts = _subtask_counts(db, [i.id for i in issues])
    return [_out(i, counts) for i in issues]


@router.post("/projects/{key}/issues", response_model=IssueDetail, status_code=201)
def create_issue(key: str, body: IssueIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project, _ = project_for(db, key, user, rbac.ISSUES_CREATE)
    st = _state(db, project, body.state_id)
    parent = _resolve_parent(db, project, body.parent_key)
    assignees = _members(db, project, body.assignee_ids)
    labels = _labels(db, project, body.label_ids)
    sprint = _sprint(db, project, body.sprint_id)
    # atomic increment (row lock held until commit): numbers stay unique under concurrency
    number = db.execute(update(Project).where(Project.id == project.id)
                        .values(issue_seq=Project.issue_seq + 1).returning(Project.issue_seq)).scalar_one()
    top = db.scalar(select(func.max(Issue.position)).where(Issue.state_id == st.id)) or 0
    issue = Issue(project_id=project.id, number=number, type=body.type, title=body.title.strip(),
                  description=body.description, state_id=st.id, priority=body.priority,
                  parent_id=parent.id if parent else None, sprint_id=sprint.id if sprint else None,
                  reporter_id=user.id, start_date=body.start_date, due_date=body.due_date, estimate=body.estimate,
                  position=top + 1024)
    issue.assignees, issue.labels = assignees, labels
    _apply_state_times(issue, st)
    db.add(issue)
    db.flush()
    _log(db, issue, user, "created", None, issue.title)
    db.commit()
    return get_issue(f"{project.key}-{number}", db, user)


# ---------- single issue
@router.get("/issues/{key}", response_model=IssueDetail)
def get_issue(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, _ = _load(db, key, user)
    subs = db.scalars(select(Issue).options(*LOAD).join(State, State.id == Issue.state_id)
                      .where(Issue.parent_id == issue.id).order_by(State.position, Issue.number)).all()
    counts = _subtask_counts(db, [issue.id] + [s.id for s in subs])
    d = _out(issue, counts, IssueDetail)
    d.project_key = issue.project.key
    d.subtasks = [_out(s, counts) for s in subs]
    return d


@router.patch("/issues/{key}", response_model=IssueDetail)
def patch_issue(key: str, body: IssuePatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, _ = _load(db, key, user, rbac.ISSUES_EDIT)
    project = issue.project
    data = body.model_dump(exclude_unset=True)

    for f in ("title", "description", "type", "priority", "start_date", "due_date", "estimate"):
        if f in data and data[f] != getattr(issue, f):
            if f == "title" and not (data[f] or "").strip():
                raise HTTPException(422, "Title cannot be empty")
            old = getattr(issue, f)
            setattr(issue, f, data[f])
            if f == "description":
                _log(db, issue, user, f, None, "updated")
            else:
                _log(db, issue, user, f, getattr(old, "value", old), getattr(data[f], "value", data[f]))

    if "state_id" in data and data["state_id"] and data["state_id"] != issue.state_id:
        st = _state(db, project, data["state_id"])
        _log(db, issue, user, "state", issue.state.name, st.name, str(issue.state_id), str(st.id))
        issue.state_id, issue.state = st.id, st
        _apply_state_times(issue, st)
    if "position" in data and data["position"] is not None:
        issue.position = data["position"]
    if "assignee_ids" in data:
        new = _members(db, project, data["assignee_ids"] or [])
        if {u.id for u in new} != {u.id for u in issue.assignees}:
            _log(db, issue, user, "assignees", ", ".join(u.display_name for u in issue.assignees),
                 ", ".join(u.display_name for u in new))
            issue.assignees = new
    if "label_ids" in data:
        new = _labels(db, project, data["label_ids"] or [])
        if {lb.id for lb in new} != {lb.id for lb in issue.labels}:
            _log(db, issue, user, "labels", ", ".join(lb.name for lb in issue.labels), ", ".join(lb.name for lb in new))
            issue.labels = new
    if "parent_key" in data:
        par = _resolve_parent(db, project, data["parent_key"], self_id=issue.id)
        if (par.id if par else None) != issue.parent_id:
            _log(db, issue, user, "parent", issue.parent.key if issue.parent else None, par.key if par else None)
            issue.parent_id = par.id if par else None
    if "sprint_id" in data and data["sprint_id"] != issue.sprint_id:
        sp = _sprint(db, project, data["sprint_id"])
        old = db.get(Sprint, issue.sprint_id) if issue.sprint_id else None
        _log(db, issue, user, "sprint", old.name if old else None, sp.name if sp else None)
        issue.sprint_id = sp.id if sp else None

    issue.updated_at = utcnow()
    db.commit()
    db.expire_all()
    return get_issue(key, db, user)


@router.delete("/issues/{key}", status_code=204)
def delete_issue(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, perms = _load(db, key, user)
    own = issue.reporter_id == user.id and rbac.ISSUES_EDIT in perms
    if rbac.ISSUES_DELETE not in perms and not own:
        raise HTTPException(403, "Only the reporter or a project admin can delete an issue")
    db.delete(issue)
    db.commit()


# ---------- comments / activity
@router.get("/issues/{key}/comments", response_model=list[CommentOut])
def comments(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, _ = _load(db, key, user)
    return db.scalars(select(Comment).options(selectinload(Comment.author)).where(Comment.issue_id == issue.id)
                      .order_by(Comment.created_at)).all()


@router.post("/issues/{key}/comments", response_model=CommentOut, status_code=201)
def add_comment(key: str, body: CommentIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, _ = _load(db, key, user, rbac.COMMENTS_CREATE)
    c = Comment(issue_id=issue.id, author_id=user.id, body=body.body)
    db.add(c)
    issue.updated_at = utcnow()
    db.commit()
    db.refresh(c)
    return c


def _comment(db: Session, comment_id: uuid.UUID, user: User) -> Comment:
    c = db.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    issue = db.get(Issue, c.issue_id)
    project = db.get(Project, issue.project_id)
    perms = rbac.project_permissions(db, project, user)
    if rbac.PROJECT_READ not in perms:
        raise HTTPException(404, "Comment not found")
    if c.author_id != user.id and rbac.COMMENTS_MODERATE not in perms:
        raise HTTPException(403, "You can only change your own comments")
    return c


@router.patch("/comments/{comment_id}", response_model=CommentOut)
def edit_comment(comment_id: uuid.UUID, body: CommentIn, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    c = _comment(db, comment_id, user)
    c.body, c.edited_at = body.body, utcnow()
    db.commit()
    return c


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_comment(db, comment_id, user))
    db.commit()


@router.get("/issues/{key}/activity", response_model=list[ActivityOut])
def activity(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    issue, _ = _load(db, key, user)
    return db.scalars(select(Activity).options(selectinload(Activity.actor)).where(Activity.issue_id == issue.id)
                      .order_by(Activity.created_at, Activity.id)).all()


# ---------- my work
@router.get("/my/issues", response_model=list[IssueOut])
def my_issues(db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = (select(Issue).options(*LOAD).join(State, State.id == Issue.state_id)
            .join(issue_assignees, issue_assignees.c.issue_id == Issue.id)
            .where(issue_assignees.c.user_id == user.id, State.category.notin_(CLOSED)))
    stmt = stmt.join(Project, Project.id == Issue.project_id).where(rbac.visible_projects(db, user))
    issues = db.scalars(stmt.order_by(Issue.due_date.nulls_last(), Issue.updated_at.desc()).limit(200)).all()
    counts = _subtask_counts(db, [i.id for i in issues])
    return [_out(i, counts) for i in issues]

