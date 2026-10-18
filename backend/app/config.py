from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables (prefix LODESTONE_)."""

    model_config = SettingsConfigDict(env_prefix="LODESTONE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://lodestone:lodestone@localhost:5432/lodestone"
    secret_key: str = Field(default="change-me", min_length=8)
    encryption_key: str = ""  # for provider secrets in the DB; empty = derived from secret_key
    session_hours: int = 12
    cookie_secure: bool = True
    base_url: str = "http://localhost:8000"
    static_dir: str = ""  # built frontend; empty = API only

    # First start. With LODESTONE_ADMIN_USERNAME/PASSWORD (or any users already in the DB) the setup wizard is
    # skipped and sign-in providers are imported from the variables below. Otherwise the web UI shows the wizard,
    # protected by a one-time token (LODESTONE_SETUP_TOKEN, or a random one printed to the log).
    setup_token: str = ""
    # true = the providers below are re-applied from env on every start (GitOps); false = env is read only once,
    # afterwards providers are managed in the admin UI.
    auth_sync_env: bool = False

    # local accounts (break-glass admin, demo)
    local_auth_enabled: bool = True
    local_admins_only: bool = False  # local accounts only for admins (break-glass), everyone else via LDAP/SSO
    admin_username: str = ""
    admin_password: str = ""

    # LDAP / Active Directory (imported as provider "ldap")
    ldap_enabled: bool = False
    ldap_url: str = "ldap://localhost:389"  # ldaps://dc.corp.local:636 for AD
    ldap_start_tls: bool = False
    ldap_ca_file: str = ""
    ldap_verify_cert: bool = True
    ldap_bind_dn: str = ""  # service account, e.g. CN=svc-lodestone,OU=Service,DC=corp,DC=local
    ldap_bind_password: str = ""
    ldap_user_base: str = ""  # OU=Users,DC=corp,DC=local
    ldap_user_filter: str = "(sAMAccountName={username})"  # OpenLDAP: (uid={username})
    ldap_attr_email: str = "mail"
    ldap_attr_name: str = "displayName"
    ldap_allowed_group: str = ""  # DN; empty = any user found under user_base may log in
    ldap_admin_group: str = ""  # DN; members become global admins
    ldap_nested_groups: bool = False  # AD only: LDAP_MATCHING_RULE_IN_CHAIN
    ldap_timeout: int = 10

    # OpenID Connect SSO: Keycloak, Entra ID (Azure AD), ADFS, Google, GitLab, Okta... (imported as provider "sso")
    oidc_enabled: bool = False
    oidc_name: str = "SSO"
    oidc_issuer: str = ""  # e.g. https://keycloak.corp.local/realms/corp
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    oidc_groups_claim: str = "groups"
    oidc_allowed_groups: str = ""  # comma-separated; empty = anyone the IdP lets through
    oidc_admin_groups: str = ""  # comma-separated
    oidc_timeout: int = 10

    # who may create projects on first start: "all" or "admins" (later: permissions of the "user" role)
    project_create: str = "all"

    # Notifications. SMTP_* are the initial mail settings (later edited in Administration -> Notifications).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"  # none | starttls | ssl
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # "Lodestone <lodestone@corp.local>"
    notify_lang: str = "en"  # default language of e-mails and messenger posts: en | ru
    notify_worker: bool = True  # send from the web process; false = run "entrypoint.sh worker" separately
    webhook_allow_private: bool = False  # allow webhooks to private/loopback addresses (on-prem Mattermost...)
    webhook_timeout: int = 10

    login_max_failures: int = 5
    login_lock_minutes: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
