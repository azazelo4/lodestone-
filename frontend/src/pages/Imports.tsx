import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../App";
import { api, ApiError, ImportJob, ImportKind, ImportSource, RemoteProject } from "../api";
import { TKey, useT } from "../i18n";

const KINDS: ImportKind[] = ["jira", "plane", "confluence"];
const NAMES: Record<ImportKind, string> = { jira: "Jira", plane: "Plane", confluence: "Confluence" };
const PLACEHOLDER: Record<ImportKind, string> = {
  jira: "https://jira.corp.local", plane: "https://plane.corp.local", confluence: "https://acme.atlassian.net/wiki",
};
const STAT_KEYS = ["issues", "issues_updated", "comments", "cycles", "modules", "labels", "states", "members", "pages", "pages_updated"];

function suggestKey(s: string) {
  const k = s.toUpperCase().replace(/[^A-Z0-9]/g, "").replace(/^[0-9]+/, "").slice(0, 10);
  return k.length >= 2 ? k : "";
}

function ImportForm({ onStarted }: { onStarted: () => void }) {
  const { t } = useT();
  const { projects, reloadProjects } = useSession();
  const [src, setSrc] = useState<ImportSource>({ source: "jira", url: "", workspace: "", username: "", token: "" });
  const [remote, setRemote] = useState<RemoteProject[] | null>(null);
  const [pick, setPick] = useState("");
  const [into, setInto] = useState<"new" | "existing">("new");
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [existing, setExisting] = useState("");
  const [comments, setComments] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (patch: Partial<ImportSource>) => { setSrc({ ...src, ...patch }); setRemote(null); setPick(""); };
  const choose = (id: string, list = remote) => {
    setPick(id);
    const r = list?.find((x) => x.id === id);
    if (r) { setKey(suggestKey(r.key) || suggestKey(r.name)); setName(r.name); }
  };

  async function call(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
    } finally {
      setBusy(false);
    }
  }

  const load = () => call(async () => {
    const rows = await api.importRemote({ ...src, url: src.url.trim() });
    setRemote(rows);
    if (rows.length) choose(rows[0].id, rows);
  });
  const start = () => call(async () => {
    await api.startImport({ ...src, url: src.url.trim(), remote: src.source === "plane" ? pick : remote!.find((r) => r.id === pick)!.key,
                            target_key: into === "new" ? key : existing, target_name: name, include_comments: comments });
    setRemote(null);
    setPick("");
    setSrc({ ...src, token: "" });
    await reloadProjects();
    onStarted();
  });

  const cloudish = src.source !== "plane";
  const ready = src.url.trim().startsWith("http") && src.token && (src.source !== "plane" || src.workspace.trim());
  const target = into === "new" ? /^[A-Za-z][A-Za-z0-9]{1,9}$/.test(key) && !projects.some((p) => p.key === key.toUpperCase()) : !!existing;

  return (
    <div className="prov-form" style={{ maxWidth: 680 }}>
      {error && <div className="banner" role="alert">{error}</div>}
      <div className="seg" role="group" aria-label={t("imp.source")}>
        {KINDS.map((k) => <button key={k} className={src.source === k ? "on" : ""} onClick={() => set({ source: k })}>{NAMES[k]}</button>)}
      </div>
      <p className="hint" style={{ margin: 0 }}>{t(`imp.about.${src.source}` as TKey)}</p>
      <div className={src.source === "plane" ? "row2" : ""}>
        <label className="field"><span>{t("imp.url")}</span>
          <input className="input" value={src.url} placeholder={PLACEHOLDER[src.source]} onChange={(e) => set({ url: e.target.value })} /></label>
        {src.source === "plane" && (
          <label className="field"><span>{t("imp.workspace")}</span>
            <input className="input" value={src.workspace} placeholder="acme" onChange={(e) => set({ workspace: e.target.value })} /></label>
        )}
      </div>
      <div className={cloudish ? "row2" : ""}>
        {cloudish && (
          <label className="field"><span>{t("imp.username")}</span>
            <input className="input" autoComplete="off" value={src.username} onChange={(e) => set({ username: e.target.value })} />
            <span className="hint">{t("imp.username.hint")}</span></label>
        )}
        <label className="field"><span>{t(src.source === "plane" ? "imp.apiKey" : "imp.token")}</span>
          <input className="input" type="password" autoComplete="new-password" value={src.token} onChange={(e) => set({ token: e.target.value })} />
          <span className="hint">{t(`imp.token.${src.source}` as TKey)}</span></label>
      </div>
      <div><button className="btn" disabled={busy || !ready} onClick={load}>{busy && !remote ? t("imp.loading") : t("imp.load")}</button></div>

      {remote && remote.length === 0 && <div className="hint">{t("imp.noRemote")}</div>}
      {remote && remote.length > 0 && (
        <>
          <label className="field"><span>{t(src.source === "confluence" ? "imp.space" : "imp.project")}</span>
            <select className="select" value={pick} onChange={(e) => choose(e.target.value)}>
              {remote.map((r) => <option key={r.id} value={r.id}>{r.key ? `${r.key} · ${r.name}` : r.name}</option>)}
            </select></label>
          <div className="field">
            <span>{t("imp.target")}</span>
            <div className="seg" role="group" aria-label={t("imp.target")}>
              <button className={into === "new" ? "on" : ""} onClick={() => setInto("new")}>{t("imp.target.new")}</button>
              <button className={into === "existing" ? "on" : ""} disabled={!projects.length} onClick={() => setInto("existing")}>{t("imp.target.existing")}</button>
            </div>
          </div>
          {into === "new" ? (
            <div className="row2 key-name">
              <label className="field"><span>{t("project.key")}</span>
                <input className="input" value={key} maxLength={10} onChange={(e) => setKey(e.target.value.toUpperCase())} />
                {projects.some((p) => p.key === key.toUpperCase()) && <span className="hint bad">{t("imp.keyTaken")}</span>}</label>
              <label className="field"><span>{t("project.name")}</span>
                <input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
            </div>
          ) : (
            <label className="field"><span>{t("imp.target.existing")}</span>
              <select className="select" value={existing} onChange={(e) => setExisting(e.target.value)}>
                <option value="">—</option>
                {projects.map((p) => <option key={p.id} value={p.key}>{p.key} · {p.name}</option>)}
              </select>
              <span className="hint">{t("imp.rerun")}</span></label>
          )}
          {src.source !== "confluence" && (
            <label className="check"><input type="checkbox" checked={comments} onChange={(e) => setComments(e.target.checked)} />{t("imp.comments")}</label>
          )}
          <div><button className="btn primary" disabled={busy || !target || !pick} onClick={start}>{t("imp.start")}</button></div>
        </>
      )}
    </div>
  );
}

function JobRow({ job }: { job: ImportJob }) {
  const { t, lang } = useT();
  const when = (s: string) => new Date(s).toLocaleString(lang, { dateStyle: "short", timeStyle: "short" });
  const stats = STAT_KEYS.filter((k) => job.stats[k]).map((k) => t(`imp.stat.${k}` as TKey, { n: job.stats[k] }));
  const unmatched = job.stats.unmatched_users ?? [];
  const status = { queued: "pending", running: "pending", done: "sent", failed: "failed" }[job.status];
  let host = job.params.url;
  try { host = new URL(job.params.url).host; } catch { /* keep as is */ }
  return (
    <div className="member-row job-row">
      <span className={`tag status-${status}`} style={{ marginLeft: 0 }}>{t(`imp.status.${job.status}` as TKey)}</span>
      <div className="name">
        <div>
          <b>{NAMES[job.source]}</b> {job.params.remote} <span className="hint">({host})</span> →{" "}
          {job.project_key && <Link to={`/p/${job.project_key}${job.source === "confluence" ? "/docs" : ""}`}>{job.project_key}</Link>}
        </div>
        <div className="hint">{job.created_by?.display_name ?? "—"} · {when(job.created_at)}{stats.length > 0 && ` · ${stats.join(", ")}`}</div>
        {job.error && <div className="hint bad" style={{ overflowWrap: "anywhere" }}>{job.error}</div>}
        {unmatched.length > 0 && <div className="hint">{t("imp.unmatched", { names: unmatched.join(", ") })}</div>}
        {job.log && (
          <details>
            <summary className="hint">{t("imp.log")}</summary>
            <pre className="job-log">{job.log}</pre>
          </details>
        )}
      </div>
    </div>
  );
}

export default function Imports() {
  const { t } = useT();
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const load = useCallback(async () => setJobs(await api.imports()), []);
  useEffect(() => { load().catch(() => {}); }, [load]);
  const active = jobs.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => load().catch(() => {}), 2000);
    return () => clearInterval(id);
  }, [active, load]);
  return (
    <>
      <section><h3>{t("imp.title")}</h3><ImportForm onStarted={load} /></section>
      <section>
        <h3>{t("imp.jobs")}</h3>
        {jobs.length === 0 && <div className="hint" style={{ padding: "8px 0" }}>{t("imp.noJobs")}</div>}
        {jobs.map((j) => <JobRow key={j.id} job={j} />)}
      </section>
    </>
  );
}
