import { useEffect, useRef, useState } from "react";
import { useSession } from "../App";
import { api, ApiError, Category, Role, UserBrief } from "../api";
import { useT } from "../i18n";
import type { ProjectData } from "../pages/ProjectView";
import { Avatar, StateDot, Toast, useOutside } from "./bits";

const ROLES: Role[] = ["admin", "member", "viewer"];
const CATS: Category[] = ["backlog", "todo", "in_progress", "done", "cancelled"];

function UserSearch({ exclude, onPick }: { exclude: string[]; onPick: (u: UserBrief) => void }) {
  const { t } = useT();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<UserBrief[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, () => setOpen(false), open);
  useEffect(() => {
    if (!q.trim()) { setRes([]); return; }
    const id = setTimeout(() => api.searchUsers(q).then((r) => { setRes(r.filter((u) => !exclude.includes(u.id))); setOpen(true); }), 200);
    return () => clearTimeout(id);
  }, [q, exclude]);
  return (
    <div className="picker" ref={ref} style={{ maxWidth: 420 }}>
      <input className="input" placeholder={t("project.findUser")} value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => res.length && setOpen(true)} />
      {open && res.length > 0 && (
        <div className="pop">
          {res.map((u) => (
            <button key={u.id} className="opt" onClick={() => { onPick(u); setQ(""); setOpen(false); }}>
              <Avatar user={u} /> {u.display_name} <span className="hint">{u.username}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ProjectSettings({ data, reload }: { data: ProjectData; reload: () => Promise<void> }) {
  const { t } = useT();
  const { reloadProjects } = useSession();
  const { project, members } = data;
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [priv, setPriv] = useState(project.is_private);
  const [newState, setNewState] = useState("");
  const [newCat, setNewCat] = useState<Category>("todo");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setError("");
    try {
      await fn();
      await reload();
      if (ok) setToast(ok);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
    }
  }

  return (
    <div className="page settings-grid">
      {error && <div className="banner" role="alert">{error}</div>}
      <section>
        <h3>{t("project.general")}</h3>
        <div style={{ display: "grid", gap: 12, maxWidth: 520 }}>
          <label className="field"><span>{t("project.name")}</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field"><span>{t("issue.description")}</span>
            <textarea className="textarea" style={{ minHeight: 70 }} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className="check"><input type="radio" checked={priv} onChange={() => setPriv(true)} />{t("project.private")}</label>
          <label className="check"><input type="radio" checked={!priv} onChange={() => setPriv(false)} />{t("project.public")}</label>
          <div>
            <button className="btn primary" onClick={() => run(async () => {
              await api.patchProject(project.key, { name, description, is_private: priv });
              await reloadProjects();
            }, t("project.saved"))}>{t("project.save")}</button>
          </div>
        </div>
      </section>

      <section>
        <h3>{t("project.members")} <span className="hint num">{members.length}</span></h3>
        <UserSearch exclude={members.map((m) => m.user.id)} onPick={(u) => run(() => api.addMember(project.key, u.id, "member"))} />
        <div style={{ marginTop: 8 }}>
          {members.map((m) => (
            <div className="member-row" key={m.user.id}>
              <Avatar user={m.user} large />
              <div className="name"><div>{m.user.display_name}</div><div className="hint">{m.user.username}</div></div>
              <select className="select" value={m.role} aria-label={`${m.user.display_name} role`}
                      onChange={(e) => run(() => api.setRole(project.key, m.user.id, e.target.value as Role))}>
                {ROLES.map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}
              </select>
              <button className="btn ghost sm danger" onClick={() => run(() => api.removeMember(project.key, m.user.id))}>{t("project.remove")}</button>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3>{t("project.states")}</h3>
        {project.states.map((s) => (
          <div className="state-row" key={s.id}>
            <StateDot category={s.category} />
            <input className="input" defaultValue={s.name} aria-label="State name"
                   onBlur={(e) => e.target.value.trim() && e.target.value !== s.name && run(() => api.patchState(project.key, s.id, { name: e.target.value.trim() }))} />
            <select className="select" value={s.category} onChange={(e) => run(() => api.patchState(project.key, s.id, { category: e.target.value as Category }))}>
              {CATS.map((c) => <option key={c} value={c}>{t(`cat.${c}`)}</option>)}
            </select>
          </div>
        ))}
        <form className="state-row" onSubmit={(e) => { e.preventDefault(); if (newState.trim()) run(() => api.addState(project.key, newState.trim(), newCat)).then(() => setNewState("")); }}>
          <StateDot category={newCat} />
          <input className="input" placeholder={t("project.addState")} value={newState} onChange={(e) => setNewState(e.target.value)} />
          <select className="select" value={newCat} onChange={(e) => setNewCat(e.target.value as Category)}>
            {CATS.map((c) => <option key={c} value={c}>{t(`cat.${c}`)}</option>)}
          </select>
          <button className="btn" disabled={!newState.trim()}>+</button>
        </form>
      </section>
      {toast && <Toast text={toast} onDone={() => setToast("")} />}
    </div>
  );
}
