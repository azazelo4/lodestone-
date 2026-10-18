# Lodestone

A self-hosted issue tracker for small engineering and ops teams. You sign in with your Active Directory account, keep your work on a board, and query the same data from Power BI.

![Board](docs/screenshots/board.png)

## Features

- **Active Directory / LDAP sign-in** out of the box:
  - service-account search, then a user bind;
  - optional "allowed users" group and admin group, with nested AD groups supported;
  - LDAPS or StartTLS with a corporate CA.
- **Projects with issue keys** (`OPS-42`), private or public. Each project has admin, member and viewer roles.
- **Issues** with:
  - sub-issues and epics;
  - status, priority, assignees, labels, start and due dates, estimate;
  - Markdown descriptions and comments;
  - a full change history.
- **Kanban board** with drag and drop, a **sortable list**, and a **"My work"** view across projects.
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

To load a sample project, run `docker compose exec app /entrypoint.sh seed`.

## Configuration

Everything is set through environment variables with the `LODESTONE_` prefix.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | `postgresql+psycopg://user:pass@host:5432/lodestone` |
| `SECRET_KEY` | — | Signs session tokens. Use 32+ random characters. |
| `SESSION_HOURS` | `12` | |
| `COOKIE_SECURE` | `true` | Set `false` only for plain-http local runs. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | empty | Local admin, created or reset on start. Leave the password empty to disable. |
| `LOCAL_AUTH_ENABLED` | `true` | Allow local (non-directory) accounts. |
| `PROJECT_CREATE` | `all` | `admins` restricts project creation. |
| `LDAP_ENABLED` | `false` | |
| `LDAP_URL` | | `ldaps://dc01.corp.local:636` |
| `LDAP_START_TLS`, `LDAP_CA_FILE`, `LDAP_VERIFY_CERT` | | TLS options. |
| `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` | | Read-only service account. |
| `LDAP_USER_BASE` | | `OU=Users,DC=corp,DC=local` |
| `LDAP_USER_FILTER` | `(sAMAccountName={username})` | OpenLDAP: `(uid={username})` |
| `LDAP_ALLOWED_GROUP` | empty | Only members can sign in. |
| `LDAP_ADMIN_GROUP` | empty | Members become global admins. Checked at every login. |
| `LDAP_NESTED_GROUPS` | `false` | AD only: uses `LDAP_MATCHING_RULE_IN_CHAIN`. |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCK_MINUTES` | `5` / `5` | Brute-force lockout per username. |

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
- [ ] Sprint board and burndown
- [ ] GitLab / GitHub integration: link MRs and commits by issue key
- [ ] Notifications: e-mail, Teams, Telegram
- [ ] Personal API tokens and outgoing webhooks
- [ ] Saved filters, issue templates, CSV / Excel import

## License

MIT
