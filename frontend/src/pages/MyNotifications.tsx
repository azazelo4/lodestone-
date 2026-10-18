import { useEffect, useState } from "react";
import { useSession } from "../App";
import { api, ApiError, NotifyPrefs } from "../api";
import { Toast } from "../components/bits";
import { eventLabel } from "../components/ChannelsEditor";
import { useT } from "../i18n";

const EVENTS = ["assigned", "mentioned", "commented", "state_changed"];

export default function MyNotifications() {
  const { t } = useT();
  const { user } = useSession();
  const [p, setP] = useState<NotifyPrefs | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  useEffect(() => { api.myNotifications().then(setP).catch(() => {}); }, []);

  async function save(next: NotifyPrefs) {
    setP(next);
    setError("");
    try {
      setP(await api.setMyNotifications(next));
      setToast(t("project.saved"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
    }
  }

  return (
    <>
      <div className="topbar"><h1>{t("ntf.my.title")}</h1></div>
      <div className="content">
        <div className="page settings-grid">
          {error && <div className="banner" role="alert">{error}</div>}
          {p && (
            <section className="prov-form" style={{ maxWidth: 560 }}>
              <p className="hint" style={{ margin: 0 }}>{t("ntf.my.sub")}</p>
              {!user.email && <div className="banner info">{t("ntf.my.noEmail")}</div>}
              <label className="check">
                <input type="checkbox" checked={p.email_enabled} onChange={(e) => save({ ...p, email_enabled: e.target.checked })} />
                {t("ntf.my.email")}{user.email && <span className="hint">&nbsp;{user.email}</span>}
              </label>
              <fieldset className="perm-group" disabled={!p.email_enabled}>
                <legend>{t("ntf.my.events")}</legend>
                {EVENTS.map((ev) => (
                  <label className="check" key={ev}>
                    <input type="checkbox" checked={p.events.includes(ev)}
                           onChange={(e) => save({ ...p, events: e.target.checked ? [...p.events, ev] : p.events.filter((x) => x !== ev) })} />
                    {eventLabel(t, ev)}
                  </label>
                ))}
              </fieldset>
              <label className="field" style={{ maxWidth: 240 }}><span>{t("ntf.lang")}</span>
                <select className="select" value={p.lang ?? ""} onChange={(e) => save({ ...p, lang: (e.target.value || null) as NotifyPrefs["lang"] })}>
                  <option value="">{t("ntf.lang.auto")}</option>
                  <option value="ru">Русский</option>
                  <option value="en">English</option>
                </select>
              </label>
            </section>
          )}
        </div>
      </div>
      {toast && <Toast text={toast} onDone={() => setToast("")} />}
    </>
  );
}
