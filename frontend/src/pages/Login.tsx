import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, AuthConfig, Me } from "../api";
import { Logo } from "../components/bits";
import { Lang, TKey, useT } from "../i18n";

export default function Login({ config, onLogin }: { config: AuthConfig; onLogin: (u: Me) => void }) {
  const { t, lang, setLang } = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [provider, setProvider] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const directories = config.password_providers.filter((p) => p.type === "ldap");
  const next = location.pathname + location.search;

  useEffect(() => {
    // SSO callback errors come back as ?login_error=<code>
    const params = new URLSearchParams(location.search);
    const code = params.get("login_error");
    if (code) {
      setError(t(`login.err.${code}` as TKey));
      params.delete("login_error");
      history.replaceState(null, "", location.pathname + (params.toString() ? `?${params}` : ""));
    }
  }, [t]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.login(username.trim(), password, provider || undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("err.generic"));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  const sub = directories.length || config.sso.length ? (directories.length ? t("login.sub.ldap") : t("login.sub.sso"))
    : t("login.sub.local");
  return (
    <div className="login">
      <div className="login-art">
        <div className="brand"><Logo size={26} /> Lodestone</div>
        <svg className="needle" viewBox="0 0 200 200" aria-hidden="true">
          <circle cx="100" cy="100" r="96" fill="none" stroke="#2a2e37" strokeWidth="1" />
          <circle cx="100" cy="100" r="70" fill="none" stroke="#2a2e37" strokeWidth="1" strokeDasharray="2 6" />
          <g transform="rotate(28 100 100)">
            <path d="M100 18 L114 100 L100 182 L86 100 Z" fill="#2a2e37" />
            <path d="M100 18 L114 100 L86 100 Z" fill="#5b67f0" />
            <circle cx="100" cy="100" r="5" fill="#e9ebef" />
          </g>
        </svg>
        <p>{t("login.tagline")}</p>
      </div>
      <form className="login-form" onSubmit={submit}>
        <div className="lang" style={{ alignSelf: "flex-end" }}>
          {(["ru", "en"] as Lang[]).map((l) => (
            <button type="button" key={l} className={l === lang ? "on" : ""} onClick={() => setLang(l)}>{l.toUpperCase()}</button>
          ))}
        </div>
        <h1>{t("login.title")}</h1>
        <p className="sub">{sub}</p>
        {error && <div className="banner" role="alert">{error}</div>}
        {config.sso.map((p) => (
          <a key={p.slug} className="btn sso" href={`/api/auth/oidc/${p.slug}/login?next=${encodeURIComponent(next)}`}>
            {t("login.sso", { name: p.name })}
          </a>
        ))}
        {config.sso.length > 0 && config.password && <div className="or"><span>{t("login.or")}</span></div>}
        {config.password && (
          <>
            {directories.length > 1 && (
              <label className="field">
                <span>{t("login.directory")}</span>
                <select className="select" value={provider} onChange={(e) => setProvider(e.target.value)}>
                  <option value="">{t("login.directory.auto")}</option>
                  {directories.map((d) => <option key={d.slug} value={d.slug}>{d.name}</option>)}
                </select>
              </label>
            )}
            <label className="field">
              <span>{t("login.username")}</span>
              <input className="input" autoComplete="username" autoFocus={!config.sso.length} value={username}
                     onChange={(e) => setUsername(e.target.value)} required />
              {directories.length > 0 && <span className="hint">{t("login.username.hint")}</span>}
            </label>
            <label className="field">
              <span>{t("login.password")}</span>
              <input className="input" type="password" autoComplete="current-password" value={password}
                     onChange={(e) => setPassword(e.target.value)} required />
            </label>
            <button className="btn primary" style={{ height: 38, justifyContent: "center" }} disabled={busy}>
              {busy ? t("login.busy") : t("login.submit")}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
