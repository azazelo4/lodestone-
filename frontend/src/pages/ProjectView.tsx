import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { api, Issue, Label, Member, Module, Project, Sprint } from "../api";
import Board from "../components/Board";
import IssueList from "../components/IssueList";
import IssuePanel from "../components/IssuePanel";
import NewIssue, { IssueDefaults } from "../components/NewIssue";
import ProjectSettings from "../components/ProjectSettings";
import { useT } from "../i18n";
import Analytics from "./Analytics";
import { Cycles, Modules } from "./Planning";

export interface ProjectData {
  project: Project;
  members: Member[];
  labels: Label[];
  cycles: Sprint[];
  modules: Module[];
  canEdit: boolean;
  can: (perm: string) => boolean;
}

export function projectData(project: Project, members: Member[], labels: Label[], cycles: Sprint[] = [],
                            modules: Module[] = []): ProjectData {
  const can = (perm: string) => project.my_permissions.includes(perm);
  return { project, members, labels, cycles, modules, canEdit: can("issues.edit"), can };
}

export default function ProjectView() {
  const { key = "" } = useParams();
  const { t } = useT();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<ProjectData | null>(null);
  const [missing, setMissing] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [q, setQ] = useState("");
  const [mine, setMine] = useState(false);
  const [showClosed, setShowClosed] = useState(true);
  const [cycle, setCycle] = useState(""); // cycle id, "none" or "" for all
  const [mod, setMod] = useState("");
  const [newIn, setNewIn] = useState<string | null | undefined>(undefined); // state id; null = default
  const [defaults, setDefaults] = useState<IssueDefaults>({});
  const [planTick, setPlanTick] = useState(0); // bumps when issues change, so planning pages reload
  const openKey = params.get("issue");

  const loadProject = useCallback(async () => {
    try {
      const [project, members, labels, cycles, modules] = await Promise.all([
        api.project(key), api.members(key), api.labels(key), api.cycles(key), api.modules(key)]);
      setData(projectData(project, members, labels, cycles, modules));
      setMissing(false);
    } catch {
      setMissing(true);
    }
  }, [key]);

  const loadIssues = useCallback(async () => {
    try {
      setIssues(await api.issues(key, {
        q: q.trim() || undefined, assignee: mine ? ["me"] : undefined, open_only: !showClosed,
        sprint_id: cycle || undefined, module_id: mod || undefined,
      }));
    } catch {
      /* project errors are handled by loadProject */
    }
  }, [key, q, mine, showClosed, cycle, mod]);

  useEffect(() => {
    setData(null);
    loadProject();
  }, [loadProject]);
  useEffect(() => {
    const id = setTimeout(loadIssues, q ? 200 : 0);
    return () => clearTimeout(id);
  }, [loadIssues, q]);

  const changed = () => { loadIssues(); setPlanTick((n) => n + 1); };
  const newIssue = (stateId: string | null, d: IssueDefaults = {}) => { setDefaults(d); setNewIn(stateId); };
  const openIssue = (k: string) => setParams((p) => { p.set("issue", k); return p; });
  const closeIssue = () => setParams((p) => { p.delete("issue"); return p; });

  if (missing) return <div className="empty"><h2>{t("notFound")}</h2><p>{t("notFound.sub")}</p></div>;
  if (!data) return null;
  const { project } = data;
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

  return (
    <>
      <div className="topbar">
        <span className="pkey">{project.key}</span>
        <h1>{project.name}</h1>
        <nav className="tabs" aria-label="Views">
          <NavLink end to={`/p/${project.key}`} className={tab}>{t("view.board")}</NavLink>
          <NavLink to={`/p/${project.key}/list`} className={tab}>{t("view.list")}</NavLink>
          <NavLink to={`/p/${project.key}/cycles`} className={tab}>{t("view.cycles")}</NavLink>
          <NavLink to={`/p/${project.key}/modules`} className={tab}>{t("view.modules")}</NavLink>
          <NavLink to={`/p/${project.key}/analytics`} className={tab}>{t("view.analytics")}</NavLink>
          {(data.can("project.manage") || data.can("members.manage")) && <NavLink to={`/p/${project.key}/settings`} className={tab}>{t("view.settings")}</NavLink>}
        </nav>
        <span className="spacer" />
        {data.can("issues.create") && (
          <button className="btn primary" onClick={() => newIssue(null, {
            sprint_id: cycle && cycle !== "none" ? cycle : undefined, module_ids: mod && mod !== "none" ? [mod] : undefined,
          })}>{t("issue.new")}</button>
        )}
      </div>
      <Routes>
        <Route path="settings" element={<div className="content"><ProjectSettings data={data} reload={loadProject} /></div>} />
        <Route path="cycles/*" element={<div className="content"><Cycles data={data} reload={loadProject} tick={planTick} onOpen={openIssue}
                                                                         onNewIssue={(d) => newIssue(null, d)} /></div>} />
        <Route path="modules/*" element={<div className="content"><Modules data={data} reload={loadProject} tick={planTick} onOpen={openIssue}
                                                                          onNewIssue={(d) => newIssue(null, d)} /></div>} />
        <Route path="analytics" element={<div className="content"><Analytics data={data} tick={planTick} /></div>} />
        <Route path="*" element={
          <>
            <div className="filters">
              <input className="input" type="search" placeholder={t("filter.search")} value={q} onChange={(e) => setQ(e.target.value)} />
              <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />{t("filter.mine")}</label>
              <label className="check"><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />{t("filter.closed")}</label>
              {data.cycles.length > 0 && (
                <select className="select sm" aria-label={t("filter.cycle")} value={cycle} onChange={(e) => setCycle(e.target.value)}>
                  <option value="">{t("filter.cycle")}: {t("filter.any")}</option>
                  <option value="none">{t("cycle.none")}</option>
                  {data.cycles.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              )}
              {data.modules.length > 0 && (
                <select className="select sm" aria-label={t("filter.module")} value={mod} onChange={(e) => setMod(e.target.value)}>
                  <option value="">{t("filter.module")}: {t("filter.any")}</option>
                  <option value="none">{t("module.none")}</option>
                  {data.modules.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
              )}
              {!data.canEdit && <span className="hint">{t("issue.readOnly")}</span>}
            </div>
            <div className="content">
              <Routes>
                <Route index element={<Board data={data} issues={issues} setIssues={setIssues} onOpen={openIssue}
                                             onAdd={(stateId) => newIssue(stateId, {
                                               sprint_id: cycle && cycle !== "none" ? cycle : undefined,
                                               module_ids: mod && mod !== "none" ? [mod] : undefined })} />} />
                <Route path="list" element={<IssueList issues={issues} onOpen={openIssue} />} />
              </Routes>
            </div>
          </>
        } />
      </Routes>
      {openKey && <IssuePanel issueKey={openKey} onClose={closeIssue} onChanged={changed} onOpen={openIssue} />}
      {newIn !== undefined && (
        <NewIssue data={data} stateId={newIn} defaults={defaults} onClose={() => setNewIn(undefined)}
                  onCreated={(i) => { setNewIn(undefined); changed(); loadProject(); openIssue(i.key); }} />
      )}
    </>
  );
}
