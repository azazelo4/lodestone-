# Deploying Lodestone to Kubernetes

A step-by-step plan from an empty repository to a running tracker with Active Directory sign-in. На русском: [deploy-kubernetes.ru.md](deploy-kubernetes.ru.md).

## What you get

```
              Ingress (TLS)
                   │
            Service :80 → :8000
                   │
   Deployment lodestone (2 pods)            Deployment lodestone-worker (optional)
   ├─ init: migrate (alembic upgrade head)  └─ sends e-mail and messenger notifications
   └─ app: uvicorn, API + web UI
                   │
          PostgreSQL 14+ (outside the chart)
                   │
   AD/LDAP · SSO (OIDC) · SMTP · Jira/Plane/Confluence for imports
```

The chart in `deploy/helm/lodestone` installs a Deployment, a Service, an Ingress, a ConfigMap and, unless `existingSecret` is set, a Secret. It does not install the database: use a managed PostgreSQL, an existing cluster or an operator (CloudNativePG, Zalando).

## Before you start

| What | Why |
|---|---|
| Kubernetes 1.25+, `kubectl` with rights in one namespace | The cluster |
| Helm 3.12+ | Installing the chart |
| An ingress controller (ingress-nginx or another) | Access from outside |
| cert-manager or a TLS certificate | HTTPS: the session cookie is only sent over HTTPS |
| PostgreSQL 14+ | Data |
| An image registry: GHCR, Harbor, Nexus | The application image |
| An AD service account and the corporate root CA (for LDAPS) | Directory sign-in |
| A DNS name, e.g. `tracker.corp.local` | The address |

## Step 1. Push the code

`lodestone-repo.zip` is a git repository with the full history; `lodestone.bundle` is the same history as one file.

```bash
unzip lodestone-repo.zip && cd lodestone
git log --oneline                      # branch main, tag v0.1.0
git remote add origin git@github.com:<you>/lodestone.git
git push -u origin main
git push origin v0.1.0
```

On GitHub, CI (`.github/workflows/ci.yml`) runs the backend tests on PostgreSQL, the frontend type check and build, and `helm lint`, then builds the image:
- a push to `main` publishes `ghcr.io/<you>/lodestone:latest` and `sha-…`;
- the tag `v0.1.0` publishes `ghcr.io/<you>/lodestone:0.1.0`.

The chart uses `appVersion` (0.1.0) as the image tag by default, so push the tag.

## Step 2. Make the image reachable

**A. GHCR.** A package created by CI is private. Either make it public (GitHub → Packages → lodestone → Package settings → Change visibility), or create a pull secret and set `imagePullSecrets: [{name: ghcr}]`:

```bash
kubectl -n lodestone create secret docker-registry ghcr \
  --docker-server=ghcr.io --docker-username=<you> --docker-password=<PAT with read:packages>
```

**B. Closed network.** Build the image yourself with your mirrors and push it to your registry:

```bash
docker build -t harbor.corp.local/tools/lodestone:0.1.0 \
  --build-arg NODE_IMAGE=harbor.corp.local/docker-hub/library/node:22-alpine \
  --build-arg PYTHON_IMAGE=harbor.corp.local/docker-hub/library/python:3.12-slim \
  --build-arg NPM_REGISTRY=https://nexus.corp.local/repository/npm-proxy/ \
  --build-arg PIP_INDEX_URL=https://nexus.corp.local/repository/pip-proxy/simple .
docker push harbor.corp.local/tools/lodestone:0.1.0
```

## Step 3. Namespace

```bash
kubectl create namespace lodestone
```

## Step 4. Database

The user must own the database: migrations create tables, types and the `analytics` schema.

```sql
CREATE ROLE lodestone LOGIN PASSWORD '<password>';
CREATE DATABASE lodestone OWNER lodestone ENCODING 'UTF8';
```

Connection string for step 5 (psycopg 3 driver):

```
postgresql+psycopg://lodestone:<password>@pg.corp.local:5432/lodestone?sslmode=require
```

Make sure pods in the `lodestone` namespace can reach PostgreSQL (NetworkPolicy, firewall).

## Step 5. Secrets

All secrets go into one Secret, `lodestone`. Never into Git or values files.

```bash
kubectl -n lodestone create secret generic lodestone \
  --from-literal=secret-key="$(openssl rand -hex 32)" \
  --from-literal=encryption-key="$(openssl rand -hex 32)" \
  --from-literal=database-url='postgresql+psycopg://lodestone:<password>@pg.corp.local:5432/lodestone?sslmode=require' \
  --from-literal=admin-password='<a long break-glass admin password>' \
  --from-literal=ldap-bind-password='<svc-lodestone password>' \
  --from-literal=smtp-password='<SMTP password>'
# with SSO also: --from-literal=oidc-client-secret='<client secret>'
```

| Key | Required | What it is |
|---|---|---|
| `secret-key` | yes | Signs sessions; changing it signs everyone out |
| `database-url` | yes | PostgreSQL connection string |
| `encryption-key` | recommended | Encrypts secrets stored in the DB (LDAP/OIDC/SMTP passwords set in the UI, messenger tokens). **Lose it and those secrets must be entered again** |
| `admin-password` | no | Local admin for when AD is down |
| `ldap-bind-password`, `oidc-client-secret`, `smtp-password` | no | Directory, SSO and mail passwords |
| `setup-token` | no | First-start wizard token, when neither an admin nor LDAP/SSO is configured |

Keep `secret-key` and `encryption-key` in your secret store: you need them to move or restore the installation.

The root CA for LDAPS:

```bash
kubectl -n lodestone create secret generic corp-ca --from-file=ca.crt=./corp-root-ca.crt
```

## Step 6. Values

Start from [deploy/examples/values-prod.yaml](../deploy/examples/values-prod.yaml) and change:
- `image.repository` and `image.tag`;
- `ingress.host` and TLS (a cert-manager issuer or `secretName` of an existing certificate);
- the AD settings: `url`, `bindDn`, `userBase`, `allowedGroup`, `adminGroup`;
- SMTP `host` and `from`, and `notifications.lang`.

For SSO (Keycloak, Entra ID, ADFS) set `auth.oidc.enabled: true`, `issuer` and `clientId`, and register this redirect URI at the identity provider:

```
https://tracker.corp.local/api/auth/oidc/sso/callback
```

## Step 7. Check the chart before installing

```bash
helm lint deploy/helm/lodestone -f values-prod.yaml
helm template lodestone deploy/helm/lodestone -n lodestone -f values-prod.yaml > /tmp/rendered.yaml
kubectl apply --dry-run=server -n lodestone -f /tmp/rendered.yaml
```

## Step 8. Install

```bash
helm upgrade --install lodestone deploy/helm/lodestone -n lodestone -f values-prod.yaml --wait --timeout 10m
kubectl -n lodestone get pods
kubectl -n lodestone logs deploy/lodestone -c migrate     # empty on success; migration errors show here
kubectl -n lodestone logs deploy/lodestone -c app | head
```

The `migrate` init container applies migrations on every rollout. They run under a PostgreSQL advisory lock, so several pods can start at once.

## Step 9. Check it works

```bash
curl -fsS https://tracker.corp.local/healthz          # {"status":"ok"}
```

1. Open `https://tracker.corp.local` and sign in with an AD account from `Lodestone Users`.
2. Sign in with an account from `Lodestone Admins`: the menu shows Administration.
3. Administration → Sign-in: the AD provider came from values; "Test connection" checks the bind account.
4. Administration → Notifications → "Send test e-mail".
5. Create a project and an issue, drag it across the board.

Without an admin, LDAP or SSO in values, the first-start wizard opens; its token is in the log:

```bash
kubectl -n lodestone logs deploy/lodestone -c app | grep "Setup token"
```

## Step 10. After the first start

- **Roles:** give roles to AD groups in Administration → Groups, globally or per project.
- **Import** from Jira, Plane or Confluence is in Administration → Import. Pods connect to the source themselves, so allow egress to it. An import runs inside a web pod: if the pod restarts during an import, the job is marked failed after 15 minutes; run it again, a repeated import updates what it brought in before and creates no copies.
- **Messengers** on internal addresses (Mattermost, Rocket.Chat) need `notifications.allowPrivateWebhooks: true`.
- **A separate notification worker:** `notifications.worker.separate: true`.
- **Power BI:** create a read-only role on the `analytics` schema (README, section Analytics). After upgrades that change views, run `GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO bi_ro` again.

## Step 11. Backups

Pods keep no state: back up PostgreSQL (pg_dump, pgBackRest or your operator) and the `lodestone` Secret.

```bash
pg_dump "postgresql://lodestone:<password>@pg.corp.local/lodestone" -Fc -f lodestone-$(date +%F).dump
```

To restore: `pg_restore` into an empty database, the same Secret, `helm upgrade --install`.

## Step 12. Upgrades

```bash
git tag v0.2.0 && git push origin v0.2.0                 # CI builds image 0.2.0
pg_dump ... -Fc -f before-0.2.0.dump                     # back up before migrations
helm upgrade lodestone deploy/helm/lodestone -n lodestone -f values-prod.yaml --set image.tag=0.2.0 --wait
```

`helm rollback` rolls back the pods, not the database schema. If the new version had migrations, roll back by restoring the dump taken before the upgrade.

## Troubleshooting

| Symptom | Where to look |
|---|---|
| Pod in `Init:CrashLoopBackOff` | `kubectl logs <pod> -c migrate`: usually a wrong `database-url` or the user does not own the database |
| `ImagePullBackOff` | The GHCR package is private and `imagePullSecrets` is not set (step 2) |
| Signed out right after signing in | The site is served over http; the cookie needs HTTPS. Add TLS to the Ingress |
| "Wrong username or password" for every AD account | Administration → Sign-in → "Test connection": `bindDn`/password, the LDAPS CA, `userFilter` |
| The same message for some people only | They are not in `allowedGroup` (Lodestone does not say why on purpose). Nested AD groups need `nestedGroups: true` |
| SSO fails with a redirect_uri error | The redirect URI at the provider must match step 6 exactly |
| No e-mails | Administration → Notifications → delivery log shows the SMTP error |
| Import fails with "access denied" | Wrong token. Cloud: the user is your e-mail; Server: your login, or empty for a personal access token |
| Import fails to connect | No egress from the namespace to Jira/Confluence |
