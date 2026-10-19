import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import {
  api, ApiError, Category, CycleStatus, Issue, Module, ModuleIn, ModuleStatus, ProgressDetail, Sprint,
} from "../api";
import { Avatar, Modal, StateDot } from "../components/bits";
import { ChartCard, ProgressBar, Row, Series, TimeChart, useDayLabel } from "../components/charts";
import IssueList from "../components/IssueList";
import type { IssueDefaults } from "../components/NewIssue";
import { TKey, useT } from "../i18n";
import type { ProjectData } from "./ProjectView";

interface PageProps {
  data: ProjectData;
  reload: () => Promise<void>;
  tick: number;
  onOpen: (key: string) => void;
  onNewIssue: (d: IssueDefaults) => void;
}

const CATS: Category[] = ["done", "in_progress", "todo", "backlog", "cancelled"];
const MODULE_STATUSES: ModuleStatus[] = ["backlog", "planned", "in_progress", "paused", "completed", "cancelled"];

function useDate() {
  const { lang } = useT();
  return (iso: string | null) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString(lang, {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "—");
}

function daysBetween(a: string, b: string) {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
}

const todayIso = () => new Date().toISOString().slice(0, 10);

function useErrors() {
  const { t } = useT();
  const [error, setError] = useState("");
  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setError("");
    try {
      await fn();
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
      return false;
    }
  }, [t]);
  return { error, setError, run };
}

// ---------- shared progress view
function Burndown({ detail }: { detail: ProgressDetail }) {
  const { t } = useT();
  const day = useDayLabel();
  const [points, setPoints] = useState(false);
  const hasPoints = detail.progress.points_scope > 0;
  const pts = detail.burndown;
  const n = pts.length;
  const startScope = pts.find((p) => p.scope !== null && (points ? p.points_scope : p.scope))?.[points ? "points_scope" : "scope"]
    ?? (points ? detail.progress.points_scope : detail.progress.scope);
  const rows: Row[] = pts.map((p, i) => {
    const scope = points ? p.points_scope : p.scope;
    const done = points ? p.points_done : p.done;
    return {
      label: day(p.date), tip: day(p.date),
      values: {
        remaining: scope === null || done === null ? null : scope - done,
        ideal: n > 1 ? Math.max(0, startScope * (1 - i / (n - 1))) : startScope,
      },
    };
  });
  const series: Series[] = [
    { key: "remaining", name: t("chart.remaining"), color: "var(--viz-a)" },
    { key: "ideal", name: t("chart.ideal"), color: "var(--muted)", dashed: true },
  ];
  return (
    <ChartCard title={t("chart.burndown")} hint={t("chart.burndownHint")} series={series} rows={rows}>
      {hasPoints && (
        <div className="seg" role="group" aria-label={t("chart.burndown")}>
          <button className={points ? "" : "on"} onClick={() => setPoints(false)}>{t("chart.byCount")}</button>
          <button className={points ? "on" : ""} onClick={() => setPoints(true)}>{t("chart.byPoints")}</button>
        </div>
      )}
      <TimeChart rows={rows} series={series} label={t("chart.burndown")} />
    </ChartCard>
  );
}

function ProgressSide({ detail, dates }: { detail: ProgressDetail; dates: React.ReactNode }) {
  const { t } = useT();
  const p = detail.progress;
  return (
    <div className="plan-side">
      <section className="chart-card">
        <div className="chart-head"><h3>{t("progress.title")}</h3><b className="num">{p.percent}%</b></div>
        <ProgressBar p={p} />
        <p className="hint" style={{ margin: "6px 0 8px" }}>
          {t("progress.done", { done: p.done, scope: p.scope })}
          {p.points_scope > 0 && <><br />{t("progress.points", { done: p.points_done, scope: p.points_scope })}</>}
        </p>
        {CATS.map((c) => (
          <div className="cat-row" key={c}><StateDot category={c} />{t(`cat.${c}` as TKey)}<span className="n num">{p.by_category[c] ?? 0}</span></div>
        ))}
      </section>
      <section className="chart-card">
        <div className="chart-head"><h3>{t("progress.dates")}</h3></div>
        {dates}
      </section>
      {detail.people.length > 0 && (
        <section className="chart-card">
          <div className="chart-head"><h3>{t("progress.people")}</h3></div>
          {detail.people.map((u) => (
            <div className="cat-row" key={u.user_id}>
              <Avatar user={{ id: u.user_id, username: u.name, display_name: u.name }} />{u.name}
              <span className="n num">{u.done}/{u.total}</span>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function PlanIssues({ projectKey, filter, tick, onOpen }: {
  projectKey: string; filter: { sprint_id?: string; module_id?: string }; tick: number; onOpen: (k: string) => void;
}) {
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const { sprint_id, module_id } = filter;
  useEffect(() => {
    api.issues(projectKey, { sprint_id, module_id }).then(setIssues).catch(() => setIssues([]));
  }, [projectKey, sprint_id, module_id, tick]);
  if (!issues) return null;
  return <div className="chart-card" style={{ padding: 0, overflow: "hidden" }}><IssueList issues={issues} onOpen={onOpen} /></div>;
}

// ---------- cycles
function CycleForm({ cycle, error, onSave, onClose }: {
  cycle: Partial<Sprint>; error: string; onSave: (v: { name: string; goal: string; start_date: string | null; end_date: string | null }) => Promise<boolean>;
  onClose: () => void;
}) {
  const { t } = useT();
  const [name, setName] = useState(cycle.name ?? "");
  const [goal, setGoal] = useState(cycle.goal ?? "");
  const [start, setStart] = useState(cycle.start_date ?? "");
  const [end, setEnd] = useState(cycle.end_date ?? "");
  const bad = !!(start && end && end < start);
  const save = () => onSave({ name: name.trim(), goal, start_date: start || null, end_date: end || null });
  return (
    <Modal title={cycle.id ? t("cycle.edit") : t("cycle.new")} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>{t("issue.cancel")}</button>
        <button className="btn primary" disabled={!name.trim() || bad} onClick={save}>{t("admin.save")}</button>
      </>
    }>
      {error && <div className="banner" role="alert">{error}</div>}
      <label className="field"><span>{t("project.name")}</span>
        <input className="input" autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
      <label className="field"><span>{t("cycle.goal")}</span>
        <textarea className="textarea" style={{ minHeight: 60 }} value={goal} onChange={(e) => setGoal(e.target.value)} /></label>
      <div className="row2">
        <label className="field"><span>{t("cycle.start")}</span>
          <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="field"><span>{t("cycle.end")}</span>
          <input className="input" type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} /></label>
      </div>
    </Modal>
  );
}

function CompleteCycle({ cycle, others, onDone, onClose }: {
  cycle: Sprint; others: Sprint[]; onDone: (moveTo: string | null) => Promise<boolean>; onClose: () => void;
}) {
  const { t } = useT();
  const unfinished = cycle.progress.total - (cycle.progress.by_category.done ?? 0) - (cycle.progress.by_category.cancelled ?? 0);
  const next = others.find((o) => o.status === "upcoming") ?? others[0];
  const [moveTo, setMoveTo] = useState(next?.id ?? "");
  return (
    <Modal title={t("cycle.completeTitle", { name: cycle.name })} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>{t("issue.cancel")}</button>
        <button className="btn primary" onClick={() => onDone(moveTo || null)}>{t("cycle.complete")}</button>
      </>
    }>
      {unfinished > 0 ? (
        <label className="field"><span>{t("cycle.completeText", { n: unfinished })}</span>
          <select className="select" value={moveTo} onChange={(e) => setMoveTo(e.target.value)}>
            {others.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            <option value="">{t("cycle.moveNone")}</option>
          </select>
        </label>
      ) : <p style={{ margin: 0 }}>{t("progress.done", { done: cycle.progress.done, scope: cycle.progress.scope })}</p>}
    </Modal>
  );
}

function CycleMeta({ c }: { c: Sprint }) {
  const { t } = useT();
  const date = useDate();
  const today = todayIso();
  let left = "";
  if (c.status === "active" && c.end_date) left = t("cycle.daysLeft", { n: daysBetween(today, c.end_date) });
  if (c.status === "ended" && c.end_date) left = t("cycle.overdueBy", { n: daysBetween(c.end_date, today) });
  return (
    <>
      <span className={`badge ${c.status}`}>{t(`cycle.status.${c.status}` as TKey)}</span>
      {(c.start_date || c.end_date) && <span>{date(c.start_date)} – {date(c.end_date)}</span>}
      {left && <span>{left}</span>}
    </>
  );
}

function CycleList({ data, onNew }: { data: ProjectData; onNew: () => void }) {
  const { t } = useT();
  const nav = useNavigate();
  const groups: { key: string; title: string; statuses: CycleStatus[] }[] = [
    { key: "current", title: t("cycle.group.current"), statuses: ["active", "ended"] },
    { key: "upcoming", title: t("cycle.group.upcoming"), statuses: ["upcoming", "draft"] },
    { key: "completed", title: t("cycle.group.completed"), statuses: ["completed"] },
  ];
  return (
    <div className="page" style={{ maxWidth: 1100 }}>
      <div className="toolbar">
        <span className="spacer" />
        {data.can("sprints.manage") && <button className="btn" onClick={onNew}>+ {t("cycle.new")}</button>}
      </div>
      {data.cycles.length === 0 && <div className="empty"><p>{t("cycle.empty")}</p></div>}
      {groups.map((g) => {
        const rows = data.cycles.filter((c) => g.statuses.includes(c.status));
        if (!rows.length) return null;
        return (
          <div className="plan-group" key={g.key}>
            <h3>{g.title}</h3>
            <div className="plan-list">
              {rows.map((c) => (
                <button key={c.id} className="plan-card" onClick={() => nav(c.id)}>
                  <div>
                    <div className="name">{c.name}</div>
                    <div className="meta"><CycleMeta c={c} /></div>
                  </div>
                  <div className="pct"><ProgressBar p={c.progress} />{t("progress.done", { done: c.progress.done, scope: c.progress.scope })}</div>
                  <b className="num">{c.progress.percent}%</b>
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CycleDetail({ data, reload, tick, onOpen, onNewIssue }: PageProps) {
  const { id = "" } = useParams();
  const { t } = useT();
  const date = useDate();
  const nav = useNavigate();
  const { error, run } = useErrors();
  const [detail, setDetail] = useState<ProgressDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [completing, setCompleting] = useState(false);
  const key = data.project.key;
  const cycle = data.cycles.find((c) => c.id === id);
  useEffect(() => { api.cycleProgress(key, id).then(setDetail).catch(() => setDetail(null)); }, [key, id, tick, data.cycles]);
  if (!cycle) return <div className="page"><Link to="..">← {t("cycle.back")}</Link></div>;
  const manage = data.can("sprints.manage");
  return (
    <div className="page" style={{ maxWidth: 1200 }}>
      <Link to=".." relative="path" className="hint">← {t("cycle.back")}</Link>
      <div className="plan-head" style={{ marginTop: 8 }}>
        <h2>{cycle.name}</h2>
        <span className="meta" style={{ display: "flex", gap: 10, color: "var(--muted)", fontSize: 13 }}><CycleMeta c={cycle} /></span>
        <span className="spacer" />
        {data.can("issues.create") && !cycle.closed && <button className="btn" onClick={() => onNewIssue({ sprint_id: cycle.id })}>+ {t("issue.new")}</button>}
        {manage && <button className="btn ghost sm" onClick={() => setEditing(true)}>{t("admin.edit")}</button>}
        {manage && !cycle.closed && <button className="btn primary" onClick={() => setCompleting(true)}>{t("cycle.complete")}</button>}
        {manage && cycle.closed && (
          <button className="btn ghost sm" onClick={() => run(() => api.patchCycle(key, cycle.id, { closed: false })).then(reload)}>{t("cycle.reopen")}</button>
        )}
        {manage && (
          <button className="btn ghost sm danger" onClick={() => confirm(t("admin.deleteConfirm", { name: cycle.name }))
            && run(() => api.deleteCycle(key, cycle.id)).then((ok) => { if (ok) { reload(); nav(".."); } })}>{t("admin.delete")}</button>
        )}
      </div>
      {cycle.goal && <p className="hint" style={{ marginTop: 0 }}>{cycle.goal}</p>}
      {error && <div className="banner" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
      {detail && (
        <div className="plan-detail">
          <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
            {detail.progress.total > 0 ? <Burndown detail={detail} /> : <div className="empty"><p>{t("progress.noIssues")}</p></div>}
            <PlanIssues projectKey={key} filter={{ sprint_id: cycle.id }} tick={tick} onOpen={onOpen} />
          </div>
          <ProgressSide detail={detail} dates={(
            <dl>
              <dt>{t("cycle.start")}</dt><dd>{date(cycle.start_date ?? detail.start)}</dd>
              <dt>{t("cycle.end")}</dt><dd>{date(cycle.end_date)}</dd>
            </dl>
          )} />
        </div>
      )}
      {editing && (
        <CycleForm cycle={cycle} error={error} onClose={() => setEditing(false)}
                   onSave={(v) => run(() => api.patchCycle(key, cycle.id, v)).then((ok) => { if (ok) { setEditing(false); reload(); } return ok; })} />
      )}
      {completing && (
        <CompleteCycle cycle={cycle} others={data.cycles.filter((c) => !c.closed && c.id !== cycle.id)} onClose={() => setCompleting(false)}
                       onDone={(moveTo) => run(() => api.completeCycle(key, cycle.id, moveTo)).then((ok) => { if (ok) { setCompleting(false); reload(); } return ok; })} />
      )}
    </div>
  );
}

export function Cycles(props: PageProps) {
  const { data, reload } = props;
  const { error, run } = useErrors();
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  return (
    <>
      <Routes>
        <Route index element={<CycleList data={data} onNew={() => setCreating(true)} />} />
        <Route path=":id" element={<CycleDetail {...props} />} />
      </Routes>
      {creating && (
        <CycleForm cycle={{}} error={error} onClose={() => setCreating(false)} onSave={async (v) => {
          let id = "";
          const ok = await run(async () => { id = (await api.addCycle(data.project.key, v)).id; });
          if (ok) { setCreating(false); await reload(); nav(`/p/${data.project.key}/cycles/${id}`); }
          return ok;
        }} />
      )}
    </>
  );
}

// ---------- modules
function ModuleForm({ module, data, error, onSave, onClose }: {
  module: Partial<Module>; data: ProjectData; error: string; onSave: (v: ModuleIn) => Promise<boolean>; onClose: () => void;
}) {
  const { t } = useT();
  const [f, setF] = useState<ModuleIn>({
    name: module.name ?? "", description: module.description ?? "", status: module.status ?? "planned",
    lead_id: module.lead?.id ?? null, start_date: module.start_date ?? null, target_date: module.target_date ?? null,
  });
  const bad = !!(f.start_date && f.target_date && f.target_date < f.start_date);
  return (
    <Modal title={module.id ? t("module.edit") : t("module.new")} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>{t("issue.cancel")}</button>
        <button className="btn primary" disabled={!f.name.trim() || bad} onClick={() => onSave({ ...f, name: f.name.trim() })}>{t("admin.save")}</button>
      </>
    }>
      {error && <div className="banner" role="alert">{error}</div>}
      <label className="field"><span>{t("project.name")}</span>
        <input className="input" autoFocus value={f.name} maxLength={120} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label className="field"><span>{t("issue.description")}</span>
        <textarea className="textarea" style={{ minHeight: 60 }} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
      <div className="row2">
        <label className="field"><span>{t("module.status")}</span>
          <select className="select" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as ModuleStatus })}>
            {MODULE_STATUSES.map((s) => <option key={s} value={s}>{t(`module.status.${s}` as TKey)}</option>)}
          </select></label>
        <label className="field"><span>{t("module.lead")}</span>
          <select className="select" value={f.lead_id ?? ""} onChange={(e) => setF({ ...f, lead_id: e.target.value || null })}>
            <option value="">—</option>
            {data.members.map((m) => <option key={m.user.id} value={m.user.id}>{m.user.display_name}</option>)}
          </select></label>
      </div>
      <div className="row2">
        <label className="field"><span>{t("cycle.start")}</span>
          <input className="input" type="date" value={f.start_date ?? ""} onChange={(e) => setF({ ...f, start_date: e.target.value || null })} /></label>
        <label className="field"><span>{t("module.target")}</span>
          <input className="input" type="date" value={f.target_date ?? ""} min={f.start_date ?? undefined}
                 onChange={(e) => setF({ ...f, target_date: e.target.value || null })} /></label>
      </div>
    </Modal>
  );
}

function ModuleMeta({ m }: { m: Module }) {
  const { t } = useT();
  const date = useDate();
  return (
    <>
      <span className={`badge ${m.status}`}>{t(`module.status.${m.status}` as TKey)}</span>
      {m.lead && <span>{m.lead.display_name}</span>}
      {m.target_date && <span>{t("module.target")}: {date(m.target_date)}</span>}
    </>
  );
}

function ModuleList({ data, onNew }: { data: ProjectData; onNew: () => void }) {
  const { t } = useT();
  const nav = useNavigate();
  return (
    <div className="page" style={{ maxWidth: 1100 }}>
      <div className="toolbar">
        <span className="spacer" />
        {data.can("modules.manage") && <button className="btn" onClick={onNew}>+ {t("module.new")}</button>}
      </div>
      {data.modules.length === 0 && <div className="empty"><p>{t("module.empty")}</p></div>}
      <div className="plan-list">
        {data.modules.map((m) => (
          <button key={m.id} className="plan-card" onClick={() => nav(m.id)}>
            <div>
              <div className="name">{m.name}</div>
              <div className="meta"><ModuleMeta m={m} /></div>
            </div>
            <div className="pct"><ProgressBar p={m.progress} />{t("progress.done", { done: m.progress.done, scope: m.progress.scope })}</div>
            <b className="num">{m.progress.percent}%</b>
          </button>
        ))}
      </div>
    </div>
  );
}

function ModuleDetail({ data, reload, tick, onOpen, onNewIssue }: PageProps) {
  const { id = "" } = useParams();
  const { t } = useT();
  const date = useDate();
  const nav = useNavigate();
  const { error, run } = useErrors();
  const [detail, setDetail] = useState<ProgressDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const key = data.project.key;
  const m = data.modules.find((x) => x.id === id);
  useEffect(() => { api.moduleProgress(key, id).then(setDetail).catch(() => setDetail(null)); }, [key, id, tick, data.modules]);
  if (!m) return <div className="page"><Link to="..">← {t("module.back")}</Link></div>;
  const manage = data.can("modules.manage");
  return (
    <div className="page" style={{ maxWidth: 1200 }}>
      <Link to=".." relative="path" className="hint">← {t("module.back")}</Link>
      <div className="plan-head" style={{ marginTop: 8 }}>
        <h2>{m.name}</h2>
        <span style={{ display: "flex", gap: 10, color: "var(--muted)", fontSize: 13 }}><ModuleMeta m={m} /></span>
        <span className="spacer" />
        {data.can("issues.create") && <button className="btn" onClick={() => onNewIssue({ module_ids: [m.id] })}>+ {t("issue.new")}</button>}
        {manage && <button className="btn ghost sm" onClick={() => setEditing(true)}>{t("admin.edit")}</button>}
        {manage && (
          <button className="btn ghost sm danger" onClick={() => confirm(t("admin.deleteConfirm", { name: m.name }))
            && run(() => api.deleteModule(key, m.id)).then((ok) => { if (ok) { reload(); nav(".."); } })}>{t("admin.delete")}</button>
        )}
      </div>
      {m.description && <p className="hint" style={{ marginTop: 0 }}>{m.description}</p>}
      {error && <div className="banner" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
      {detail && (
        <div className="plan-detail">
          <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
            {detail.progress.total > 0 ? <Burndown detail={detail} /> : <div className="empty"><p>{t("progress.noIssues")}</p></div>}
            <PlanIssues projectKey={key} filter={{ module_id: m.id }} tick={tick} onOpen={onOpen} />
          </div>
          <ProgressSide detail={detail} dates={(
            <dl>
              <dt>{t("cycle.start")}</dt><dd>{date(m.start_date ?? detail.start)}</dd>
              <dt>{t("module.target")}</dt><dd>{date(m.target_date)}</dd>
            </dl>
          )} />
        </div>
      )}
      {editing && (
        <ModuleForm module={m} data={data} error={error} onClose={() => setEditing(false)}
                    onSave={(v) => run(() => api.patchModule(key, m.id, v)).then((ok) => { if (ok) { setEditing(false); reload(); } return ok; })} />
      )}
    </div>
  );
}

export function Modules(props: PageProps) {
  const { data, reload } = props;
  const { error, run } = useErrors();
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  return (
    <>
      <Routes>
        <Route index element={<ModuleList data={data} onNew={() => setCreating(true)} />} />
        <Route path=":id" element={<ModuleDetail {...props} />} />
      </Routes>
      {creating && (
        <ModuleForm module={{}} data={data} error={error} onClose={() => setCreating(false)} onSave={async (v) => {
          let id = "";
          const ok = await run(async () => { id = (await api.addModule(data.project.key, v)).id; });
          if (ok) { setCreating(false); await reload(); nav(`/p/${data.project.key}/modules/${id}`); }
          return ok;
        }} />
      )}
    </>
  );
}
