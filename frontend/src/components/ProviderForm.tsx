import { useState } from "react";
import { ProviderConfig, ProviderIn, ProviderType, TestResult } from "../api";
import { TKey, useT } from "../i18n";

const LDAP_PRESETS = {
  ad: { user_filter: "(sAMAccountName={username})", attr_email: "mail", attr_name: "displayName", nested_groups: true },
  openldap: { user_filter: "(uid={username})", attr_email: "mail", attr_name: "cn", nested_groups: false },
};

export function emptyProvider(type: ProviderType, n = 1): ProviderIn {
  if (type === "ldap") {
    return {
      slug: n > 1 ? `ldap-${n}` : "ldap", type, name: "Active Directory", enabled: true,
      config: { url: "ldaps://dc01.corp.local:636", start_tls: false, verify_cert: true, ca_pem: "", bind_dn: "",
                bind_password: "", user_base: "", allowed_group: "", admin_group: "", timeout: 10, ...LDAP_PRESETS.ad },
    };
  }
  return {
    slug: n > 1 ? `sso-${n}` : "sso", type: "oidc", name: "SSO", enabled: true,
    config: { issuer: "", client_id: "", client_secret: "", scopes: "openid profile email",
              username_claim: "preferred_username", groups_claim: "groups", allowed_groups: [], admin_groups: [],
              auto_create: true, link_by_email: false },
  };
}

type Field = { key: string; label: TKey; kind?: "text" | "password" | "bool" | "list" | "pem"; hint?: TKey; ph?: string };
const LDAP_FIELDS: Field[] = [
  { key: "url", label: "ldap.url", ph: "ldaps://dc01.corp.local:636" },
  { key: "start_tls", label: "ldap.startTls", kind: "bool" },
  { key: "verify_cert", label: "ldap.verifyCert", kind: "bool" },
  { key: "ca_pem", label: "ldap.caPem", kind: "pem" },
  { key: "bind_dn", label: "ldap.bindDn", ph: "CN=svc-lodestone,OU=Service,DC=corp,DC=local" },
  { key: "bind_password", label: "ldap.bindPassword", kind: "password" },
  { key: "user_base", label: "ldap.userBase", ph: "OU=Users,DC=corp,DC=local" },
  { key: "user_filter", label: "ldap.userFilter" },
  { key: "attr_email", label: "ldap.attrEmail" },
  { key: "attr_name", label: "ldap.attrName" },
  { key: "allowed_group", label: "ldap.allowedGroup", ph: "CN=lodestone-users,OU=Groups,DC=corp,DC=local" },
  { key: "admin_group", label: "ldap.adminGroup", ph: "CN=lodestone-admins,OU=Groups,DC=corp,DC=local" },
  { key: "nested_groups", label: "ldap.nested", kind: "bool" },
];
const OIDC_FIELDS: Field[] = [
  { key: "issuer", label: "oidc.issuer", hint: "oidc.issuerHint", ph: "https://keycloak.corp.local/realms/corp" },
  { key: "client_id", label: "oidc.clientId" },
  { key: "client_secret", label: "oidc.clientSecret", kind: "password" },
  { key: "scopes", label: "oidc.scopes" },
  { key: "username_claim", label: "oidc.usernameClaim" },
  { key: "groups_claim", label: "oidc.groupsClaim", hint: "oidc.groupsHint" },
  { key: "allowed_groups", label: "oidc.allowedGroups", kind: "list" },
  { key: "admin_groups", label: "oidc.adminGroups", kind: "list" },
  { key: "auto_create", label: "oidc.autoCreate", kind: "bool" },
  { key: "link_by_email", label: "oidc.linkEmail", kind: "bool" },
];

export default function ProviderForm({ value, onChange, baseUrl, secretsSet = [], slugLocked, onTest }: {
  value: ProviderIn;
  onChange: (p: ProviderIn) => void;
  baseUrl: string;
  secretsSet?: string[];
  slugLocked?: boolean;
  onTest?: (p: ProviderIn, username: string) => Promise<TestResult>;
}) {
  const { t } = useT();
  const [testUser, setTestUser] = useState("");
  const [result, setResult] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const cfg = value.config;
  const set = (patch: ProviderConfig) => { setResult(null); onChange({ ...value, config: { ...cfg, ...patch } }); };
  const fields = value.type === "ldap" ? LDAP_FIELDS : OIDC_FIELDS;

  async function test() {
    if (!onTest) return;
    setBusy(true);
    try {
      setResult(await onTest(value, testUser.trim()));
    } catch (e) {
      setResult({ ok: false, message: e instanceof Error ? e.message : t("err.generic") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="prov-form">
      <div className="row2">
        <label className="field"><span>{t("prov.name")}</span>
          <input className="input" value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} />
        </label>
        <label className="field"><span>{t("prov.slug")}</span>
          <input className="input" value={value.slug} disabled={slugLocked} maxLength={40}
                 onChange={(e) => onChange({ ...value, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} />
          <span className="hint">{t("prov.slugHint")}</span>
        </label>
      </div>
      {value.type === "ldap" && (
        <label className="field"><span>{t("ldap.preset")}</span>
          <select className="select" value={cfg.user_filter === LDAP_PRESETS.ad.user_filter ? "ad" : "openldap"}
                  onChange={(e) => set(LDAP_PRESETS[e.target.value as "ad" | "openldap"])}>
            <option value="ad">{t("ldap.preset.ad")}</option>
            <option value="openldap">{t("ldap.preset.openldap")}</option>
          </select>
        </label>
      )}
      {fields.map((f) => {
        const v = cfg[f.key];
        if (f.kind === "bool") {
          return (
            <label className="check" key={f.key}>
              <input type="checkbox" checked={!!v} onChange={(e) => set({ [f.key]: e.target.checked })} />{t(f.label)}
            </label>
          );
        }
        const saved = f.kind === "password" && secretsSet.includes(f.key);
        return (
          <label className="field" key={f.key}><span>{t(f.label)}</span>
            {f.kind === "pem" ? (
              <textarea className="textarea mono" style={{ minHeight: 60 }} value={String(v ?? "")}
                        placeholder="-----BEGIN CERTIFICATE-----" onChange={(e) => set({ [f.key]: e.target.value })} />
            ) : (
              <input className="input" type={f.kind === "password" ? "password" : "text"} autoComplete="off"
                     placeholder={saved ? "••••••••" : f.ph}
                     value={f.kind === "list" ? (Array.isArray(v) ? v.join(", ") : String(v ?? "")) : String(v ?? "")}
                     onChange={(e) => set({ [f.key]: f.kind === "list"
                       ? e.target.value.split(",").map((x) => x.trimStart()) : e.target.value })}
                     onBlur={(e) => f.kind === "list" && set({ [f.key]: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
            )}
            {saved && <span className="hint">{t("secret.keep")}</span>}
            {f.hint && <span className="hint">{t(f.hint)}</span>}
          </label>
        );
      })}
      {value.type === "oidc" && (
        <div className="field"><span>{t("oidc.redirect")}</span>
          <code className="copyable">{`${baseUrl.replace(/\/$/, "")}/api/auth/oidc/${value.slug || "<id>"}/callback`}</code>
        </div>
      )}
      {onTest && (
        <div className="test-row">
          {value.type === "ldap" && (
            <input className="input" style={{ maxWidth: 220 }} placeholder={t("prov.testUser")} value={testUser}
                   onChange={(e) => setTestUser(e.target.value)} />
          )}
          <button type="button" className="btn" disabled={busy} onClick={test}>{t("prov.test")}</button>
          {result && <span className={result.ok ? "ok" : "bad"} role="status">{result.message}</span>}
        </div>
      )}
    </div>
  );
}
