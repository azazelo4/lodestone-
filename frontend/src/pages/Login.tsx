import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, User } from "../api";
import { Logo } from "../components/bits";
import { Lang, useT } from "../i18n";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const { t, lang, setLang } = useT();
  const [cfg, setCfg] = useState({ ldap: false, local: true });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.authConfig().then(setCfg).catch(() => {});
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.login(username.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("err.generic"));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

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
        <p className="sub">{cfg.ldap ? t("login.sub.ldap") : t("login.sub.local")}</p>
        {error && <div className="banner" role="alert">{error}</div>}
        <label className="field">
          <span>{t("login.username")}</span>
          <input className="input" autoComplete="username" autoFocus value={username}
                 onChange={(e) => setUsername(e.target.value)} required />
          {cfg.ldap && <span className="hint">{t("login.username.hint")}</span>}
        </label>
        <label className="field">
          <span>{t("login.password")}</span>
          <input className="input" type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <button className="btn primary" style={{ height: 38, justifyContent: "center" }} disabled={busy}>
          {busy ? t("login.busy") : t("login.submit")}
        </button>
      </form>
    </div>
  );
}
