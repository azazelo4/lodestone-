"""Sign-in providers stored in the DB, first-start state (setup wizard) and import from environment variables."""
import logging
import re
import secrets

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import crypto
from .config import Settings, get_settings
from .ldap_auth import LdapConfig
from .models import AppSetting, AuthProvider, Role, User
from .oidc import OidcConfig
from .rbac import BUILTIN_ROLES, PROJECTS_CREATE

log = logging.getLogger("lodestone")

TYPES = ("local", "ldap", "oidc")
SECRET_FIELDS = {"ldap": ("bind_password",), "oidc": ("client_secret",), "local": ()}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SETUP_KEY = "setup"


# ---------- typed configs
def ldap_config(p: AuthProvider) -> LdapConfig:
    return LdapConfig.from_dict({**(p.config or {}), **crypto.decrypt(p.secrets)})


def oidc_config(p: AuthProvider) -> OidcConfig:
    return OidcConfig.from_dict({**(p.config or {}), **crypto.decrypt(p.secrets)})


def split_secrets(type_: str, config: dict) -> tuple[dict, dict]:
    names = SECRET_FIELDS[type_]
    return {k: v for k, v in config.items() if k not in names}, {k: v for k, v in config.items() if k in names}


def apply(p: AuthProvider, config: dict | None = None, secret_values: dict | None = None):
    """config replaces non-secret settings (non-empty secrets inside it are set too);
    secret_values: key absent = keep, "" or None = clear, value = set."""
    if config is not None:
        plain, inline_secrets = split_secrets(p.type, config)
        p.config = plain
        secret_values = {**{k: v for k, v in inline_secrets.items() if v}, **(secret_values or {})}
    if secret_values:
        current = crypto.decrypt(p.secrets)
        for k, v in secret_values.items():
            if k in SECRET_FIELDS[p.type]:
                current[k] = v or ""
        p.secrets = crypto.encrypt(current)


def decrypt_secrets(p: AuthProvider) -> dict:
    return crypto.decrypt(p.secrets)


def secrets_set(p: AuthProvider) -> list[str]:
    return sorted(k for k, v in crypto.decrypt(p.secrets).items() if v)


def enabled(db: Session, type_: str | None = None) -> list[AuthProvider]:
    stmt = select(AuthProvider).where(AuthProvider.enabled.is_(True))
    if type_:
        stmt = stmt.where(AuthProvider.type == type_)
    return list(db.scalars(stmt.order_by(AuthProvider.position, AuthProvider.name)).all())


def local_provider(db: Session) -> AuthProvider | None:
    return db.scalar(select(AuthProvider).where(AuthProvider.type == "local"))


# ---------- setup state
def setup_state(db: Session) -> dict:
    row = db.get(AppSetting, SETUP_KEY)
    return dict(row.value) if row else {"completed": False}


def setup_required(db: Session) -> bool:
    return not setup_state(db).get("completed")


def mark_setup_completed(db: Session) -> bool:
    """Atomic: only one request can finish the wizard. Returns False if it was already finished."""
    done = db.execute(text(
        "UPDATE app_settings SET value = jsonb_build_object('completed', true) "
        "WHERE key = :k AND coalesce((value->>'completed')::boolean, false) = false"), {"k": SETUP_KEY}).rowcount
    if not done and not db.get(AppSetting, SETUP_KEY):
        done = db.execute(pg_insert(AppSetting).values(key=SETUP_KEY, value={"completed": True})
                          .on_conflict_do_nothing()).rowcount
    return bool(done)


# ---------- env import
def _csv(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def env_providers(s: Settings) -> list[dict]:
    out = [{"slug": "local", "type": "local", "name": "Local accounts", "enabled": s.local_auth_enabled,
            "position": 0, "config": {"admins_only": s.local_admins_only}}]
    if s.ldap_enabled:
        out.append({"slug": "ldap", "type": "ldap", "name": "LDAP", "enabled": True, "position": 1, "config": {
            "url": s.ldap_url, "start_tls": s.ldap_start_tls, "ca_file": s.ldap_ca_file,
            "verify_cert": s.ldap_verify_cert, "bind_dn": s.ldap_bind_dn, "bind_password": s.ldap_bind_password,
            "user_base": s.ldap_user_base, "user_filter": s.ldap_user_filter, "attr_email": s.ldap_attr_email,
            "attr_name": s.ldap_attr_name, "allowed_group": s.ldap_allowed_group, "admin_group": s.ldap_admin_group,
            "nested_groups": s.ldap_nested_groups, "timeout": s.ldap_timeout}})
    if s.oidc_enabled:
        out.append({"slug": "sso", "type": "oidc", "name": s.oidc_name, "enabled": True, "position": 2, "config": {
            "issuer": s.oidc_issuer, "client_id": s.oidc_client_id, "client_secret": s.oidc_client_secret,
            "scopes": s.oidc_scopes, "groups_claim": s.oidc_groups_claim,
            "allowed_groups": _csv(s.oidc_allowed_groups), "admin_groups": _csv(s.oidc_admin_groups),
            "timeout": s.oidc_timeout}})
    return out


def import_env(db: Session, s: Settings, overwrite: bool):
    for spec in env_providers(s):
        p = db.scalar(select(AuthProvider).where(AuthProvider.slug == spec["slug"]))
        if p and not overwrite:
            continue
        if p is None:
            p = AuthProvider(slug=spec["slug"], type=spec["type"])
            db.add(p)
        elif p.type != spec["type"]:
            log.warning("provider %s exists with another type, env import skipped", spec["slug"])
            continue
        p.name, p.enabled, p.position = spec["name"], spec["enabled"], spec["position"]
        apply(p, spec["config"])
    db.flush()
    ldap = db.scalar(select(AuthProvider).where(AuthProvider.slug == "ldap"))
    if ldap:  # users from iteration 1 had no provider link
        db.query(User).filter(User.source == "ldap", User.provider_id.is_(None)).update({User.provider_id: ldap.id})


def ensure_builtin_roles(db: Session, s: Settings):
    for key, (scope, name, perms) in BUILTIN_ROLES.items():
        if key == "user" and s.project_create == "admins":
            perms = [p for p in perms if p != PROJECTS_CREATE]
        db.execute(pg_insert(Role).values(key=key, name=name, scope=scope, permissions=list(perms), builtin=True,
                                          is_default=key == "user", description="")
                   .on_conflict_do_nothing(index_elements=["key"]))


def bootstrap(db: Session):
    """Runs at every start (under an advisory lock: several workers start at once)."""
    s = get_settings()
    db.execute(text("SELECT pg_advisory_xact_lock(7354212)"))
    ensure_builtin_roles(db, s)
    state = db.get(AppSetting, SETUP_KEY)
    if state is None or not state.value.get("completed"):
        headless = bool(s.admin_username and s.admin_password) or s.ldap_enabled or s.oidc_enabled
        has_users = (db.scalar(select(func.count()).select_from(User)) or 0) > 0
        if headless or has_users:  # Helm/compose install or an upgrade from iteration 1: no wizard
            import_env(db, s, overwrite=False)
            mark_setup_completed(db)
        else:
            token = s.setup_token or (state.value.get("token") if state else None) or secrets.token_urlsafe(18)
            if state is None:
                db.add(AppSetting(key=SETUP_KEY, value={"completed": False, "token": token}))
            else:
                state.value = {"completed": False, "token": token}
            log.warning("First start: open %s and finish setup. Setup token: %s", s.base_url, token)
    elif s.auth_sync_env:
        import_env(db, s, overwrite=True)
    db.commit()
