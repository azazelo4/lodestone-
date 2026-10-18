import { useCallback, useEffect, useState } from "react";
import { api, ApiError, Channel, ChannelIn, ChannelType, TestResult } from "../api";
import { TKey, useT } from "../i18n";
import { Modal, Toast } from "./bits";

export const CHANNEL_EVENTS = ["created", "assigned", "state_changed", "commented"];
const TYPES: ChannelType[] = ["slack", "mattermost", "rocketchat", "teams", "discord", "telegram", "generic"];
const TYPE_NAMES: Record<ChannelType, string> = {
  slack: "Slack", mattermost: "Mattermost", rocketchat: "Rocket.Chat", teams: "Microsoft Teams", discord: "Discord",
  telegram: "Telegram", generic: "",
};

export function channelTypeName(t: (k: TKey) => string, type: ChannelType) {
  return type === "generic" ? t("ntf.type.generic") : TYPE_NAMES[type];
}

export function eventLabel(t: (k: TKey) => string, ev: string, channel = false) {
  return t((channel && ev === "assigned" ? "ev.assigned.channel" : `ev.${ev}`) as TKey);
}

type Edit = { id?: string; value: ChannelIn; secretsSet: string[] };

function emptyChannel(lang: "en" | "ru"): ChannelIn {
  return { name: "", type: "mattermost", enabled: true, events: [...CHANNEL_EVENTS], lang, config: {}, secrets: {} };
}

function ChannelForm({ edit, onChange }: { edit: Edit; onChange: (v: ChannelIn) => void }) {
  const { t } = useT();
  const v = edit.value;
  const secret = (key: string, label: TKey, hint?: TKey) => {
    const saved = edit.secretsSet.includes(key);
    return (
      <label className="field"><span>{t(label)}</span>
        <input className="input" type="password" autoComplete="off" placeholder={saved ? "••••••••" : undefined}
               value={v.secrets[key] ?? ""} onChange={(e) => onChange({ ...v, secrets: { ...v.secrets, [key]: e.target.value } })} />
        {saved && <span className="hint">{t("secret.keep")}</span>}
        {hint && <span className="hint">{t(hint)}</span>}
      </label>
    );
  };
  const conf = (key: string, label: TKey, hint?: TKey, ph?: string) => (
    <label className="field"><span>{t(label)}</span>
      <input className="input" value={v.config[key] ?? ""} placeholder={ph}
             onChange={(e) => onChange({ ...v, config: { ...v.config, [key]: e.target.value } })} />
      {hint && <span className="hint">{t(hint)}</span>}
    </label>
  );
  return (
    <div className="prov-form">
      <div className="row2">
        <label className="field"><span>{t("ntf.channel.type")}</span>
          <select className="select" value={v.type} disabled={!!edit.id}
                  onChange={(e) => onChange({ ...v, type: e.target.value as ChannelType, config: {}, secrets: {} })}>
            {TYPES.map((x) => <option key={x} value={x}>{channelTypeName(t, x)}</option>)}
          </select>
        </label>
        <label className="field"><span>{t("ntf.channel.name")}</span>
          <input className="input" value={v.name} maxLength={100} placeholder={channelTypeName(t, v.type)}
                 onChange={(e) => onChange({ ...v, name: e.target.value })} />
        </label>
      </div>
      {v.type === "telegram" ? (
        <>
          {secret("bot_token", "ntf.channel.botToken")}
          <div className="row2">
            {conf("chat_id", "ntf.channel.chatId", "ntf.channel.chatIdHint", "-1001234567890")}
            {conf("thread_id", "ntf.channel.threadId")}
          </div>
          {conf("api_url", "ntf.channel.apiUrl", undefined, "https://api.telegram.org")}
        </>
      ) : (
        secret("url", "ntf.channel.url", v.type === "teams" ? "ntf.channel.url.teams" : undefined)
      )}
      {v.type === "generic" && secret("signing_secret", "ntf.channel.signing", "ntf.channel.signingHint")}
      <fieldset className="perm-group">
        <legend>{t("ntf.channel.events")}</legend>
        {CHANNEL_EVENTS.map((ev) => (
          <label className="check" key={ev}>
            <input type="checkbox" checked={v.events.includes(ev)}
                   onChange={(e) => onChange({ ...v, events: e.target.checked ? [...v.events, ev] : v.events.filter((x) => x !== ev) })} />
            {eventLabel(t, ev, true)}
          </label>
        ))}
      </fieldset>
      <div className="row2">
        <label className="field"><span>{t("ntf.lang")}</span>
          <select className="select" value={v.lang} onChange={(e) => onChange({ ...v, lang: e.target.value as "en" | "ru" })}>
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </select>
        </label>
        <label className="check" style={{ alignSelf: "end", paddingBottom: 8 }}>
          <input type="checkbox" checked={v.enabled} onChange={(e) => onChange({ ...v, enabled: e.target.checked })} />{t("prov.enabled")}
        </label>
      </div>
    </div>
  );
}

/** Messenger channels: global ones (projectKey undefined) or those of one project. */
export default function ChannelsEditor({ projectKey }: { projectKey?: string }) {
  const { t, lang } = useT();
  const [rows, setRows] = useState<Channel[]>([]);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const load = useCallback(async () => setRows(await api.channels(projectKey)), [projectKey]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setError("");
    try {
      await fn();
      if (ok) setToast(ok);
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
      return false;
    }
  }

  async function save() {
    if (!edit) return;
    const value = { ...edit.value, name: edit.value.name.trim() || channelTypeName(t, edit.value.type) };
    // empty secret fields mean "keep the stored value"
    value.secrets = Object.fromEntries(Object.entries(value.secrets).filter(([, s]) => s !== ""));
    const ok = await run(() => (edit.id ? api.updateChannel(projectKey, edit.id, value) : api.addChannel(projectKey, value)),
                         t("project.saved"));
    if (ok) { setEdit(null); load(); }
  }

  async function test(id: string) {
    try {
      const r = await api.testChannel(projectKey, id);
      setResults((x) => ({ ...x, [id]: r }));
    } catch (e) {
      setResults((x) => ({ ...x, [id]: { ok: false, message: e instanceof ApiError ? e.message : t("err.generic") } }));
    }
  }

  const ready = edit && (edit.value.type === "telegram"
    ? (edit.value.secrets.bot_token || edit.secretsSet.includes("bot_token")) && edit.value.config.chat_id
    : edit.value.secrets.url || edit.secretsSet.includes("url"));

  return (
    <div>
      {error && <div className="banner" role="alert">{error}</div>}
      <p className="hint">{t("ntf.channels.sub")}</p>
      {rows.length === 0 && <div className="hint" style={{ padding: "8px 0" }}>{t("ntf.channels.empty")}</div>}
      {rows.map((c) => (
        <div className="member-row" key={c.id}>
          <div className="name">
            <div>{c.name} {!c.enabled && <span className="tag">{t("admin.disabled")}</span>}</div>
            <div className="hint">{channelTypeName(t, c.type)} · {c.events.map((ev) => eventLabel(t, ev, true)).join(", ") || "—"}</div>
            {results[c.id] && <div className={`hint ${results[c.id].ok ? "" : "bad"}`} role="status">{results[c.id].message}</div>}
          </div>
          <button className="btn ghost sm" onClick={() => test(c.id)}>{t("ntf.channel.test")}</button>
          <button className="btn ghost sm" onClick={() => setEdit({
            id: c.id, secretsSet: c.secrets_set,
            value: { name: c.name, type: c.type, enabled: c.enabled, events: c.events, lang: c.lang, config: { ...c.config }, secrets: {} },
          })}>{t("admin.edit")}</button>
          <button className="btn ghost sm danger" onClick={() => confirm(t("admin.deleteConfirm", { name: c.name }))
            && run(() => api.deleteChannel(projectKey, c.id)).then(load)}>{t("admin.delete")}</button>
        </div>
      ))}
      <div className="add-methods">
        <button className="btn" onClick={() => setEdit({ value: emptyChannel(lang), secretsSet: [] })}>+ {t("ntf.channel.add")}</button>
      </div>
      {edit && (
        <Modal title={edit.id ? edit.value.name : t("ntf.channel.add")} onClose={() => setEdit(null)} footer={
          <>
            <button className="btn" onClick={() => setEdit(null)}>{t("issue.cancel")}</button>
            <button className="btn primary" disabled={!ready} onClick={save}>{t("admin.save")}</button>
          </>
        }>
          <div className="modal-scroll">
            <ChannelForm edit={edit} onChange={(value) => setEdit({ ...edit, value })} />
          </div>
        </Modal>
      )}
      {toast && <Toast text={toast} onDone={() => setToast("")} />}
    </div>
  );
}
