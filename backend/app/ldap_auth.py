"""LDAP / Active Directory authentication.

Flow: bind as service account -> find user by filter -> bind as that user with the given password
-> check group membership (allowed group, admin group). Works with AD and OpenLDAP.
"""
import logging
import ssl
from dataclasses import dataclass

from ldap3 import BASE, NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars

from .config import Settings

log = logging.getLogger("lodestone.ldap")


class LdapUnavailable(Exception):
    pass


@dataclass
class LdapUser:
    username: str
    dn: str
    email: str | None
    display_name: str
    is_admin: bool


def _server(s: Settings) -> Server:
    tls = None
    if s.ldap_url.startswith("ldaps://") or s.ldap_start_tls:
        tls = Tls(validate=ssl.CERT_REQUIRED if s.ldap_verify_cert else ssl.CERT_NONE,
                  ca_certs_file=s.ldap_ca_file or None)
    return Server(s.ldap_url, use_ssl=s.ldap_url.startswith("ldaps://"), tls=tls, get_info=NONE,
                  connect_timeout=s.ldap_timeout)


def _connect(s: Settings, server: Server, user: str | None, password: str | None, connection_factory=Connection):
    conn = connection_factory(server, user=user, password=password, receive_timeout=s.ldap_timeout,
                              raise_exceptions=False)
    if s.ldap_start_tls and not s.ldap_url.startswith("ldaps://"):
        conn.open()
        conn.start_tls()
    return conn


def _first(entry_attrs: dict, name: str) -> str | None:
    v = entry_attrs.get(name)
    if isinstance(v, list):
        v = v[0] if v else None
    return str(v) if v else None


def _in_group(s: Settings, conn: Connection, user_dn: str, group_dn: str) -> bool:
    if not group_dn:
        return False
    dn = escape_filter_chars(user_dn)
    if s.ldap_nested_groups:  # AD: transitive membership
        conn.search(user_dn, f"(memberOf:1.2.840.113556.1.4.1941:={escape_filter_chars(group_dn)})",
                    search_scope=BASE, attributes=[])
        return bool(conn.entries)
    conn.search(group_dn, f"(|(member={dn})(uniqueMember={dn}))", search_scope=BASE, attributes=[])
    return bool(conn.entries)


def authenticate(s: Settings, username: str, password: str, connection_factory=Connection) -> LdapUser | None:
    """Returns LdapUser on success, None on bad credentials / not allowed. Raises LdapUnavailable."""
    if not username or not password:  # empty password = anonymous bind on many servers — never allow
        return None
    server = _server(s)
    try:
        svc = _connect(s, server, s.ldap_bind_dn or None, s.ldap_bind_password or None, connection_factory)
        if not svc.bind():
            log.error("service bind failed: %s", svc.result)
            raise LdapUnavailable("service bind failed")
        flt = s.ldap_user_filter.format(username=escape_filter_chars(username))
        svc.search(s.ldap_user_base, flt, search_scope=SUBTREE,
                   attributes=[s.ldap_attr_email, s.ldap_attr_name], size_limit=2)
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

        if s.ldap_allowed_group and not _in_group(s, svc, user_dn, s.ldap_allowed_group):
            log.info("user %s not in allowed group", username)
            return None
        is_admin = _in_group(s, svc, user_dn, s.ldap_admin_group)
        svc.unbind()
        return LdapUser(
            username=username.lower(), dn=user_dn,
            email=_first(attrs, s.ldap_attr_email),
            display_name=_first(attrs, s.ldap_attr_name) or username,
            is_admin=is_admin,
        )
    except LDAPException as e:
        log.error("ldap error: %s", e)
        raise LdapUnavailable(str(e)) from e

