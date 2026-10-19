import { FormEvent, useState } from "react";
import { api, ApiError, IssueDetail, IssueType, Priority } from "../api";
import { useT } from "../i18n";
import type { ProjectData } from "../pages/ProjectView";
import { Avatar, Modal, MultiPicker } from "./bits";

export interface IssueDefaults { sprint_id?: string; module_ids?: string[] }

export default function NewIssue({ data, stateId, defaults = {}, onClose, onCreated }: {
  data: ProjectData; stateId: string | null; defaults?: IssueDefaults; onClose: () => void; onCreated: (i: IssueDetail) => void;
}) {
  const { t } = useT();
  const { project, members } = data;
  const firstOpen = project.states.find((s) => s.category === "todo") ?? project.states[0];
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [state, setState] = useState(stateId ?? firstOpen?.id ?? "");
  const [priority, setPriority] = useState<Priority>("none");
  const [type, setType] = useState<IssueType>("task");
  const [assignees, setAssignees] = useState<string[]>([]);
  const [due, setDue] = useState("");
  const [parent, setParent] = useState("");
  const [cycle, setCycle] = useState(defaults.sprint_id ?? "");
  const [mods, setMods] = useState<string[]>(defaults.module_ids ?? []);
  const [estimate, setEstimate] = useState("");
  const openCycles = data.cycles.filter((c) => !c.closed);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setError("");
    try {
      onCreated(await api.createIssue(project.key, {
        title: title.trim(), description, state_id: state, priority, type, assignee_ids: assignees,
        due_date: due || null, parent_key: parent.trim().toUpperCase() || null,
        sprint_id: cycle || null, module_ids: mods, estimate: estimate === "" ? null : Number(estimate),
      }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("err.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`${t("issue.new")} · ${project.key}`} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>{t("issue.cancel")}</button>
        <button className="btn primary" disabled={busy || !title.trim()} onClick={() => submit()}>{t("issue.create")}</button>
      </>
    }>
      <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
        {error && <div className="banner" role="alert">{error}</div>}
        <input className="input" style={{ fontSize: 16, fontWeight: 500 }} autoFocus placeholder={t("issue.titlePh")}
               aria-label={t("issue.title")} value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea className="textarea" style={{ minHeight: 90 }} placeholder={t("issue.descriptionPh")}
                  aria-label={t("issue.description")} value={description} onChange={(e) => setDescription(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(); }} />
        <div className="row2">
          <label className="field"><span>{t("issue.state")}</span>
            <select className="select" value={state} onChange={(e) => setState(e.target.value)}>
              {project.states.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="field"><span>{t("issue.priority")}</span>
            <select className="select" value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
              {(["urgent", "high", "medium", "low", "none"] as Priority[]).map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
            </select>
          </label>
        </div>
        <div className="field"><span>{t("issue.assignees")}</span>
          <MultiPicker items={members.map((m) => m.user)} selected={assignees} onChange={setAssignees} placeholder={t("issue.unassigned")}
                       searchable={(u) => `${u.display_name} ${u.username}`}
                       render={(u) => <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}><Avatar user={u} />{u.display_name}</span>} />
        </div>
        <div className="row2">
          <label className="field"><span>{t("issue.type")}</span>
            <select className="select" value={type} onChange={(e) => setType(e.target.value as IssueType)}>
              {(["task", "bug", "story", "epic"] as IssueType[]).map((x) => <option key={x} value={x}>{t(`type.${x}`)}</option>)}
            </select>
          </label>
          <label className="field"><span>{t("issue.due")}</span>
            <input className="input" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
        </div>
        {(openCycles.length > 0 || data.modules.length > 0) && (
          <div className="row2">
            <label className="field"><span>{t("cycle.field")}</span>
              <select className="select" value={cycle} onChange={(e) => setCycle(e.target.value)}>
                <option value="">{t("cycle.none")}</option>
                {openCycles.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <div className="field"><span>{t("module.field")}</span>
              <MultiPicker items={data.modules} selected={mods} onChange={setMods} placeholder={t("module.none")}
                           render={(m) => <span>{m.name}</span>} />
            </div>
          </div>
        )}
        <div className="row2">
          <label className="field"><span>{t("issue.parent")}</span>
            <input className="input num" placeholder={`${project.key}-1`} value={parent} onChange={(e) => setParent(e.target.value)} />
          </label>
          <label className="field"><span>{t("issue.estimate")}</span>
            <input className="input num" type="number" min={0} step="0.5" value={estimate} onChange={(e) => setEstimate(e.target.value)} />
          </label>
        </div>
        <button hidden />
      </form>
    </Modal>
  );
}
