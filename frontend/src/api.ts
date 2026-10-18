export type Role = "admin" | "member" | "viewer";
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
export interface UserBrief { id: string; username: string; display_name: string }
export interface State { id: string; name: string; category: Category; position: number }
export interface Label { id: string; name: string; color: string }
export interface Sprint { id: string; name: string; goal: string; start_date: string | null; end_date: string | null; closed: boolean }
export interface Project {
  id: string; key: string; name: string; description: string; is_private: boolean; archived: boolean;
  lead: UserBrief | null; states: State[]; my_role: Role | null; open_issues: number;
}
export interface Member { user: UserBrief; role: Role }
export interface Issue {
  id: string; key: string; number: number; type: IssueType; title: string; priority: Priority; state: State;
  assignees: UserBrief[]; labels: Label[]; parent_key: string | null; sprint_id: string | null;
  start_date: string | null; due_date: string | null; estimate: number | null; position: number;
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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
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
}

export const api = {
  authConfig: () => request<{ ldap: boolean; local: boolean }>("GET", "/auth/config"),
  login: (username: string, password: string) => request<User>("POST", "/auth/login", { username, password }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/auth/me"),
  searchUsers: (q: string) => request<UserBrief[]>("GET", `/users${qs({ q })}`),

  projects: () => request<Project[]>("GET", "/projects"),
  project: (key: string) => request<Project>("GET", `/projects/${key}`),
  createProject: (b: { key: string; name: string; description?: string; is_private: boolean }) =>
    request<Project>("POST", "/projects", b),
  patchProject: (key: string, b: Partial<Pick<Project, "name" | "description" | "is_private">>) =>
    request<Project>("PATCH", `/projects/${key}`, b),
  members: (key: string) => request<Member[]>("GET", `/projects/${key}/members`),
  addMember: (key: string, user_id: string, role: Role) =>
    request<Member>("POST", `/projects/${key}/members`, { user_id, role }),
  setRole: (key: string, user_id: string, role: Role) =>
    request<Member>("PATCH", `/projects/${key}/members/${user_id}`, { role }),
  removeMember: (key: string, user_id: string) => request<void>("DELETE", `/projects/${key}/members/${user_id}`),
  addState: (key: string, name: string, category: Category) =>
    request<State>("POST", `/projects/${key}/states`, { name, category }),
  patchState: (key: string, id: string, b: Partial<Pick<State, "name" | "category" | "position">>) =>
    request<State>("PATCH", `/projects/${key}/states/${id}`, b),
  deleteState: (key: string, id: string, moveTo?: string) =>
    request<void>("DELETE", `/projects/${key}/states/${id}${qs({ move_to: moveTo })}`),
  labels: (key: string) => request<Label[]>("GET", `/projects/${key}/labels`),
  addLabel: (key: string, name: string, color: string) =>
    request<Label>("POST", `/projects/${key}/labels`, { name, color }),

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
