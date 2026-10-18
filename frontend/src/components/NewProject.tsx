import { FormEvent, useState } from "react";
import { useSession } from "../App";
import { api, ApiError, Project } from "../api";
import { useT } from "../i18n";
import { Modal } from "./bits";

function suggestKey(name: string) {
  const latin = name.toUpperCase().replace(/[^A-Z0-9 ]/g, " ").trim();
  const words = latin.split(/\s+/).filter(Boolean);
  let key = words.length > 1 ? words.map((w) => w[0]).join("") : (words[0] ?? "").slice(0, 4);
  key = key.replace(/^[0-9]+/, "").slice(0, 10);
  return key.length >= 2 ? key : "";
}

export default function NewProject({ onClose, onCreated }: { onClose: () => void; onCreated: (p: Project) => void }) {
  const { t } = useT();
  const { reloadProjects } = useSession();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [priv, setPriv] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const shownKey = keyTouched ? key : suggestKey(name);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError("");
    try {
      const p = await api.createProject({ name: name.trim(), key: shownKey, is_private: priv });
      await reloadProjects();
      onCreated(p);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("err.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={t("project.new")} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>{t("issue.cancel")}</button>
        <button className="btn primary" disabled={busy || !name.trim() || shownKey.length < 2} onClick={() => submit()}>
          {t("project.create")}
        </button>
      </>
    }>
      <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
        {error && <div className="banner" role="alert">{error}</div>}
        <label className="field">
          <span>{t("project.name")}</span>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>{t("project.key")}</span>
          <input className="input num" style={{ maxWidth: 160, textTransform: "uppercase" }} value={shownKey} maxLength={10}
                 onChange={(e) => { setKeyTouched(true); setKey(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "")); }} />
          <span className="hint">{t("project.keyHint", { key: shownKey || "KEY" })}</span>
        </label>
        <label className="check"><input type="radio" checked={priv} onChange={() => setPriv(true)} />{t("project.private")}</label>
        <label className="check"><input type="radio" checked={!priv} onChange={() => setPriv(false)} />{t("project.public")}</label>
        <button hidden />
      </form>
    </Modal>
  );
}
