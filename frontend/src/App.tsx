import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { api, AuthConfig, Me, Project, setUnauthorizedHandler } from "./api";
import { Avatar, Logo } from "./components/bits";
import NewProject from "./components/NewProject";
import { detectLang, I18n, Lang, translator, useT } from "./i18n";
import Admin, { ADMIN_PERMS } from "./pages/Admin";
import IssuePage from "./pages/IssuePage";
import Login from "./pages/Login";
import MyNotifications from "./pages/MyNotifications";
import MyWork from "./pages/MyWork";
import ProjectView from "./pages/ProjectView";
import Setup from "./pages/Setup";

interface Session {
  user: Me;
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
          {ADMIN_PERMS.some((p) => user.permissions.includes(p)) && (
            <NavLink to="/admin" className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>{t("nav.admin")}</NavLink>
          )}
          <div className="group">
            <span>{t("nav.projects")}</span>
            {user.permissions.includes("projects.create") && (
              <button className="btn ghost sm" onClick={() => setCreating(true)} aria-label={t("nav.newProject")} title={t("nav.newProject")}>+</button>
            )}
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
        <div style={{ padding: "0 12px 12px", display: "flex", gap: 4, flexWrap: "wrap" }}>
          <NavLink to="/settings/notifications" className="btn ghost sm">{t("nav.notifications")}</NavLink>
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

function Authed({ user, setUser }: { user: Me; setUser: (u: Me | null) => void }) {
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
          <Route path="settings/notifications" element={<MyNotifications />} />
          <Route path="p/:key/*" element={<ProjectView />} />
          <Route path="i/:issueKey" element={<IssuePage />} />
          <Route path="admin/*" element={<Admin />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </SessionCtx.Provider>
  );
}

export default function App() {
  const [lang, setLangState] = useState<Lang>(detectLang());
  const [user, setUser] = useState<Me | null | undefined>(undefined);
  const [config, setConfig] = useState<AuthConfig | null>(null);
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
  }, [lang]);
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    api.authConfig().then(setConfig).catch(() => setConfig({ setup_required: false, password: true, password_providers: [], sso: [] }));
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  let body = null;
  if (config && user !== undefined) {
    if (config.setup_required && !user) body = <Setup onDone={(u) => { setConfig({ ...config, setup_required: false }); setUser(u); }} />;
    else if (!user) body = <Login config={config} onLogin={setUser} />;
    else body = <Authed user={user} setUser={setUser} />;
  }

  return (
    <I18n.Provider value={i18n}>
      <BrowserRouter>
        {body}
      </BrowserRouter>
    </I18n.Provider>
  );
}
