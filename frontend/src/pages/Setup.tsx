import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, Me, ProviderIn, ProviderType } from "../api";
import { Logo } from "../components/bits";
import ProviderForm, { emptyProvider } from "../components/ProviderForm";
import { Lang, useT } from "../i18n";

const STEPS = ["setup.step.token", "setup.step.admin", "setup.step.auth", "setup.step.done"] as const;

export default function Setup({ onDone }: { onDone: (u: Me) => void }) {
  const { t, lang, setLang } = useT();
  const [step, setStep] = useState(0);
  const [token, setToken] = useState("");
  const [baseUrl, setBaseUrl] = useState(location.origin);
  const [admin, setAdmin] = useState({ username: "admin", display_name: "", email: "", password: "", password2: "" });
  const [localMode, setLocalMode] = useState<"all" | "admins">("all");
  const [providers, setProviders] = useState<ProviderIn[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.setupStatus().then((s) => setBaseUrl(s.base_url)).catch(() => {});
  }, []);

  async function guard(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
    } finally {
      setBusy(false);
    }
  }

  function add(type: ProviderType) {
    setProviders((ps) => [...ps, emptyProvider(type, ps.filter((p) => p.type === type).length + 1)]);
  }

  const adminOk = admin.username.trim().length >= 2 && admin.display_name.trim() && admin.password.length >= 10
    && admin.password === admin.password2;
  const slugs = providers.map((p) => p.slug);
  const providersOk = providers.every((p) => p.slug && p.name.trim()) && new Set(slugs).size === slugs.length
    && !slugs.includes("local");

  function next(e?: FormEvent) {
    e?.preventDefault();
    if (step === 0) guard(async () => { await api.setupVerify(token.trim()); setStep(1); });
    else if (step === 1 && adminOk) setStep(2);
    else if (step === 2 && providersOk) setStep(3);
    else if (step === 3) {
      guard(async () => {
        const { password2: _, ...a } = admin;
        onDone(await api.setupComplete({ token: token.trim(), admin: { ...a, email: a.email || "" }, local_mode: localMode, providers }));
      });
    }
  }

  return (
    <div className="setup">
      <header className="setup-head">
        <div className="brand"><Logo size={22} /> Lodestone</div>
        <span className="hint">{t("setup.title")}</span>
        <span className="spacer" />
        <div className="lang">
          {(["ru", "en"] as Lang[]).map((l) => (
            <button type="button" key={l} className={l === lang ? "on" : ""} onClick={() => setLang(l)}>{l.toUpperCase()}</button>
          ))}
        </div>
      </header>
      <ol className="steps">
        {STEPS.map((s, i) => <li key={s} className={i === step ? "on" : i < step ? "done" : ""}>{t(s)}</li>)}
      </ol>
      <form className="setup-body" onSubmit={next}>
        {error && <div className="banner" role="alert">{error}</div>}

        {step === 0 && (
          <>
            <p className="sub">{t("setup.token.sub")}</p>
            <label className="field"><span>{t("setup.token")}</span>
              <input className="input mono" autoFocus value={token} onChange={(e) => setToken(e.target.value)} />
            </label>
          </>
        )}

        {step === 1 && (
          <>
            <p className="sub">{t("setup.admin.sub")}</p>
            <div className="row2">
              <label className="field"><span>{t("login.username")}</span>
                <input className="input" autoComplete="username" value={admin.username}
                       onChange={(e) => setAdmin({ ...admin, username: e.target.value.replace(/[^A-Za-z0-9._-]/g, "") })} />
              </label>
              <label className="field"><span>{t("setup.displayName")}</span>
                <input className="input" autoFocus value={admin.display_name} onChange={(e) => setAdmin({ ...admin, display_name: e.target.value })} />
              </label>
            </div>
            <label className="field"><span>{t("setup.email")}</span>
              <input className="input" type="email" value={admin.email} onChange={(e) => setAdmin({ ...admin, email: e.target.value })} />
            </label>
            <div className="row2">
              <label className="field"><span>{t("login.password")}</span>
                <input className="input" type="password" autoComplete="new-password" value={admin.password}
                       onChange={(e) => setAdmin({ ...admin, password: e.target.value })} />
                <span className="hint">{t("setup.passwordHint")}</span>
              </label>
              <label className="field"><span>{t("setup.password2")}</span>
                <input className="input" type="password" autoComplete="new-password" value={admin.password2}
                       onChange={(e) => setAdmin({ ...admin, password2: e.target.value })} />
                {admin.password2 && admin.password !== admin.password2 && <span className="hint bad">{t("setup.passwordMismatch")}</span>}
              </label>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <p className="sub">{t("setup.auth.sub")}</p>
            <section className="method">
              <h3>{t("setup.local")}</h3>
              <label className="check"><input type="radio" checked={localMode === "all"} onChange={() => setLocalMode("all")} />{t("setup.local.all")}</label>
              <label className="check"><input type="radio" checked={localMode === "admins"} onChange={() => setLocalMode("admins")} />{t("setup.local.admins")}</label>
            </section>
            {providers.map((p, i) => (
              <section className="method" key={i}>
                <h3>{t(`prov.type.${p.type}`)}
                  <button type="button" className="btn ghost sm danger" onClick={() => setProviders((ps) => ps.filter((_, j) => j !== i))}>{t("prov.remove")}</button>
                </h3>
                <ProviderForm value={p} baseUrl={baseUrl}
                              onChange={(v) => setProviders((ps) => ps.map((x, j) => (j === i ? v : x)))}
                              onTest={(v, user) => api.setupTest(token.trim(), v, user)} />
              </section>
            ))}
            <div className="add-methods">
              <button type="button" className="btn" onClick={() => add("ldap")}>+ {t("setup.addLdap")}</button>
              <button type="button" className="btn" onClick={() => add("oidc")}>+ {t("setup.addOidc")}</button>
            </div>
          </>
        )}

        {step === 3 && (
          <dl className="review">
            <dt>{t("setup.review.admin")}</dt>
            <dd>{admin.display_name} <span className="hint">{admin.username}</span></dd>
            <dt>{t("setup.review.methods")}</dt>
            <dd>{t("setup.local")}: {localMode === "all" ? t("setup.local.all") : t("setup.local.admins")}</dd>
            {providers.map((p) => <dd key={p.slug}>{t(`prov.type.${p.type}`)}: {p.name} <span className="hint">{p.slug}</span></dd>)}
          </dl>
        )}

        <footer className="setup-foot">
          {step > 0 && <button type="button" className="btn" onClick={() => setStep(step - 1)}>{t("setup.back")}</button>}
          <span className="spacer" />
          <button className="btn primary" disabled={busy || (step === 0 && !token.trim()) || (step === 1 && !adminOk) || (step === 2 && !providersOk)}>
            {step === 3 ? t("setup.finish") : t("setup.next")}
          </button>
        </footer>
      </form>
    </div>
  );
}
