from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables (prefix LODESTONE_)."""

    model_config = SettingsConfigDict(env_prefix="LODESTONE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://lodestone:lodestone@localhost:5432/lodestone"
    secret_key: str = Field(default="change-me", min_length=8)
    session_hours: int = 12
    cookie_secure: bool = True
    base_url: str = "http://localhost:8000"
    static_dir: str = ""  # built frontend; empty = API only

    # local accounts (break-glass admin, demo)
    local_auth_enabled: bool = True
    admin_username: str = ""
    admin_password: str = ""

    # LDAP / Active Directory
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

    # who may create projects: "all" or "admins"
    project_create: str = "all"

    login_max_failures: int = 5
    login_lock_minutes: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
