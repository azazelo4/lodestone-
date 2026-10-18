"""Administration: sign-in providers, roles, group-to-role bindings."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import ldap_auth, oidc, providers, rbac
from ..db import get_db
from ..deps import current_user, require
from ..models import AuthProvider, GroupBinding, ProjectMember, Role, User
from ..schemas import (
    BindingIn,
    BindingOut,
    PermissionInfo,
    ProviderBrief,
    ProviderIn,
    ProviderOut,
    ProviderPatch,
    ProviderTest,
    RoleIn,
    RoleOut,
    RolePatch,
    TestResult,
)

router = APIRouter(prefix="/api", tags=["admin"])


# ---------- shared helpers (also used by the setup wizard and project settings)
def provider_out(p: AuthProvider) -> ProviderOut:
    from .auth import redirect_uri  # avoid import cycle

    out = ProviderOut.model_validate(p, from_attributes=True)
    out.secrets_set = providers.secrets_set(p)
    out.redirect_uri = redirect_uri(p.slug) if p.type == "oidc" else None
    return out


def new_provider(body: ProviderIn, position: int | None = None) -> AuthProvider:
    p = AuthProvider(slug=body.slug, type=body.type, name=body.name, enabled=body.enabled,
                     position=body.position if position is None else position)
    providers.apply(p, body.config)
    return p


def run_test(type_: str, config: dict, username: str = "") -> TestResult:
    if type_ == "ldap":
        return TestResult(**ldap_auth.test_connection(ldap_auth.LdapConfig.from_dict(config), username))
    if type_ == "oidc":
        cfg = oidc.OidcConfig.from_dict(config)
        if not cfg.issuer or not cfg.client_id:
            return TestResult(ok=False, message="issuer and client_id are required")
        return TestResult(**oidc.test_connection(cfg))
    return TestResult(ok=True, message="Nothing to test for local accounts")


def binding_out(b: GroupBinding, project_key: str | None = None) -> BindingOut:
    return BindingOut(id=b.id, group=b.group, role=b.role, project_key=project_key,
                      provider=ProviderBrief(slug=b.provider.slug, type=b.provider.type, name=b.provider.name)
                      if b.provider else None)


def resolve_binding(db: Session, body: BindingIn, scope: str) -> tuple[Role, AuthProvider | None]:
    role = db.scalar(select(Role).where(Role.key == body.role))
    if not role or role.scope != scope:
        raise HTTPException(422, f"Unknown {scope} role {body.role}")
    provider = None
    if body.provider:
        provider = db.scalar(select(AuthProvider).where(AuthProvider.slug == body.provider))
        if not provider or provider.type == "local":
            raise HTTPException(422, "Groups come from an LDAP or OIDC provider")
    return role, provider


# ---------- providers
@router.get("/admin/auth-providers", response_model=list[ProviderOut])
def list_providers(db: Session = Depends(get_db), _: User = Depends(require(rbac.AUTH_MANAGE))):
    return [provider_out(p) for p in db.scalars(select(AuthProvider).order_by(AuthProvider.position,
                                                                              AuthProvider.name)).all()]


@router.post("/admin/auth-providers", response_model=ProviderOut, status_code=201)
def create_provider(body: ProviderIn, db: Session = Depends(get_db), _: User = Depends(require(rbac.AUTH_MANAGE))):
    if body.type == "local":
        raise HTTPException(422, "There is exactly one local provider; edit it instead")
    if db.scalar(select(AuthProvider).where(AuthProvider.slug == body.slug)):
        raise HTTPException(409, f"Provider {body.slug} exists")
    p = new_provider(body)
    db.add(p)
    db.commit()
    return provider_out(p)


def _provider(db: Session, provider_id: uuid.UUID) -> AuthProvider:
    p = db.get(AuthProvider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    return p


def _check_not_last(db: Session, p: AuthProvider):
    others = db.scalar(select(func.count()).select_from(AuthProvider).where(
        AuthProvider.enabled.is_(True), AuthProvider.id != p.id)) or 0
    if not others:
        raise HTTPException(400, "At least one sign-in provider must stay enabled")


@router.patch("/admin/auth-providers/{provider_id}", response_model=ProviderOut)
def patch_provider(provider_id: uuid.UUID, body: ProviderPatch, db: Session = Depends(get_db),
                   _: User = Depends(require(rbac.AUTH_MANAGE))):
    p = _provider(db, provider_id)
    if body.enabled is False and p.enabled:
        _check_not_last(db, p)
    for k in ("name", "enabled", "position"):
        v = getattr(body, k)
        if v is not None:
            setattr(p, k, v)
    if body.config is not None or body.secrets is not None:
        providers.apply(p, body.config, body.secrets)
    db.commit()
    return provider_out(p)


@router.delete("/admin/auth-providers/{provider_id}", status_code=204)
def delete_provider(provider_id: uuid.UUID, db: Session = Depends(get_db),
                    _: User = Depends(require(rbac.AUTH_MANAGE))):
    p = _provider(db, provider_id)
    if p.type == "local":
        raise HTTPException(400, "The local provider can be disabled, not deleted")
    if p.enabled:
        _check_not_last(db, p)
    db.delete(p)  # its users stay but cannot sign in until linked to another provider
    db.commit()


@router.post("/admin/auth-providers/test", response_model=TestResult)
def test_provider(body: ProviderTest, db: Session = Depends(get_db), _: User = Depends(require(rbac.AUTH_MANAGE))):
    if body.provider_id:
        p = _provider(db, body.provider_id)
        config = {**(p.config or {}), **providers.decrypt_secrets(p)}
        if body.provider:  # unsaved edits on top of the saved provider; an empty secret keeps the saved one
            for k, v in body.provider.config.items():
                if v or k not in providers.SECRET_FIELDS[p.type]:
                    config[k] = v
        return run_test(p.type, config, body.username)
    if not body.provider:
        raise HTTPException(422, "provider or provider_id is required")
    return run_test(body.provider.type, body.provider.config, body.username)


# ---------- roles
@router.get("/permissions", response_model=list[PermissionInfo])
def permissions(_: User = Depends(current_user)):
    return ([PermissionInfo(key=p, scope="global") for p in rbac.GLOBAL_PERMISSIONS]
            + [PermissionInfo(key=p, scope="project") for p in rbac.PROJECT_PERMISSIONS])


@router.get("/roles", response_model=list[RoleOut])
def list_roles(scope: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Role)
    if scope:
        stmt = stmt.where(Role.scope == scope)
    return db.scalars(stmt.order_by(Role.scope, Role.builtin.desc(), Role.name)).all()


def _no_escalation(db: Session, user: User, perms: list[str]):
    mine = rbac.global_permissions(db, user)
    extra = set(perms) - mine
    if extra and not user.is_admin:
        raise HTTPException(403, f"You cannot grant permissions you do not have: {', '.join(sorted(extra))}")


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(body: RoleIn, db: Session = Depends(get_db), user: User = Depends(require(rbac.ROLES_MANAGE))):
    try:
        perms = rbac.valid_permissions(body.scope, body.permissions)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    _no_escalation(db, user, perms)
    if db.scalar(select(Role).where(Role.key == body.key)):
        raise HTTPException(409, f"Role {body.key} exists")
    r = Role(key=body.key, name=body.name, description=body.description, scope=body.scope, permissions=perms)
    db.add(r)
    db.commit()
    return r


def _role(db: Session, role_id: uuid.UUID) -> Role:
    r = db.get(Role, role_id)
    if not r:
        raise HTTPException(404, "Role not found")
    return r


@router.patch("/roles/{role_id}", response_model=RoleOut)
def patch_role(role_id: uuid.UUID, body: RolePatch, db: Session = Depends(get_db),
               user: User = Depends(require(rbac.ROLES_MANAGE))):
    r = _role(db, role_id)
    if body.permissions is not None:
        if r.key in rbac.LOCKED_ROLES:
            raise HTTPException(400, "Permissions of the project admin role cannot be changed")
        try:
            perms = rbac.valid_permissions(r.scope, body.permissions)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        _no_escalation(db, user, perms)
        r.permissions = perms
    if body.is_default is not None:
        if r.scope != "global":
            raise HTTPException(422, "Only global roles can be default")
        _no_escalation(db, user, r.permissions)
        r.is_default = body.is_default
    for k in ("name", "description"):
        v = getattr(body, k)
        if v is not None:
            setattr(r, k, v)
    db.commit()
    return r


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require(rbac.ROLES_MANAGE))):
    r = _role(db, role_id)
    if r.builtin:
        raise HTTPException(400, "Builtin roles cannot be deleted")
    used = db.scalar(select(func.count()).select_from(ProjectMember).where(ProjectMember.role_id == r.id))
    if used:
        raise HTTPException(409, f"{used} project members have this role; give them another role first")
    db.delete(r)
    db.commit()


# ---------- global group bindings
@router.get("/admin/group-bindings", response_model=list[BindingOut])
def list_bindings(db: Session = Depends(get_db), _: User = Depends(require(rbac.ROLES_MANAGE))):
    rows = db.scalars(select(GroupBinding).options(selectinload(GroupBinding.role), selectinload(GroupBinding.provider))
                      .where(GroupBinding.project_id.is_(None)).order_by(GroupBinding.group)).all()
    return [binding_out(b) for b in rows]


@router.post("/admin/group-bindings", response_model=BindingOut, status_code=201)
def add_binding(body: BindingIn, db: Session = Depends(get_db), user: User = Depends(require(rbac.ROLES_MANAGE))):
    role, provider = resolve_binding(db, body, "global")
    _no_escalation(db, user, role.permissions)
    b = GroupBinding(group=body.group.strip(), role_id=role.id, provider_id=provider.id if provider else None)
    db.add(b)
    db.commit()
    db.refresh(b)
    return binding_out(b)


@router.delete("/admin/group-bindings/{binding_id}", status_code=204)
def delete_binding(binding_id: uuid.UUID, db: Session = Depends(get_db),
                   _: User = Depends(require(rbac.ROLES_MANAGE))):
    b = db.get(GroupBinding, binding_id)
    if not b or b.project_id is not None:
        raise HTTPException(404, "Binding not found")
    db.delete(b)
    db.commit()
