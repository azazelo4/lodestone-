# Lodestone

A self-hosted issue tracker for small engineering and ops teams. You sign in with your Active Directory account, keep your work on a board, and query the same data from Power BI.

![Board](docs/screenshots/board.png)

## Features

- **Active Directory / LDAP sign-in** out of the box:
  - service-account search, then a user bind;
  - optional "allowed users" group and admin group, with nested AD groups supported;
  - LDAPS or StartTLS with a corporate CA.
- **Single sign-on (OpenID Connect)** with Keycloak, Entra ID (Azure AD), ADFS, Google, GitLab or Okta: authorization code flow with PKCE, IdP groups for access and admin rights.
- **Several sign-in methods at once**: local accounts, one or more LDAP/AD directories and SSO providers. A first-start wizard lets you pick them; later they are managed in Administration.
- **Role-based access control**: roles are sets of permissions, builtin admin / member / viewer plus your own, global or per project, given to people or to directory groups.
- **Notifications**: e-mails over SMTP to the people involved in an issue (assigned, @mentioned, commented, status changed), and posts to Slack, Mattermost, Rocket.Chat, Microsoft Teams, Discord, Telegram or any JSON webhook, for all projects or per project. Delivery goes through an outbox with retries, so a slow mail server never slows the UI.
- **Projects with issue keys** (`OPS-42`), private or public.
- **Issues** with:
  - sub-issues and epics;
  - status, priority, assignees, labels, start and due dates, estimate;
  - Markdown descriptions and comments;
  - a full change history.
- **Kanban board** with drag and drop, a **sortable list**, and a **"My work"** view across projects.
- **Cycles**: time boxes of one or two weeks with a burndown, by issue count or by estimate. Open cycles cannot overlap; completing a cycle moves its unfinished issues to the next one.
- **Modules**: a feature or part of the system with a status, a lead and a target date. They group issues across cycles, and an issue can be in several.
- **Progress analytics** per project: cumulative flow by status, created vs completed per week, lead and cycle time (median and 85th percentile), workload per person, open issues by priority. Every chart has a table view.
- **Documentation** per project: Markdown pages in a tree, with preview, search by title and links between pages.
- **Import from Jira, Plane and Confluence**: projects with issues, statuses, sprints, components or modules, epics, sub-tasks and comments; Confluence spaces become project documentation. Running an import again updates what it brought in before.
- **Custom statuses** per project. Each status maps to a fixed category (backlog, todo, in progress, done, cancelled), so metrics keep working whatever names a team picks.
- **Analytics-ready schema.** The `analytics.*` views give lead time, cycle time, age, overdue flags and state transitions to Power BI, Metabase or Grafana. No ETL needed.
- **REST API** with OpenAPI docs at `/api/docs`. It accepts the session cookie or a `Bearer` token.
- **English and Russian UI**, light and dark themes.
- **One container.** It runs on PostgreSQL 14+ and ships with a Helm chart and docker-compose.

| | |
|---|---|
| ![Issue](docs/screenshots/issue.png) | ![List](docs/screenshots/list.png) |

## Quick start (docker compose)

```bash
docker compose up --build
```

Open http://localhost:8000. The compose file starts PostgreSQL and an OpenLDAP server with demo accounts:

| Login | Password | Role |
|---|---|---|
| `alice` | `alice-password` | admin (member of `lodestone-admins`) |
| `bob` | `bob-password` | user |
| `mallory` | `mallory-password` | rejected: not in `lodestone-users` |
| `admin` | `admin-password-1` | local break-glass admin |

To load a sample project, run `docker compose exec app /entrypoint.sh seed`. Notification e-mails for alice and bob are caught by Mailpit at http://localhost:8025.

## Configuration

Everything is set through environment variables with the `LODESTONE_` prefix.

### Sign-in and first start

On an empty install without `ADMIN_PASSWORD`, LDAP or OIDC variables the web UI opens a setup wizard. It asks for the setup token from the log, creates the first administrator and lets you choose one or several sign-in methods: local accounts (for everyone or administrators only), any number of LDAP/AD directories and SSO providers, each with a "Test connection" button.

If those variables are set (Helm, compose, CI), the wizard is skipped and the variables become the initial providers. Afterwards providers are edited in **Administration → Sign-in**; set `AUTH_SYNC_ENV=true` if env should stay the source of truth. Bind passwords and client secrets are stored encrypted and never returned by the API.

### Roles and permissions

A role is a named set of permissions. Global permissions: `users.manage`, `roles.manage`, `auth.manage`, `projects.create`. Project permissions: `project.read`, `project.manage`, `members.manage`, `issues.create`, `issues.edit`, `issues.delete`, `comments.create`, `comments.moderate`, `labels.manage`, `sprints.manage`.

- Builtin project roles `admin`, `member`, `viewer`, and the global `user` role every account has. Add your own in **Administration → Roles**.
- A project permission inside a global role applies to every project, e.g. an "Auditor" role with `project.read`.
- Roles can be given to a directory group: an LDAP group DN or an IdP group name, globally (**Administration → Groups**) or in one project (**Project settings → Directory groups**). Groups are refreshed at every sign-in.
- Nobody can give a role with permissions they do not have themselves. Administrators (`is_admin`, the LDAP/IdP admin group) have every permission.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | `postgresql+psycopg://user:pass@host:5432/lodestone` |
| `SECRET_KEY` | — | Signs session tokens. Use 32+ random characters. |
| `SESSION_HOURS` | `12` | |
| `COOKIE_SECURE` | `true` | Set `false` only for plain-http local runs. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | empty | Local admin, created or reset on start. Leave the password empty to disable. |
| `SETUP_TOKEN` | random | Token for the first-start wizard. If empty, a random one is printed to the log. |
| `AUTH_SYNC_ENV` | `false` | `true` re-applies the providers below from env on every start (GitOps). |
| `ENCRYPTION_KEY` | derived from `SECRET_KEY` | Encrypts provider secrets stored in the DB. |
| `LOCAL_AUTH_ENABLED` | `true` | Allow local (non-directory) accounts. |
| `LOCAL_ADMINS_ONLY` | `false` | Local accounts only for administrators (break-glass). |
| `PROJECT_CREATE` | `all` | `admins`: the default "user" role starts without the `projects.create` permission. |
| `LDAP_ENABLED` | `false` | |
| `LDAP_URL` | | `ldaps://dc01.corp.local:636` |
| `LDAP_START_TLS`, `LDAP_CA_FILE`, `LDAP_VERIFY_CERT` | | TLS options. |
| `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` | | Read-only service account. |
| `LDAP_USER_BASE` | | `OU=Users,DC=corp,DC=local` |
| `LDAP_USER_FILTER` | `(sAMAccountName={username})` | OpenLDAP: `(uid={username})` |
| `LDAP_ALLOWED_GROUP` | empty | Only members can sign in. |
| `LDAP_ADMIN_GROUP` | empty | Members become global admins. Checked at every login. |
| `LDAP_NESTED_GROUPS` | `false` | AD only: uses `LDAP_MATCHING_RULE_IN_CHAIN`. |
| `OIDC_ENABLED`, `OIDC_NAME` | `false`, `SSO` | SSO provider; `NAME` is the button text. |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | | Redirect URI to register: `<BASE_URL>/api/auth/oidc/sso/callback`. |
| `OIDC_SCOPES`, `OIDC_GROUPS_CLAIM` | `openid profile email`, `groups` | Dotted paths work: `realm_access.roles`. |
| `OIDC_ALLOWED_GROUPS`, `OIDC_ADMIN_GROUPS` | empty | Comma-separated group names. |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCK_MINUTES` | `5` / `5` | Brute-force lockout per username. |
| `SMTP_HOST`, `SMTP_PORT` | empty, `587` | Initial mail server; later edited in Administration → Notifications. |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (port 465) or `none`. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | empty | Leave empty for a relay without authentication. |
| `SMTP_FROM` | empty | `Lodestone <tracker@corp.local>` |
| `NOTIFY_LANG` | `en` | Language of notifications when the person or channel has not chosen one. |
| `NOTIFY_WORKER` | `true` | Send notifications from the web process. Set `false` if you run `worker` separately. |
| `WEBHOOK_ALLOW_PRIVATE` | `false` | Allow webhooks to private addresses (an internal Mattermost, a Telegram proxy). |
| `WEBHOOK_TIMEOUT` | `10` | Seconds. |

### Notifications

**Administration → Notifications** holds the mail server (with a "Send test e-mail" button), messengers for all projects and a delivery log where failed messages can be retried. Project managers add their own messengers in the project settings. Everyone chooses what e-mails they get under **Notifications** in the sidebar.

E-mail goes to the reporter, the assignees, earlier commenters and anyone mentioned as `@login`, never to the person who made the change, and only while they can still see the project. Messenger channels get every event they subscribe to. The webhook URL for each messenger:

| Messenger | Where to get it |
|---|---|
| Slack | App → Incoming Webhooks |
| Mattermost, Rocket.Chat | Integrations → Incoming webhook |
| Microsoft Teams | Channel → Workflows → "Post to a channel when a webhook request is received" |
| Discord | Channel settings → Integrations → Webhooks |
| Telegram | A bot token from @BotFather and the chat id; add the bot to the group |
| Other | Any URL that accepts JSON `{event, text, url, data}`; with a signing secret the body is signed in `X-Lodestone-Signature: sha256=<HMAC>` |

Messages are written to the `notification_outbox` table in the same transaction as the change and sent in the background with retries after 1, 5, 30, 120 and 360 minutes. Several replicas can send at once. To run sending as its own Deployment, set `NOTIFY_WORKER=false` on the web pods and start the image with the `worker` command. Webhooks to private IP addresses are blocked unless `WEBHOOK_ALLOW_PRIVATE=true`, so a project manager cannot use them to probe the internal network.

### Import from Jira, Plane and Confluence

**Administration → Import** (permission `imports.run`, administrators only by default). Pick the source, enter its address and credentials, load the list of projects or spaces, and choose a new or an existing Lodestone project. The import runs in the background; the list below the form shows progress, what was created and the log.

| Source | Address | Credentials | What comes over |
|---|---|---|---|
| Jira Cloud | `https://acme.atlassian.net` | e-mail + API token | issues, statuses, priorities, labels, assignees, sprints → cycles, components → modules, epics and sub-tasks → parents, story points → estimate, comments |
| Jira Server / Data Center | `https://jira.corp.local` | login + password, or only a personal access token | the same; descriptions in wiki markup are converted to Markdown |
| Plane | `https://plane.corp.local` + workspace slug | API key | states, labels, work items, cycles, modules, parents, comments |
| Confluence Cloud | `https://acme.atlassian.net/wiki` | e-mail + API token | the page tree of a space with text, tables, code blocks and links between pages |
| Confluence Server / Data Center | `https://wiki.corp.local` | login + password, or a personal access token | the same |

- People are matched by e-mail, then by login, and become members of the project. Issues and comments of people who have no Lodestone account are kept, with their name in the text.
- Every issue and page gets a link back to the original. Running the same import again updates titles, descriptions, statuses and comments instead of creating copies (the `import_links` table remembers what became what).
- Not imported: attachments and images (a placeholder with the file name stays), worklogs, change history, Plane pages (they are not in Plane's public API).
- Credentials are stored encrypted only while the import runs and are deleted when it ends. Imports reach any address the server can, internal ones included, which is why the permission is for administrators.

### Active Directory example

```env
LODESTONE_LDAP_ENABLED=true
LODESTONE_LDAP_URL=ldaps://dc01.corp.local:636
LODESTONE_LDAP_CA_FILE=/etc/lodestone/ca/ca.crt
LODESTONE_LDAP_BIND_DN=CN=svc-lodestone,OU=Service Accounts,DC=corp,DC=local
LODESTONE_LDAP_USER_BASE=OU=Users,DC=corp,DC=local
LODESTONE_LDAP_USER_FILTER=(sAMAccountName={username})
LODESTONE_LDAP_ALLOWED_GROUP=CN=Lodestone Users,OU=Groups,DC=corp,DC=local
LODESTONE_LDAP_ADMIN_GROUP=CN=Lodestone Admins,OU=Groups,DC=corp,DC=local
LODESTONE_LDAP_NESTED_GROUPS=true
```

The service account only needs read access to users and groups. User passwords go straight to the domain controller in a bind and are never stored. If users sign in with `user@corp.local`, use the filter `(|(sAMAccountName={username})(userPrincipalName={username}))`.

## Kubernetes (Helm)

Step-by-step guide: [docs/deploy-kubernetes.md](docs/deploy-kubernetes.md) (на русском: [docs/deploy-kubernetes.ru.md](docs/deploy-kubernetes.ru.md)). An example production values file is in [deploy/examples/values-prod.yaml](deploy/examples/values-prod.yaml). In short:

```bash
helm install lodestone deploy/helm/lodestone \
  --set image.repository=ghcr.io/<you>/lodestone \
  --set ingress.host=lodestone.corp.local \
  --set existingSecret=lodestone \
  --set auth.ldap.enabled=true \
  --set auth.ldap.caSecret=corp-ca
```

The `existingSecret` Secret holds these keys:
- `secret-key`
- `database-url`
- `ldap-bind-password`
- `admin-password` (optional)
- `oidc-client-secret`, `encryption-key`, `setup-token`, `smtp-password` (optional)

Migrations run in an init container. They are serialized with a PostgreSQL advisory lock, so several replicas can roll out at once.

## Analytics

Give a read-only role access to the `analytics` schema, then point Power BI (PostgreSQL connector) at these views:

```sql
CREATE ROLE bi_ro LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA analytics TO bi_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO bi_ro;
```

| View | What's in it |
|---|---|
| `analytics.issues` | One row per issue: project, state, category, assignees, dates, `lead_time_days`, `cycle_time_days`, `age_days`, `is_overdue` |
| `analytics.issue_assignees` | Issue ↔ user, with `share` so per-person counts don't double-count shared issues |
| `analytics.state_transitions` | Every status change, with `days_in_from_state` |
| `analytics.cycles` | One row per cycle (the `sprint` column in `analytics.issues`): dates, issue counts by category, estimate totals |
| `analytics.modules` | One row per module: status, lead, dates, issue counts and estimates |
| `analytics.issue_modules` | Issue ↔ module |

## Development

```bash
# backend (needs PostgreSQL)
cd backend
pip install -r requirements-dev.txt
export LODESTONE_DATABASE_URL=postgresql+psycopg://postgres@localhost/lodestone
export LODESTONE_SECRET_KEY=dev-secret-key LODESTONE_COOKIE_SECURE=false
export LODESTONE_ADMIN_USERNAME=admin LODESTONE_ADMIN_PASSWORD=admin-password-1
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev

# tests: real PostgreSQL + an in-memory LDAP directory
cd backend && LODESTONE_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost/lodestone_test pytest
```

The stack is FastAPI, SQLAlchemy 2, Alembic and ldap3 on the backend, and React 18 with TypeScript and Vite on the frontend. There is no UI framework, and the font is bundled, so it works in air-gapped networks.

## Roadmap

- [ ] Attachments (S3 / MinIO)
- [x] Cycles with burndown, modules, progress analytics
- [ ] GitLab / GitHub integration: link MRs and commits by issue key
- [x] Notifications: e-mail and messenger webhooks
- [ ] Personal API tokens and outgoing webhooks
- [x] Project documentation, import from Jira, Plane and Confluence
- [ ] Saved filters, issue templates, CSV / Excel import

## License

MIT
