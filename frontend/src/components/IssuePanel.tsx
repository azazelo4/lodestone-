import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useSession } from "../App";
import {
  Activity, api, ApiError, Comment, IssueDetail, IssueType, Priority,
} from "../api";
import { ProjectData, projectData } from "../pages/ProjectView";
import { TKey, useT } from "../i18n";
import {
  Avatar, Avatars, DueDate, Markdown, MultiPicker, PriorityIcon, StateDot, timeAgo, Toast,
} from "./bits";

const PRIORITIES: Priority[] = ["urgent", "high", "medium", "low", "none"];
const TYPES: IssueType[] = ["task", "bug", "story", "epic"];

type Ctx = ProjectData;

function AutoTitle({ value, onSave, disabled }: { value: string; onSave: (v: string) => void; disabled: boolean }) {
  const [v, setV] = useState(value);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => setV(value), [value]);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) { el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; }
  }, [v]);
  const commit = () => {
    const nv = v.trim();
    if (nv && nv !== value) onSave(nv);
    else setV(value);
  };
  return (
    <textarea ref={ref} className="issue-title" rows={1} value={v} disabled={disabled} aria-label="Title"
              onChange={(e) => setV(e.target.value.replace(/\n/g, ""))} onBlur={commit}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.target as HTMLTextAreaElement).blur(); } if (e.key === "Escape") { setV(value); } }} />
  );
}

function Description({ value, onSave, canEdit }: { value: string; onSave: (v: string) => Promise<void>; canEdit: boolean }) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  if (editing) {
    return (
      <div style={{ display: "grid", gap: 8 }}>
        <textarea className="textarea" autoFocus value={v} placeholder={t("issue.descriptionPh")} onChange={(e) => setV(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { onSave(v).then(() => setEditing(false)); } }} />
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn primary sm" onClick={() => onSave(v).then(() => setEditing(false))}>{t("issue.save")}</button>
          <button className="btn sm" onClick={() => { setV(value); setEditing(false); }}>{t("issue.cancel")}</button>
          <span className="hint" style={{ alignSelf: "center" }}>Ctrl+Enter</span>
        </div>
      </div>
    );
  }
  if (!value) {
    return canEdit
      ? <div className="desc-view placeholder" onClick={() => setEditing(true)} role="button" tabIndex={0}
             onKeyDown={(e) => e.key === "Enter" && setEditing(true)}>{t("issue.noDescription")}</div>
      : null;
  }
  return (
    <div className="desc-view" onClick={(e) => { if (canEdit && !(e.target as HTMLElement).closest("a")) setEditing(true); }}>
      <Markdown text={value} />
    </div>
  );
}

function ActivityLine({ a }: { a: Activity }) {
  const { t, lang } = useT();
  const key = `act.${a.field}` as TKey;
  const showValues = !["created", "description"].includes(a.field);
  const val = (v: string | null) => {
    if (v === null) return t("issue.none");
    if (a.field === "priority") return t(`priority.${v}` as TKey);
    if (a.field === "type") return t(`type.${v}` as TKey);
    return v;
  };
  return (
    <div className="event">
      <b>{a.actor?.display_name ?? "—"}</b>
      <span>{t(key) === key ? a.field : t(key)}</span>
      {showValues && <><span className="val">{val(a.old_value)}</span><span>→</span><span className="val">{val(a.new_value)}</span></>}
      <time dateTime={a.created_at} title={new Date(a.created_at).toLocaleString(lang)}>{timeAgo(a.created_at, lang)}</time>
    </div>
  );
}

function CommentItem({ c, canModify, onEdit, onDelete }: {
  c: Comment; canModify: boolean; onEdit: (body: string) => Promise<void>; onDelete: () => void;
}) {
  const { t, lang } = useT();
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(c.body);
  return (
    <div className="comment">
      {c.author ? <Avatar user={c.author} large /> : <span />}
      <div>
        <div className="head">
          <b>{c.author?.display_name ?? "—"}</b>
          <time dateTime={c.created_at} title={new Date(c.created_at).toLocaleString(lang)}>
            {timeAgo(c.created_at, lang)}{c.edited_at ? " ·  ✎" : ""}
          </time>
          {canModify && !editing && (
            <span className="tools">
              <button className="btn ghost sm" onClick={() => setEditing(true)}>{t("issue.edit")}</button>
              <button className="btn ghost sm danger" onClick={onDelete} aria-label="Delete">✕</button>
            </span>
          )}
        </div>
        {editing ? (
          <div className="composer">
            <textarea className="textarea" value={v} onChange={(e) => setV(e.target.value)} />
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn primary sm" onClick={() => onEdit(v).then(() => setEditing(false))}>{t("issue.save")}</button>
              <button className="btn sm" onClick={() => { setV(c.body); setEditing(false); }}>{t("issue.cancel")}</button>
            </div>
          </div>
        ) : <Markdown text={c.body} />}
      </div>
    </div>
  );
}

export function IssueBody({ issueKey, onChanged, onOpen, onDeleted, header }: {
  issueKey: string; onChanged?: () => void; onOpen: (k: string) => void; onDeleted: () => void;
  header: (issue: IssueDetail | null, actions: { copy: () => void; remove: () => void; canDelete: boolean }) => React.ReactNode;
}) {
  const { t } = useT();
  const { user } = useSession();
  const [issue, setIssue] = useState<IssueDetail | null>(null);
  const [ctx, setCtx] = useState<Ctx | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [acts, setActs] = useState<Activity[]>([]);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);
  const [toast, setToast] = useState("");
  const [draft, setDraft] = useState("");
  const [newSub, setNewSub] = useState("");

  const load = useCallback(async () => {
    try {
      const i = await api.issue(issueKey);
      setIssue(i);
      setMissing(false);
      const [project, members, labels, cs, as, cycles, modules] = await Promise.all([
        api.project(i.project_key), api.members(i.project_key), api.labels(i.project_key),
        api.comments(issueKey), api.activity(issueKey), api.cycles(i.project_key), api.modules(i.project_key),
      ]);
      setCtx(projectData(project, members, labels, cycles, modules));
      setComments(cs);
      setActs(as);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMissing(true);
      else setError(e instanceof Error ? e.message : t("err.generic"));
    }
  }, [issueKey, t]);

  useEffect(() => {
    setIssue(null);
    load();
  }, [load]);

  async function patch(body: Record<string, unknown>) {
    setError("");
    try {
      const updated = await api.patchIssue(issueKey, body);
      setIssue(updated);
      setActs(await api.activity(issueKey));
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.generic"));
    }
  }

  async function sendComment() {
    if (!draft.trim()) return;
    const c = await api.addComment(issueKey, draft.trim());
    setComments((cs) => [...cs, c]);
    setDraft("");
  }

  async function addSubtask() {
    if (!newSub.trim() || !issue) return;
    try {
      await api.createIssue(issue.project_key, { title: newSub.trim(), parent_key: issue.key });
      setNewSub("");
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.generic"));
    }
  }

  const canDelete = !!issue && !!ctx && (ctx.can("issues.delete") || (issue.reporter?.id === user.id && ctx.canEdit));
  const actions = {
    canDelete,
    copy: () => {
      navigator.clipboard?.writeText(`${location.origin}/i/${issueKey}`).then(() => setToast(t("issue.copied")));
    },
    remove: async () => {
      if (!confirm(t("issue.deleteConfirm", { key: issueKey }))) return;
      await api.deleteIssue(issueKey);
      onChanged?.();
      onDeleted();
    },
  };

  if (missing) return <>{header(null, actions)}<div className="empty"><h2>{t("notFound")}</h2><p>{t("notFound.sub")}</p></div></>;
  if (!issue || !ctx) return <>{header(null, actions)}</>;
  const ro = !ctx.canEdit;
  const memberUsers = ctx.members.map((m) => m.user);
  const feed = [
    ...comments.map((c) => ({ at: c.created_at, el: (
      <CommentItem key={`c${c.id}`} c={c} canModify={c.author?.id === user.id || ctx.can("comments.moderate")}
                   onEdit={async (b) => { const u = await api.editComment(c.id, b); setComments((cs) => cs.map((x) => (x.id === c.id ? u : x))); }}
                   onDelete={async () => { await api.deleteComment(c.id); setComments((cs) => cs.filter((x) => x.id !== c.id)); }} />
    ) })),
    ...acts.map((a) => ({ at: a.created_at, el: <ActivityLine key={`a${a.id}`} a={a} /> })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  return (
    <>
      {header(issue, actions)}
      <div className="panel-body">
        <div className="issue-main">
          {error && <div className="banner" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
          {ro && <div className="banner info" style={{ marginBottom: 12 }}>{t("issue.readOnly")}</div>}
          {issue.parent_key && (
            <button className="btn ghost sm" style={{ marginBottom: 6, marginLeft: -8 }} onClick={() => onOpen(issue.parent_key!)}>
              ↰ {issue.parent_key}
            </button>
          )}
          <AutoTitle value={issue.title} disabled={ro} onSave={(v) => patch({ title: v })} />
          <Description value={issue.description} canEdit={!ro} onSave={(v) => patch({ description: v })} />

          <div className="section-h">
            {t("issue.subtasks")} {issue.subtasks.length > 0 && <span className="n num">{issue.subtasks_done}/{issue.subtasks_total}</span>}
            {issue.subtasks_total > 0 && <span className="progress"><i style={{ width: `${(100 * issue.subtasks_done) / issue.subtasks_total}%` }} /></span>}
          </div>
          {issue.subtasks.map((s) => (
            <div key={s.id} className={`subtask${["done", "cancelled"].includes(s.state.category) ? " closed" : ""}`}
                 role="button" tabIndex={0} onClick={() => onOpen(s.key)} onKeyDown={(e) => e.key === "Enter" && onOpen(s.key)}
                 style={{ cursor: "pointer" }}>
              <StateDot category={s.state.category} />
              <span className="key">{s.key}</span>
              <span className="title">{s.title}</span>
              <PriorityIcon priority={s.priority} />
              <DueDate due={s.due_date} category={s.state.category} />
              <Avatars users={s.assignees} />
            </div>
          ))}
          {ctx.can("issues.create") && (
            <form onSubmit={(e) => { e.preventDefault(); addSubtask(); }} style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <input className="input" placeholder={t("issue.addSubtask")} value={newSub} onChange={(e) => setNewSub(e.target.value)} />
              <button className="btn" disabled={!newSub.trim()}>+</button>
            </form>
          )}

          <div className="section-h">{t("issue.comments")} <span className="n num">{comments.length || ""}</span></div>
          <div className="feed">{feed.map((f) => f.el)}</div>
          {ctx.can("comments.create") && (
            <div className="composer">
              <textarea className="textarea" placeholder={t("issue.commentPh")} value={draft} onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendComment(); }} />
              <div><button className="btn primary sm" disabled={!draft.trim()} onClick={sendComment}>{t("issue.comment")}</button></div>
            </div>
          )}
        </div>

        <aside className="issue-side">
          <label className="side-field">
            <span>{t("issue.state")}</span>
            <select className="select" value={issue.state.id} disabled={ro} onChange={(e) => patch({ state_id: e.target.value })}>
              {ctx.project.states.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="side-field">
            <span>{t("issue.priority")}</span>
            <select className="select" value={issue.priority} disabled={ro} onChange={(e) => patch({ priority: e.target.value })}>
              {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
            </select>
          </label>
          <div className="side-field">
            <span>{t("issue.assignees")}</span>
            <MultiPicker items={memberUsers} selected={issue.assignees.map((a) => a.id)} disabled={ro}
                         placeholder={t("issue.unassigned")} searchable={(u) => `${u.display_name} ${u.username}`}
                         onChange={(ids) => patch({ assignee_ids: ids })}
                         render={(u) => <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}><Avatar user={u} />{u.display_name}</span>} />
          </div>
          <div className="side-field">
            <span>{t("issue.labels")}</span>
            <MultiPicker items={ctx.labels} selected={issue.labels.map((l) => l.id)} disabled={ro} placeholder={t("issue.none")}
                         onChange={(ids) => patch({ label_ids: ids })}
                         render={(l) => <span className="label-chip"><i style={{ background: l.color }} />{l.name}</span>} />
          </div>
          <label className="side-field">
            <span>{t("cycle.field")}</span>
            <select className="select" value={issue.sprint_id ?? ""} disabled={ro} onChange={(e) => patch({ sprint_id: e.target.value || null })}>
              <option value="">{t("cycle.none")}</option>
              {ctx.cycles.filter((c) => !c.closed || c.id === issue.sprint_id).map((c) => (
                <option key={c.id} value={c.id} disabled={c.closed}>{c.name}</option>
              ))}
            </select>
          </label>
          <div className="side-field">
            <span>{t("module.field")}</span>
            <MultiPicker items={ctx.modules} selected={issue.module_ids} disabled={ro} placeholder={t("module.none")}
                         onChange={(ids) => patch({ module_ids: ids })} render={(m) => <span>{m.name}</span>} />
          </div>
          <label className="side-field">
            <span>{t("issue.estimate")}</span>
            <input className="input num" type="number" min={0} step="0.5" defaultValue={issue.estimate ?? ""} disabled={ro}
                   key={`est${issue.estimate ?? ""}`}
                   onBlur={(e) => { const v = e.target.value === "" ? null : Number(e.target.value); if (v !== issue.estimate) patch({ estimate: v }); }} />
          </label>
          <label className="side-field">
            <span>{t("issue.type")}</span>
            <select className="select" value={issue.type} disabled={ro} onChange={(e) => patch({ type: e.target.value })}>
              {TYPES.map((x) => <option key={x} value={x}>{t(`type.${x}`)}</option>)}
            </select>
          </label>
          <div className="row2">
            <label className="side-field">
              <span>{t("issue.start")}</span>
              <input className="input" type="date" value={issue.start_date ?? ""} disabled={ro}
                     onChange={(e) => patch({ start_date: e.target.value || null })} />
            </label>
            <label className="side-field">
              <span>{t("issue.due")}</span>
              <input className="input" type="date" value={issue.due_date ?? ""} disabled={ro}
                     onChange={(e) => patch({ due_date: e.target.value || null })} />
            </label>
          </div>
          <label className="side-field">
            <span>{t("issue.parent")}</span>
            <input className="input num" defaultValue={issue.parent_key ?? ""} placeholder={`${ctx.project.key}-1`} disabled={ro}
                   key={issue.parent_key ?? ""}
                   onBlur={(e) => { const v = e.target.value.trim().toUpperCase(); if (v !== (issue.parent_key ?? "")) patch({ parent_key: v || null }); }} />
          </label>
          <div className="side-field">
            <span>{t("issue.reporter")}</span>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {issue.reporter && <><Avatar user={issue.reporter} />{issue.reporter.display_name}</>}
            </div>
          </div>
          <div className="side-field">
            <span>{t("issue.created")}</span>
            <div>{new Date(issue.created_at).toLocaleString()}</div>
          </div>
        </aside>
      </div>
      {toast && <Toast text={toast} onDone={() => setToast("")} />}
    </>
  );
}

export default function IssuePanel({ issueKey, onClose, onChanged, onOpen }: {
  issueKey: string; onClose: () => void; onChanged: () => void; onOpen: (k: string) => void;
}) {
  const { t } = useT();
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (e.key === "Escape" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag)) onClose();
    };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="panel" role="dialog" aria-modal="true" aria-label={issueKey}>
        <IssueBody issueKey={issueKey} onChanged={onChanged} onOpen={onOpen} onDeleted={onClose}
                   header={(issue, a) => (
                     <div className="panel-head">
                       {issue && <StateDot category={issue.state.category} />}
                       <a className="key" href={`/i/${issueKey}`} style={{ fontSize: 13 }}>{issueKey}</a>
                       <span style={{ flex: 1 }} />
                       <button className="btn ghost sm" onClick={a.copy}>{t("issue.copyLink")}</button>
                       {a.canDelete && <button className="btn ghost sm danger" onClick={a.remove}>{t("issue.delete")}</button>}
                       <button className="btn ghost sm" onClick={onClose} aria-label="Close">✕</button>
                     </div>
                   )} />
      </div>
    </>
  );
}
