export type Category = "backlog" | "todo" | "in_progress" | "done" | "cancelled";
export type Priority = "none" | "low" | "medium" | "high" | "urgent";
export type IssueType = "task" | "bug" | "story" | "epic";

export interface User {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  source: string;
}
export interface Me extends User { permissions: string[] }
export interface UserBrief { id: string; username: string; display_name: string }
export interface State { id: string; name: string; category: Category; position: number }
export interface Label { id: string; name: string; color: string }
export interface Progress {
  total: number; scope: number; done: number; percent: number; by_category: Record<Category, number>;
  points_scope: number; points_done: number; points_percent: number;
}
export type CycleStatus = "draft" | "upcoming" | "active" | "ended" | "completed";
export interface Sprint {
  id: string; name: string; goal: string; start_date: string | null; end_date: string | null; closed: boolean;
  closed_at: string | null; status: CycleStatus; progress: Progress;
}
export type ModuleStatus = "backlog" | "planned" | "in_progress" | "paused" | "completed" | "cancelled";
export interface Module {
  id: string; name: string; description: string; status: ModuleStatus; lead: UserBrief | null;
  start_date: string | null; target_date: string | null; created_at: string; progress: Progress;
}
export interface ModuleIn {
  name: string; description: string; status: ModuleStatus; lead_id: string | null; start_date: string | null; target_date: string | null;
}
export interface BurnPoint { date: string; scope: number | null; done: number | null; points_scope: number | null; points_done: number | null }
export interface ProgressDetail {
  progress: Progress; start: string; end: string; burndown: BurnPoint[];
  people: { user_id: string; name: string; total: number; done: number }[];
}
export interface TimeStats { count: number; median: number | null; p85: number | null }
export interface ProjectAnalytics {
  since: string;
  totals: Progress & { overdue: number; unassigned: number };
  weekly: { week: string; created: number; completed: number }[];
  lead_time: TimeStats; cycle_time: TimeStats;
  people: { user_id: string; name: string; todo: number; in_progress: number; done: number }[];
  priority: Record<Priority, number>;
  flow: ({ date: string } & Record<Category, number>)[];
}
export interface PageBrief { id: string; parent_id: string | null; title: string; position: number; updated_at: string }
export interface Page extends PageBrief { body: string; created_at: string; updated_by: UserBrief | null }
export type ImportKind = "jira" | "plane" | "confluence";
export interface ImportSource { source: ImportKind; url: string; workspace: string; username: string; token: string }
export interface ImportIn extends ImportSource { remote: string; target_key: string; target_name: string; include_comments: boolean }
export interface RemoteProject { id: string; key: string; name: string }
export interface ImportJob {
  id: string; source: ImportKind; status: "queued" | "running" | "done" | "failed";
  params: { url: string; workspace?: string; remote: string; include_comments?: boolean };
  stats: Record<string, number> & { unmatched_users?: string[] }; log: string; error: string | null;
  project_key: string | null; created_by: UserBrief | null; created_at: string; started_at: string | null; finished_at: string | null;
}
export interface Project {
  id: string; key: string; name: string; description: string; is_private: boolean; archived: boolean;
  lead: UserBrief | null; states: State[]; my_role: string | null; my_permissions: string[]; open_issues: number;
}
export interface RoleBrief { id: string; key: string; name: string }
export interface Role extends RoleBrief {
  description: string; scope: "global" | "project"; permissions: string[]; builtin: boolean; is_default: boolean;
}
export interface Member { user: UserBrief; role: RoleBrief }
export type ProviderType = "local" | "ldap" | "oidc";
export interface ProviderBrief { slug: string; type: ProviderType; name: string }
export interface AuthConfig {
  setup_required: boolean; password: boolean; password_providers: ProviderBrief[]; sso: ProviderBrief[];
}
export type ProviderConfig = Record<string, string | boolean | number | string[]>;
export interface ProviderIn { slug: string; type: ProviderType; name: string; enabled: boolean; position?: number; config: ProviderConfig }
export interface Provider extends ProviderIn { id: string; position: number; secrets_set: string[]; redirect_uri: string | null }
export interface TestResult { ok: boolean; message: string }
export interface Binding { id: string; group: string; role: RoleBrief; provider: ProviderBrief | null; project_key: string | null }
export type ChannelType = "slack" | "mattermost" | "rocketchat" | "teams" | "discord" | "telegram" | "generic";
export interface ChannelIn {
  name: string; type: ChannelType; enabled: boolean; events: string[]; lang: "en" | "ru";
  config: Record<string, string>; secrets: Record<string, string>;
}
export interface Channel extends Omit<ChannelIn, "secrets"> { id: string; secrets_set: string[]; project_key: string | null }
export interface Smtp { enabled: boolean; host: string; port: number; security: "none" | "starttls" | "ssl"; username: string; from_address: string; password_set: boolean }
export interface NotifyPrefs { email_enabled: boolean; events: string[]; lang: "en" | "ru" | null }
export interface OutboxRow {
  id: number; kind: "email" | "webhook"; recipient: string; subject: string; status: "pending" | "sent" | "failed";
  attempts: number; last_error: string | null; created_at: string; sent_at: string | null; next_attempt_at: string;
}
export interface BindingIn { group: string; role: string; provider?: string | null }
export interface Issue {
  id: string; key: string; number: number; type: IssueType; title: string; priority: Priority; state: State;
  assignees: UserBrief[]; labels: Label[]; parent_key: string | null; sprint_id: string | null;
  module_ids: string[]; start_date: string | null; due_date: string | null; estimate: number | null; position: number;
  created_at: string; updated_at: string; completed_at: string | null;
  subtasks_total: number; subtasks_done: number;
}
export interface IssueDetail extends Issue {
  description: string; reporter: UserBrief | null; project_key: string; started_at: string | null; subtasks: Issue[];
}
export interface Comment { id: string; body: string; author: UserBrief | null; created_at: string; edited_at: string | null }
export interface Activity {
  id: number; field: string; old_value: string | null; new_value: string | null; actor: UserBrief | null; created_at: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function detail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? "").filter(Boolean).join("; ");
  }
  return `Request failed (${status})`;
}

async function request<T>(method: string, path: string, body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...extraHeaders },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && path !== "/auth/login") onUnauthorized();
    throw new ApiError(res.status, detail(data, res.status));
  }
  return data as T;
}

function qs(params: Record<string, string | string[] | boolean | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || v === false) continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x));
    else u.append(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export interface IssueFilter {
  q?: string; assignee?: string[]; priority?: string[]; open_only?: boolean; label_id?: string[]; type?: string[];
  sprint_id?: string; module_id?: string;
}

export const api = {
  authConfig: () => request<AuthConfig>("GET", "/auth/config"),
  login: (username: string, password: string, provider?: string) =>
    request<Me>("POST", "/auth/login", { username, password, provider: provider || null }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<Me>("GET", "/auth/me"),
  searchUsers: (q: string) => request<UserBrief[]>("GET", `/users${qs({ q })}`),

  setupStatus: () => request<{ required: boolean; base_url: string }>("GET", "/setup"),
  setupVerify: (token: string) => request<void>("POST", "/setup/verify", { token }),
  setupTest: (token: string, provider: ProviderIn, username = "") =>
    request<TestResult>("POST", "/setup/test", { provider, username }, { "X-Setup-Token": token }),
  setupComplete: (b: { token: string; admin: Record<string, string>; local_mode: "all" | "admins"; providers: ProviderIn[] }) =>
    request<Me>("POST", "/setup", b),

  providers: () => request<Provider[]>("GET", "/admin/auth-providers"),
  createProvider: (b: ProviderIn) => request<Provider>("POST", "/admin/auth-providers", b),
  patchProvider: (id: string, b: { name?: string; enabled?: boolean; position?: number; config?: ProviderConfig; secrets?: Record<string, string> }) =>
    request<Provider>("PATCH", `/admin/auth-providers/${id}`, b),
  deleteProvider: (id: string) => request<void>("DELETE", `/admin/auth-providers/${id}`),
  testProvider: (b: { provider?: ProviderIn; provider_id?: string; username?: string }) =>
    request<TestResult>("POST", "/admin/auth-providers/test", b),

  permissions: () => request<{ key: string; scope: "global" | "project" }[]>("GET", "/permissions"),
  roles: (scope?: "global" | "project") => request<Role[]>("GET", `/roles${qs({ scope })}`),
  createRole: (b: { key: string; name: string; description?: string; scope: string; permissions: string[] }) =>
    request<Role>("POST", "/roles", b),
  patchRole: (id: string, b: { name?: string; description?: string; permissions?: string[]; is_default?: boolean }) =>
    request<Role>("PATCH", `/roles/${id}`, b),
  deleteRole: (id: string) => request<void>("DELETE", `/roles/${id}`),
  bindings: () => request<Binding[]>("GET", "/admin/group-bindings"),
  addBinding: (b: BindingIn) => request<Binding>("POST", "/admin/group-bindings", b),
  deleteBinding: (id: string) => request<void>("DELETE", `/admin/group-bindings/${id}`),

  myNotifications: () => request<NotifyPrefs>("GET", "/me/notifications"),
  setMyNotifications: (b: NotifyPrefs) => request<NotifyPrefs>("PUT", "/me/notifications", b),
  smtp: () => request<Smtp>("GET", "/admin/notifications/smtp"),
  setSmtp: (b: Omit<Smtp, "password_set"> & { password?: string | null }) => request<Smtp>("PUT", "/admin/notifications/smtp", b),
  testSmtp: (to: string) => request<TestResult>("POST", "/admin/notifications/smtp/test", { to }),
  outbox: (status?: string) => request<OutboxRow[]>("GET", `/admin/notifications/outbox${qs({ status, limit: "50" })}`),
  retryOutbox: (id: number) => request<OutboxRow>("POST", `/admin/notifications/outbox/${id}/retry`),
  channels: (projectKey?: string) =>
    request<Channel[]>("GET", projectKey ? `/projects/${projectKey}/notification-channels` : "/admin/notification-channels"),
  addChannel: (projectKey: string | undefined, b: ChannelIn) =>
    request<Channel>("POST", projectKey ? `/projects/${projectKey}/notification-channels` : "/admin/notification-channels", b),
  updateChannel: (projectKey: string | undefined, id: string, b: ChannelIn) =>
    request<Channel>("PUT", `${projectKey ? `/projects/${projectKey}` : "/admin"}/notification-channels/${id}`, b),
  deleteChannel: (projectKey: string | undefined, id: string) =>
    request<void>("DELETE", `${projectKey ? `/projects/${projectKey}` : "/admin"}/notification-channels/${id}`),
  testChannel: (projectKey: string | undefined, id: string) =>
    request<TestResult>("POST", `${projectKey ? `/projects/${projectKey}` : "/admin"}/notification-channels/${id}/test`),

  allUsers: () => request<User[]>("GET", "/users/all"),
  createUser: (b: { username: string; display_name: string; email?: string; password: string; is_admin?: boolean }) =>
    request<User>("POST", "/users", b),
  patchUser: (id: string, b: { is_admin?: boolean; is_active?: boolean }) => request<User>("PATCH", `/users/${id}`, b),
  userRoles: (id: string) => request<RoleBrief[]>("GET", `/users/${id}/roles`),
  setUserRoles: (id: string, roles: string[]) => request<RoleBrief[]>("PUT", `/users/${id}/roles`, { roles }),
  userGroups: (id: string) => request<string[]>("GET", `/users/${id}/groups`),

  projects: () => request<Project[]>("GET", "/projects"),
  project: (key: string) => request<Project>("GET", `/projects/${key}`),
  createProject: (b: { key: string; name: string; description?: string; is_private: boolean }) =>
    request<Project>("POST", "/projects", b),
  patchProject: (key: string, b: Partial<Pick<Project, "name" | "description" | "is_private">>) =>
    request<Project>("PATCH", `/projects/${key}`, b),
  members: (key: string) => request<Member[]>("GET", `/projects/${key}/members`),
  addMember: (key: string, user_id: string, role: string) =>
    request<Member>("POST", `/projects/${key}/members`, { user_id, role }),
  setRole: (key: string, user_id: string, role: string) =>
    request<Member>("PATCH", `/projects/${key}/members/${user_id}`, { role }),
  removeMember: (key: string, user_id: string) => request<void>("DELETE", `/projects/${key}/members/${user_id}`),
  projectBindings: (key: string) => request<Binding[]>("GET", `/projects/${key}/group-bindings`),
  addProjectBinding: (key: string, b: BindingIn) => request<Binding>("POST", `/projects/${key}/group-bindings`, b),
  deleteProjectBinding: (key: string, id: string) => request<void>("DELETE", `/projects/${key}/group-bindings/${id}`),
  addState: (key: string, name: string, category: Category) =>
    request<State>("POST", `/projects/${key}/states`, { name, category }),
  patchState: (key: string, id: string, b: Partial<Pick<State, "name" | "category" | "position">>) =>
    request<State>("PATCH", `/projects/${key}/states/${id}`, b),
  deleteState: (key: string, id: string, moveTo?: string) =>
    request<void>("DELETE", `/projects/${key}/states/${id}${qs({ move_to: moveTo })}`),
  labels: (key: string) => request<Label[]>("GET", `/projects/${key}/labels`),
  addLabel: (key: string, name: string, color: string) =>
    request<Label>("POST", `/projects/${key}/labels`, { name, color }),

  cycles: (key: string) => request<Sprint[]>("GET", `/projects/${key}/sprints`),
  addCycle: (key: string, b: { name: string; goal: string; start_date: string | null; end_date: string | null }) =>
    request<Sprint>("POST", `/projects/${key}/sprints`, b),
  patchCycle: (key: string, id: string, b: Partial<Pick<Sprint, "name" | "goal" | "start_date" | "end_date" | "closed">>) =>
    request<Sprint>("PATCH", `/projects/${key}/sprints/${id}`, b),
  deleteCycle: (key: string, id: string) => request<void>("DELETE", `/projects/${key}/sprints/${id}`),
  completeCycle: (key: string, id: string, moveTo: string | null) =>
    request<Sprint>("POST", `/projects/${key}/sprints/${id}/complete`, { move_to: moveTo }),
  cycleProgress: (key: string, id: string) => request<ProgressDetail>("GET", `/projects/${key}/sprints/${id}/progress`),
  modules: (key: string) => request<Module[]>("GET", `/projects/${key}/modules`),
  addModule: (key: string, b: ModuleIn) => request<Module>("POST", `/projects/${key}/modules`, b),
  patchModule: (key: string, id: string, b: Partial<ModuleIn>) => request<Module>("PATCH", `/projects/${key}/modules/${id}`, b),
  deleteModule: (key: string, id: string) => request<void>("DELETE", `/projects/${key}/modules/${id}`),
  moduleProgress: (key: string, id: string) => request<ProgressDetail>("GET", `/projects/${key}/modules/${id}/progress`),
  pages: (key: string) => request<PageBrief[]>("GET", `/projects/${key}/pages`),
  page: (key: string, id: string) => request<Page>("GET", `/projects/${key}/pages/${id}`),
  addPage: (key: string, b: { title: string; body: string; parent_id: string | null }) => request<Page>("POST", `/projects/${key}/pages`, b),
  patchPage: (key: string, id: string, b: Partial<{ title: string; body: string; parent_id: string | null; position: number }>) =>
    request<Page>("PATCH", `/projects/${key}/pages/${id}`, b),
  deletePage: (key: string, id: string) => request<void>("DELETE", `/projects/${key}/pages/${id}`),
  importRemote: (b: ImportSource) => request<RemoteProject[]>("POST", "/imports/remote", b),
  startImport: (b: ImportIn) => request<ImportJob>("POST", "/imports", b),
  imports: () => request<ImportJob[]>("GET", "/imports"),
  analytics: (key: string, weeks: number) => request<ProjectAnalytics>("GET", `/projects/${key}/analytics?weeks=${weeks}`),

  issues: (key: string, f: IssueFilter = {}) =>
    request<Issue[]>("GET", `/projects/${key}/issues${qs(f as Record<string, string | string[] | boolean>)}`),
  myIssues: () => request<Issue[]>("GET", "/my/issues"),
  issue: (key: string) => request<IssueDetail>("GET", `/issues/${key}`),
  createIssue: (projectKey: string, b: Record<string, unknown>) =>
    request<IssueDetail>("POST", `/projects/${projectKey}/issues`, b),
  patchIssue: (key: string, b: Record<string, unknown>) => request<IssueDetail>("PATCH", `/issues/${key}`, b),
  deleteIssue: (key: string) => request<void>("DELETE", `/issues/${key}`),
  comments: (key: string) => request<Comment[]>("GET", `/issues/${key}/comments`),
  addComment: (key: string, body: string) => request<Comment>("POST", `/issues/${key}/comments`, { body }),
  editComment: (id: string, body: string) => request<Comment>("PATCH", `/comments/${id}`, { body }),
  deleteComment: (id: string) => request<void>("DELETE", `/comments/${id}`),
  activity: (key: string) => request<Activity[]>("GET", `/issues/${key}/activity`),
};
