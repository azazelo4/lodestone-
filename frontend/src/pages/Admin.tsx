import { useCallback, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useSession } from "../App";
import { api, ApiError, Binding, BindingIn, Provider, ProviderBrief, ProviderIn, ProviderType, Role, RoleBrief, User } from "../api";
import { Modal, Toast } from "../components/bits";
import ProviderForm, { emptyProvider } from "../components/ProviderForm";
import { TKey, useT } from "../i18n";

export const ADMIN_PERMS = ["auth.manage", "users.manage", "roles.manage"];

export function roleName(t: (k: TKey) => string, r: RoleBrief & { builtin?: boolean }) {
  return ["admin", "member", "viewer", "user"].includes(r.key) ? t(`role.${r.key}` as TKey) : r.name;
}

function useRunner() {
  const { t } = useT();
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const run = useCallback(async (fn: () => Promise<unknown>, ok?: string) => {
    setError("");
    try {
      await fn();
      if (ok) setToast(ok);
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
      return false;
    }
  }, [t]);
  const ui = (
    <>
      {error && <div className="banner" role="alert">{error}</div>}
      {toast && <Toast text={toast} onDone={() => setToast("")} />}
    </>
  );
  return { run, ui };
}

// ---------- sign-in providers
function Providers() {
  const { t } = useT();
  const { run, ui } = useRunner();
  const [rows, setRows] = useState<Provider[]>([]);
  const [edit, setEdit] = useState<{ id?: string; value: ProviderIn; secretsSet: string[] } | null>(null);
  const [baseUrl, setBaseUrl] = useState(location.origin);
  const load = useCallback(async () => setRows(await api.providers()), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.setupStatus().then((s) => setBaseUrl(s.base_url)).catch(() => {}); }, []);

  async function save() {
    if (!edit) return;
    const { id, value } = edit;
    const ok = await run(() => (id
      ? api.patchProvider(id, { name: value.name, enabled: value.enabled, config: value.config })
      : api.createProvider(value)), t("project.saved"));
    if (ok) { setEdit(null); load(); }
  }

  function addNew(type: ProviderType) {
    setEdit({ value: emptyProvider(type, rows.filter((r) => r.type === type).length + 1), secretsSet: [] });
  }

  return (
    <section>
      {ui}
      {rows.map((p) => (
        <div className="member-row" key={p.id}>
          <div className="name">
            <div>{p.name} {!p.enabled && <span className="tag">{t("admin.disabled")}</span>}
              {p.type === "local" && p.config.admins_only && <span className="tag">{t("admin.adminsOnly")}</span>}</div>
            <div className="hint">{t(`prov.type.${p.type}`)} · {p.slug}</div>
          </div>
          <label className="check"><input type="checkbox" checked={p.enabled}
            onChange={(e) => run(() => api.patchProvider(p.id, { enabled: e.target.checked })).then(load)} />{t("prov.enabled")}</label>
          {p.type === "local" ? (
            <label className="check"><input type="checkbox" checked={!!p.config.admins_only}
              onChange={(e) => run(() => api.patchProvider(p.id, { config: { admins_only: e.target.checked } })).then(load)} />{t("admin.adminsOnly")}</label>
          ) : (
            <>
              <button className="btn ghost sm" onClick={() => setEdit({ id: p.id, value: { ...p, config: { ...p.config } }, secretsSet: p.secrets_set })}>{t("admin.edit")}</button>
              <button className="btn ghost sm danger" onClick={() => confirm(t("admin.deleteConfirm", { name: p.name }))
                && run(() => api.deleteProvider(p.id)).then(load)}>{t("admin.delete")}</button>
            </>
          )}
        </div>
      ))}
      <div className="add-methods">
        <button className="btn" onClick={() => addNew("ldap")}>+ {t("setup.addLdap")}</button>
        <button className="btn" onClick={() => addNew("oidc")}>+ {t("setup.addOidc")}</button>
      </div>
      {edit && (
        <Modal title={t(`prov.type.${edit.value.type}`)} onClose={() => setEdit(null)} footer={
          <>
            <button className="btn" onClick={() => setEdit(null)}>{t("issue.cancel")}</button>
            <button className="btn primary" onClick={save}>{t("admin.save")}</button>
          </>
        }>
          <div className="modal-scroll">
            <ProviderForm value={edit.value} onChange={(value) => setEdit({ ...edit, value })} baseUrl={baseUrl}
                          secretsSet={edit.secretsSet} slugLocked={!!edit.id}
                          onTest={(v, username) => api.testProvider(edit.id ? { provider_id: edit.id, provider: v, username } : { provider: v, username })} />
          </div>
        </Modal>
      )}
    </section>
  );
}

// ---------- roles
function RoleEditor({ role, perms, onSave, onClose }: {
  role: Partial<Role> & { scope: "global" | "project" };
  perms: { key: string; scope: string }[];
  onSave: (r: { key: string; name: string; description: string; permissions: string[]; is_default: boolean }) => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const [key, setKey] = useState(role.key ?? "");
  const [name, setName] = useState(role.name ?? "");
  const [description, setDescription] = useState(role.description ?? "");
  const [chosen, setChosen] = useState<string[]>(role.permissions ?? []);
  const [isDefault, setIsDefault] = useState(!!role.is_default);
  const locked = role.key === "admin" && role.builtin;
  const groups = role.scope === "global" ? ["global", "project"] : ["project"];
  return (
    <Modal title={role.id ? roleName(t, role as Role) : t("roles.new")} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>{t("issue.cancel")}</button>
        <button className="btn primary" disabled={!key || !name.trim()}
                onClick={() => onSave({ key, name: name.trim(), description, permissions: chosen, is_default: isDefault })}>{t("admin.save")}</button>
      </>
    }>
      <div className="modal-scroll" style={{ display: "grid", gap: 12 }}>
        <div className="row2">
          <label className="field"><span>{t("project.name")}</span>
            <input className="input" value={name} disabled={role.builtin} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field"><span>{t("roles.key")}</span>
            <input className="input mono" value={key} disabled={!!role.id}
                   onChange={(e) => setKey(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))} />
          </label>
        </div>
        <label className="field"><span>{t("issue.description")}</span>
          <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {role.scope === "global" && (
          <label className="check"><input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />{t("roles.default")}</label>
        )}
        {locked && <div className="banner info">{t("roles.locked")}</div>}
        {groups.map((g) => (
          <fieldset className="perm-group" key={g} disabled={locked}>
            <legend>{g === "global" ? t("perm.group.global") : t("perm.group.project")}</legend>
            {perms.filter((p) => p.scope === g).map((p) => (
              <label className="check" key={p.key}>
                <input type="checkbox" checked={chosen.includes(p.key)}
                       onChange={(e) => setChosen((c) => (e.target.checked ? [...c, p.key] : c.filter((x) => x !== p.key)))} />
                {t(`perm.${p.key}` as TKey)} <span className="hint mono">{p.key}</span>
              </label>
            ))}
          </fieldset>
        ))}
      </div>
    </Modal>
  );
}

function Roles() {
  const { t } = useT();
  const { run, ui } = useRunner();
  const [roles, setRoles] = useState<Role[]>([]);
  const [perms, setPerms] = useState<{ key: string; scope: "global" | "project" }[]>([]);
  const [edit, setEdit] = useState<(Partial<Role> & { scope: "global" | "project" }) | null>(null);
  const load = useCallback(async () => {
    const [r, p] = await Promise.all([api.roles(), api.permissions()]);
    setRoles(r);
    setPerms(p);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save(v: { key: string; name: string; description: string; permissions: string[]; is_default: boolean }) {
    if (!edit) return;
    const ok = await run(() => (edit.id
      ? api.patchRole(edit.id, { name: edit.builtin ? undefined : v.name, description: v.description,
                                 permissions: edit.key === "admin" ? undefined : v.permissions,
                                 is_default: edit.scope === "global" ? v.is_default : undefined })
      : api.createRole({ ...v, scope: edit.scope })), t("project.saved"));
    if (ok) { setEdit(null); load(); }
  }

  return (
    <section>
      {ui}
      {(["global", "project"] as const).map((scope) => (
        <div key={scope} style={{ marginBottom: 24 }}>
          <h3>{scope === "global" ? t("roles.global") : t("roles.project")}
            <button className="btn ghost sm" onClick={() => setEdit({ scope, permissions: [] })}>+ {t("roles.new")}</button>
          </h3>
          {scope === "global" && <p className="hint">{t("roles.globalHint")}</p>}
          {roles.filter((r) => r.scope === scope).map((r) => (
            <div className="member-row" key={r.id}>
              <div className="name">
                <div>{roleName(t, r)} {r.builtin && <span className="tag">{t("roles.builtin")}</span>}
                  {r.is_default && <span className="tag">{t("roles.default")}</span>}</div>
                <div className="hint">{r.permissions.map((p) => t(`perm.${p}` as TKey)).join(" · ") || "—"}</div>
              </div>
              <button className="btn ghost sm" onClick={() => setEdit(r)}>{t("admin.edit")}</button>
              {!r.builtin && <button className="btn ghost sm danger" onClick={() => confirm(t("admin.deleteConfirm", { name: r.name }))
                && run(() => api.deleteRole(r.id)).then(load)}>{t("admin.delete")}</button>}
            </div>
          ))}
        </div>
      ))}
      {edit && <RoleEditor role={edit} perms={perms} onSave={save} onClose={() => setEdit(null)} />}
    </section>
  );
}

// ---------- group bindings (shared with project settings)
export function BindingsEditor({ rows, roles, providers, onAdd, onDelete }: {
  rows: Binding[];
  roles: Role[];
  providers: ProviderBrief[];
  onAdd: (b: BindingIn) => Promise<unknown>;
  onDelete: (id: string) => Promise<unknown>;
}) {
  const { t } = useT();
  const [group, setGroup] = useState("");
  const [role, setRole] = useState("");
  const [provider, setProvider] = useState("");
  const chosenRole = role || roles[0]?.key || "";
  return (
    <div>
      <p className="hint">{t("groups.sub")}</p>
      {rows.length === 0 && <div className="hint" style={{ padding: "8px 0" }}>{t("groups.empty")}</div>}
      {rows.map((b) => (
        <div className="member-row" key={b.id}>
          <div className="name"><div className="mono" style={{ overflowWrap: "anywhere" }}>{b.group}</div>
            <div className="hint">{b.provider ? b.provider.name : t("groups.anyProvider")}</div></div>
          <span>{roleName(t, b.role)}</span>
          <button className="btn ghost sm danger" onClick={() => onDelete(b.id)}>{t("project.remove")}</button>
        </div>
      ))}
      <form className="binding-form" onSubmit={(e) => {
        e.preventDefault();
        if (group.trim()) onAdd({ group: group.trim(), role: chosenRole, provider: provider || null }).then(() => setGroup(""));
      }}>
        <input className="input" placeholder={t("groups.group")} value={group} onChange={(e) => setGroup(e.target.value)} />
        <select className="select" aria-label={t("groups.provider")} value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="">{t("groups.anyProvider")}</option>
          {providers.filter((p) => p.type !== "local").map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
        </select>
        <select className="select" aria-label={t("groups.role")} value={chosenRole} onChange={(e) => setRole(e.target.value)}>
          {roles.map((r) => <option key={r.key} value={r.key}>{roleName(t, r)}</option>)}
        </select>
        <button className="btn" disabled={!group.trim() || !chosenRole}>{t("groups.add")}</button>
      </form>
    </div>
  );
}

export function useDirectoryProviders() {
  const [list, setList] = useState<ProviderBrief[]>([]);
  useEffect(() => {
    api.authConfig().then((c) => setList([...c.password_providers, ...c.sso])).catch(() => {});
  }, []);
  return list;
}

function Groups() {
  const { run, ui } = useRunner();
  const [rows, setRows] = useState<Binding[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const providers = useDirectoryProviders();
  const load = useCallback(async () => {
    const [b, r] = await Promise.all([api.bindings(), api.roles("global")]);
    setRows(b);
    setRoles(r.filter((x) => !x.is_default));
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <section>
      {ui}
      <BindingsEditor rows={rows} roles={roles} providers={providers}
                      onAdd={(b) => run(() => api.addBinding(b)).then(load)}
                      onDelete={(id) => run(() => api.deleteBinding(id)).then(load)} />
    </section>
  );
}

// ---------- users
function UserRow({ u, roles, me, reload }: { u: User; roles: Role[]; me: User; reload: () => void }) {
  const { t } = useT();
  const { run, ui } = useRunner();
  const [open, setOpen] = useState(false);
  const [mine, setMine] = useState<string[] | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  useEffect(() => {
    if (!open) return;
    api.userRoles(u.id).then((r) => setMine(r.map((x) => x.key)));
    api.userGroups(u.id).then(setGroups);
  }, [open, u.id]);
  return (
    <div className="user-row">
      <div className="member-row">
        <div className="name"><div>{u.display_name} {u.is_admin && <span className="tag">{t("users.admin")}</span>}
          {!u.is_active && <span className="tag">{t("admin.disabled")}</span>}</div>
          <div className="hint">{u.username} · {u.source}{u.email ? ` · ${u.email}` : ""}</div></div>
        <button className="btn ghost sm" onClick={() => setOpen(!open)}>{t("admin.edit")}</button>
      </div>
      {open && (
        <div className="user-edit">
          {ui}
          <label className="check"><input type="checkbox" checked={u.is_active} disabled={u.id === me.id}
            onChange={(e) => run(() => api.patchUser(u.id, { is_active: e.target.checked })).then(reload)} />{t("users.active")}</label>
          {me.is_admin && (
            <label className="check"><input type="checkbox" checked={u.is_admin} disabled={u.id === me.id}
              onChange={(e) => run(() => api.patchUser(u.id, { is_admin: e.target.checked })).then(reload)} />{t("users.admin")}</label>
          )}
          <div className="field"><span>{t("users.roles")}</span>
            {mine && roles.filter((r) => !r.is_default).map((r) => (
              <label className="check" key={r.key}><input type="checkbox" checked={mine.includes(r.key)} onChange={(e) => {
                const nextRoles = e.target.checked ? [...mine, r.key] : mine.filter((x) => x !== r.key);
                run(() => api.setUserRoles(u.id, nextRoles), t("project.saved")).then((ok) => ok && setMine(nextRoles));
              }} />{roleName(t, r)}</label>
            ))}
          </div>
          {groups.length > 0 && (
            <div className="field"><span>{t("users.groups")}</span>
              {groups.map((g) => <code key={g} className="copyable">{g}</code>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NewUser({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useT();
  const { run, ui } = useRunner();
  const [f, setF] = useState({ username: "", display_name: "", email: "", password: "" });
  return (
    <Modal title={t("users.new")} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>{t("issue.cancel")}</button>
        <button className="btn primary" disabled={f.username.length < 2 || !f.display_name || f.password.length < 10}
                onClick={() => run(() => api.createUser({ ...f, email: f.email || undefined })).then((ok) => ok && onCreated())}>{t("users.create")}</button>
      </>
    }>
      {ui}
      <div className="row2">
        <label className="field"><span>{t("login.username")}</span>
          <input className="input" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value.replace(/[^A-Za-z0-9._-]/g, "") })} /></label>
        <label className="field"><span>{t("setup.displayName")}</span>
          <input className="input" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></label>
      </div>
      <label className="field"><span>{t("setup.email")}</span>
        <input className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
      <label className="field"><span>{t("login.password")}</span>
        <input className="input" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <span className="hint">{t("setup.passwordHint")}</span></label>
    </Modal>
  );
}

function Users() {
  const { t } = useT();
  const { user } = useSession();
  const [rows, setRows] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [creating, setCreating] = useState(false);
  const load = useCallback(async () => {
    const [u, r] = await Promise.all([api.allUsers(), api.roles("global")]);
    setRows(u);
    setRoles(r);
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <section>
      <div style={{ marginBottom: 8 }}><button className="btn" onClick={() => setCreating(true)}>+ {t("users.new")}</button></div>
      {rows.map((u) => <UserRow key={u.id} u={u} roles={roles} me={user} reload={load} />)}
      {creating && <NewUser onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load(); }} />}
    </section>
  );
}

export default function Admin() {
  const { t } = useT();
  const { user } = useSession();
  const can = (p: string) => user.permissions.includes(p);
  const tabs = [
    { path: "auth", label: t("admin.tab.auth"), ok: can("auth.manage"), el: <Providers /> },
    { path: "users", label: t("admin.tab.users"), ok: can("users.manage"), el: <Users /> },
    { path: "roles", label: t("admin.tab.roles"), ok: can("roles.manage"), el: <Roles /> },
    { path: "groups", label: t("admin.tab.groups"), ok: can("roles.manage"), el: <Groups /> },
  ].filter((x) => x.ok);
  if (!tabs.length) return <Navigate to="/" replace />;
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");
  return (
    <>
      <div className="topbar">
        <h1>{t("nav.admin")}</h1>
        <nav className="tabs" aria-label={t("nav.admin")}>
          {tabs.map((x) => <NavLink key={x.path} to={`/admin/${x.path}`} className={tab}>{x.label}</NavLink>)}
        </nav>
      </div>
      <div className="content">
        <div className="page settings-grid">
          <Routes>
            {tabs.map((x) => <Route key={x.path} path={x.path} element={x.el} />)}
            <Route path="*" element={<Navigate to={tabs[0].path} replace />} />
          </Routes>
        </div>
      </div>
    </>
  );
}
