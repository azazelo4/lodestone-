"""LDAP / Active Directory authentication.

Flow: bind as service account -> find user by filter -> bind as that user with the given password
-> check group membership (allowed group, admin group). Works with AD and OpenLDAP.
"""
import logging
import ssl
from dataclasses import dataclass, field, fields

from ldap3 import BASE, NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars

log = logging.getLogger("lodestone.ldap")


@dataclass
class LdapConfig:
    """Settings of one LDAP/AD provider (auth_providers.config + decrypted bind_password)."""

    url: str = "ldap://localhost:389"  # ldaps://dc.corp.local:636 for AD
    start_tls: bool = False
    ca_file: str = ""
    ca_pem: str = ""  # corporate CA pasted in the admin UI
    verify_cert: bool = True
    bind_dn: str = ""
    bind_password: str = ""
    user_base: str = ""
    user_filter: str = "(sAMAccountName={username})"
    attr_email: str = "mail"
    attr_name: str = "displayName"
    allowed_group: str = ""
    admin_group: str = ""
    nested_groups: bool = False
    timeout: int = 10

    @classmethod
    def from_dict(cls, data: dict) -> "LdapConfig":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


class LdapUnavailable(Exception):
    pass


@dataclass
class LdapUser:
    username: str
    dn: str
    email: str | None
    display_name: str
    is_admin: bool
    groups: list[str] = field(default_factory=list)  # DNs (lower-case) of checked groups the user is in


def _server(s: LdapConfig) -> Server:
    tls = None
    if s.url.startswith("ldaps://") or s.start_tls:
        tls = Tls(validate=ssl.CERT_REQUIRED if s.verify_cert else ssl.CERT_NONE,
                  ca_certs_file=s.ca_file or None, ca_certs_data=s.ca_pem or None)
    return Server(s.url, use_ssl=s.url.startswith("ldaps://"), tls=tls, get_info=NONE, connect_timeout=s.timeout)


def _connect(s: LdapConfig, server: Server, user: str | None, password: str | None, connection_factory=Connection):
    conn = connection_factory(server, user=user, password=password, receive_timeout=s.timeout,
                              raise_exceptions=False)
    if s.start_tls and not s.url.startswith("ldaps://"):
        conn.open()
        conn.start_tls()
    return conn


def _first(entry_attrs: dict, name: str) -> str | None:
    v = entry_attrs.get(name)
    if isinstance(v, list):
        v = v[0] if v else None
    return str(v) if v else None


def _in_group(s: LdapConfig, conn: Connection, user_dn: str, group_dn: str) -> bool:
    if not group_dn:
        return False
    dn = escape_filter_chars(user_dn)
    if s.nested_groups:  # AD: transitive membership
        conn.search(user_dn, f"(memberOf:1.2.840.113556.1.4.1941:={escape_filter_chars(group_dn)})",
                    search_scope=BASE, attributes=[])
        return bool(conn.entries)
    conn.search(group_dn, f"(|(member={dn})(uniqueMember={dn}))", search_scope=BASE, attributes=[])
    return bool(conn.entries)


def authenticate(s: LdapConfig, username: str, password: str, connection_factory=Connection,
                 check_groups: tuple[str, ...] = ()) -> LdapUser | None:
    """Returns LdapUser on success, None on bad credentials / not allowed. Raises LdapUnavailable.

    check_groups: group DNs used in role bindings; the ones the user belongs to are returned in LdapUser.groups."""
    if not username or not password:  # empty password = anonymous bind on many servers — never allow
        return None
    server = _server(s)
    try:
        svc = _connect(s, server, s.bind_dn or None, s.bind_password or None, connection_factory)
        if not svc.bind():
            log.error("service bind failed: %s", svc.result)
            raise LdapUnavailable("service bind failed")
        flt = s.user_filter.format(username=escape_filter_chars(username))
        svc.search(s.user_base, flt, search_scope=SUBTREE, attributes=[s.attr_email, s.attr_name], size_limit=2)
        if len(svc.entries) != 1:
            return None
        entry = svc.entries[0]
        user_dn = entry.entry_dn
        attrs = entry.entry_attributes_as_dict

        user_conn = _connect(s, server, user_dn, password, connection_factory)
        try:
            if not user_conn.bind():
                return None
        except LDAPBindError:
            return None
        finally:
            user_conn.unbind()

        if s.allowed_group and not _in_group(s, svc, user_dn, s.allowed_group):
            log.info("user %s not in allowed group", username)
            return None
        is_admin = _in_group(s, svc, user_dn, s.admin_group)
        groups = sorted({g.lower() for g in check_groups if g and _in_group(s, svc, user_dn, g)})
        svc.unbind()
        return LdapUser(
            username=username.lower(), dn=user_dn,
            email=_first(attrs, s.attr_email),
            display_name=_first(attrs, s.attr_name) or username,
            is_admin=is_admin, groups=groups,
        )
    except LDAPException as e:
        log.error("ldap error: %s", e)
        raise LdapUnavailable(str(e)) from e



def test_connection(s: LdapConfig, username: str = "", connection_factory=Connection) -> dict:
    """For the setup wizard / admin UI: service bind, then optionally look a user up. Never raises."""
    try:
        svc = _connect(s, _server(s), s.bind_dn or None, s.bind_password or None, connection_factory)
        if not svc.bind():
            return {"ok": False, "message": f"Service account bind failed: {svc.result.get('description', '')}"}
        found = None
        if username:
            svc.search(s.user_base, s.user_filter.format(username=escape_filter_chars(username)),
                       search_scope=SUBTREE, attributes=[s.attr_name], size_limit=2)
            found = svc.entries[0].entry_dn if len(svc.entries) == 1 else None
        svc.unbind()
        if username and not found:
            return {"ok": False, "message": f"Connected, but user {username!r} was not found under {s.user_base}"}
        return {"ok": True, "message": f"Connected; found {found}" if found else "Connected"}
    except LDAPException as e:
        return {"ok": False, "message": f"LDAP error: {e}"}
