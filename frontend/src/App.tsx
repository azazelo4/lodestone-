import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { api, Project, setUnauthorizedHandler, User } from "./api";
import { Avatar, Logo } from "./components/bits";
import NewProject from "./components/NewProject";
import { detectLang, I18n, Lang, translator, useT } from "./i18n";
import IssuePage from "./pages/IssuePage";
import Login from "./pages/Login";
import MyWork from "./pages/MyWork";
import ProjectView from "./pages/ProjectView";

interface Session {
  user: User;
  projects: Project[];
  reloadProjects: () => Promise<void>;
  signOut: () => Promise<void>;
}
const SessionCtx = createContext<Session | null>(null);
export const useSession = () => {
  const s = useContext(SessionCtx);
  if (!s) throw new Error("no session");
  return s;
};

function Shell() {
  const { user, projects, signOut } = useSession();
  const { t, lang, setLang } = useT();
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><Logo /> {t("app.name")}</div>
        <nav aria-label="Main">
          <NavLink to="/my" className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>{t("nav.my")}</NavLink>
          <div className="group">
            <span>{t("nav.projects")}</span>
            <button className="btn ghost sm" onClick={() => setCreating(true)} aria-label={t("nav.newProject")} title={t("nav.newProject")}>+</button>
          </div>
          {projects.length === 0 && <div className="hint" style={{ padding: "4px 8px" }}>{t("nav.noProjects")}</div>}
          {projects.map((p) => (
            <NavLink key={p.id} to={`/p/${p.key}`} className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>
              <span className="pkey">{p.key}</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</span>
              <span className="count num">{p.open_issues || ""}</span>
            </NavLink>
          ))}
        </nav>
        <div className="side-foot">
          <Avatar user={user} large />
          <div className="who">
            <div style={{ fontWeight: 500 }}>{user.display_name}</div>
            <div className="hint">{user.username}</div>
          </div>
          <div className="lang">
            {(["ru", "en"] as Lang[]).map((l) => (
              <button key={l} className={l === lang ? "on" : ""} onClick={() => setLang(l)}>{l.toUpperCase()}</button>
            ))}
          </div>
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <button className="btn ghost sm" onClick={signOut}>{t("nav.signOut")}</button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
      {creating && <NewProject onClose={() => setCreating(false)} onCreated={(p) => { setCreating(false); nav(`/p/${p.key}`); }} />}
    </div>
  );
}

function Authed({ user, setUser }: { user: User; setUser: (u: User | null) => void }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const reloadProjects = useCallback(async () => setProjects(await api.projects()), []);
  useEffect(() => {
    reloadProjects();
  }, [reloadProjects]);
  const signOut = useCallback(async () => {
    await api.logout().catch(() => {});
    setUser(null);
  }, [setUser]);
  const value = useMemo(() => ({ user, projects: projects ?? [], reloadProjects, signOut }), [user, projects, reloadProjects, signOut]);
  if (projects === null) return null;
  return (
    <SessionCtx.Provider value={value}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Navigate to={projects[0] ? `/p/${projects[0].key}` : "/my"} replace />} />
          <Route path="my" element={<MyWork />} />
          <Route path="p/:key/*" element={<ProjectView />} />
          <Route path="i/:issueKey" element={<IssuePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </SessionCtx.Provider>
  );
}

export default function App() {
  const [lang, setLangState] = useState<Lang>(detectLang());
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const i18n = useMemo(() => ({
    lang,
    t: translator(lang),
    setLang: (l: Lang) => {
      setLangState(l);
      try { localStorage.setItem("lodestone.lang", l); } catch { /* ignore */ }
      document.documentElement.lang = l;
    },
  }), [lang]);

  useEffect(() => {
    document.documentElement.lang = lang;
    setUnauthorizedHandler(() => setUser(null));
    api.me().then(setUser).catch(() => setUser(null));
  }, [lang]);

  return (
    <I18n.Provider value={i18n}>
      <BrowserRouter>
        {user === undefined ? null : user === null ? <Login onLogin={setUser} /> : <Authed user={user} setUser={setUser} />}
      </BrowserRouter>
    </I18n.Provider>
  );
}
