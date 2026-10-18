import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { api, Issue, Label, Member, Project } from "../api";
import Board from "../components/Board";
import IssueList from "../components/IssueList";
import IssuePanel from "../components/IssuePanel";
import NewIssue from "../components/NewIssue";
import ProjectSettings from "../components/ProjectSettings";
import { useT } from "../i18n";

export interface ProjectData {
  project: Project;
  members: Member[];
  labels: Label[];
  canEdit: boolean;
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
  const [newIn, setNewIn] = useState<string | null | undefined>(undefined); // state id; null = default
  const openKey = params.get("issue");

  const loadProject = useCallback(async () => {
    try {
      const [project, members, labels] = await Promise.all([api.project(key), api.members(key), api.labels(key)]);
      setData({ project, members, labels, canEdit: project.my_role === "admin" || project.my_role === "member" });
      setMissing(false);
    } catch {
      setMissing(true);
    }
  }, [key]);

  const loadIssues = useCallback(async () => {
    try {
      setIssues(await api.issues(key, { q: q.trim() || undefined, assignee: mine ? ["me"] : undefined, open_only: !showClosed }));
    } catch {
      /* project errors are handled by loadProject */
    }
  }, [key, q, mine, showClosed]);

  useEffect(() => {
    setData(null);
    loadProject();
  }, [loadProject]);
  useEffect(() => {
    const id = setTimeout(loadIssues, q ? 200 : 0);
    return () => clearTimeout(id);
  }, [loadIssues, q]);

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
          {project.my_role === "admin" && <NavLink to={`/p/${project.key}/settings`} className={tab}>{t("view.settings")}</NavLink>}
        </nav>
        <span className="spacer" />
        {data.canEdit && <button className="btn primary" onClick={() => setNewIn(null)}>{t("issue.new")}</button>}
      </div>
      <Routes>
        <Route path="settings" element={<div className="content"><ProjectSettings data={data} reload={loadProject} /></div>} />
        <Route path="*" element={
          <>
            <div className="filters">
              <input className="input" type="search" placeholder={t("filter.search")} value={q} onChange={(e) => setQ(e.target.value)} />
              <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />{t("filter.mine")}</label>
              <label className="check"><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />{t("filter.closed")}</label>
              {!data.canEdit && <span className="hint">{t("issue.readOnly")}</span>}
            </div>
            <div className="content">
              <Routes>
                <Route index element={<Board data={data} issues={issues} setIssues={setIssues} onOpen={openIssue}
                                             onAdd={(stateId) => setNewIn(stateId)} />} />
                <Route path="list" element={<IssueList issues={issues} onOpen={openIssue} />} />
              </Routes>
            </div>
          </>
        } />
      </Routes>
      {openKey && <IssuePanel issueKey={openKey} onClose={closeIssue} onChanged={loadIssues} onOpen={openIssue} />}
      {newIn !== undefined && (
        <NewIssue data={data} stateId={newIn} onClose={() => setNewIn(undefined)}
                  onCreated={(i) => { setNewIn(undefined); loadIssues(); loadProject(); openIssue(i.key); }} />
      )}
    </>
  );
}
