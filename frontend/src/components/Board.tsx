import { DragEvent, useState } from "react";
import { api, Issue, State } from "../api";
import { useT } from "../i18n";
import type { ProjectData } from "../pages/ProjectView";
import { Avatars, DueDate, PriorityIcon, StateDot } from "./bits";

function Card({ issue, onOpen, draggable, dragging, onDragStart, onDragEnd }: {
  issue: Issue; onOpen: (k: string) => void; draggable: boolean; dragging: boolean;
  onDragStart: (e: DragEvent) => void; onDragEnd: () => void;
}) {
  return (
    <div className={`card${dragging ? " dragging" : ""}`} draggable={draggable} onDragStart={onDragStart} onDragEnd={onDragEnd}
         onClick={() => onOpen(issue.key)} onKeyDown={(e) => e.key === "Enter" && onOpen(issue.key)} tabIndex={0}
         role="button" aria-label={`${issue.key} ${issue.title}`}>
      <div className="title">{issue.title}</div>
      <div className="meta">
        <span className="key">{issue.key}</span>
        <PriorityIcon priority={issue.priority} />
        {issue.subtasks_total > 0 && <span className="num">{issue.subtasks_done}/{issue.subtasks_total}</span>}
        <DueDate due={issue.due_date} category={issue.state.category} />
        <Avatars users={issue.assignees} />
      </div>
      {issue.labels.length > 0 && (
        <div className="meta" style={{ flexWrap: "wrap", gap: 8 }}>
          {issue.labels.map((l) => <span key={l.id} className="label-chip"><i style={{ background: l.color }} />{l.name}</span>)}
        </div>
      )}
    </div>
  );
}

export default function Board({ data, issues, setIssues, onOpen, onAdd }: {
  data: ProjectData; issues: Issue[]; setIssues: (f: (prev: Issue[]) => Issue[]) => void;
  onOpen: (k: string) => void; onAdd: (stateId: string) => void;
}) {
  const { t } = useT();
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [over, setOver] = useState<{ state: string; index: number } | null>(null);
  const states = data.project.states;
  const byState = (s: State) => issues.filter((i) => i.state.id === s.id).sort((a, b) => a.position - b.position);

  function indexAt(e: DragEvent, colEl: HTMLElement) {
    const cards = Array.from(colEl.querySelectorAll<HTMLElement>(".card:not(.dragging)"));
    const y = e.clientY;
    const idx = cards.findIndex((c) => {
      const r = c.getBoundingClientRect();
      return y < r.top + r.height / 2;
    });
    return idx === -1 ? cards.length : idx;
  }

  async function drop(state: State) {
    const key = dragKey;
    const target = over;
    setDragKey(null);
    setOver(null);
    if (!key || !target) return;
    const moving = issues.find((i) => i.key === key);
    if (!moving) return;
    const col = byState(state).filter((i) => i.key !== key);
    const before = col[target.index - 1];
    const after = col[target.index];
    const position = before && after ? (before.position + after.position) / 2
      : before ? before.position + 1024 : after ? after.position - 1024 : 1024;
    if (moving.state.id === state.id && Math.abs(moving.position - position) < 1e-9) return;
    const prev = issues;
    setIssues((list) => list.map((i) => (i.key === key ? { ...i, state, position } : i)));  // optimistic
    try {
      const body: Record<string, unknown> = { position };
      if (moving.state.id !== state.id) body.state_id = state.id;
      const updated = await api.patchIssue(key, body);
      setIssues((list) => list.map((i) => (i.key === key ? { ...i, ...updated } : i)));
    } catch {
      setIssues(() => prev);
    }
  }

  return (
    <div className="board">
      {states.map((s) => {
        const list = byState(s);
        const visible = list.filter((i) => i.key !== dragKey);
        return (
          <section className="col" key={s.id} aria-label={s.name}>
            <div className="col-head">
              <StateDot category={s.category} />
              <span>{s.name}</span>
              <span className="n num">{list.length}</span>
              {data.can("issues.create") && <button className="btn ghost sm" onClick={() => onAdd(s.id)} title={t("board.add")} aria-label={t("board.add")}>+</button>}
            </div>
            <div className={`col-body${over?.state === s.id ? " over" : ""}`}
                 onDragOver={(e) => { if (!dragKey) return; e.preventDefault(); setOver({ state: s.id, index: indexAt(e, e.currentTarget) }); }}
                 onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(null); }}
                 onDrop={(e) => { e.preventDefault(); drop(s); }}>
              {list.map((i) => {
                const vIndex = visible.indexOf(i);
                return (
                  <div key={i.id} style={{ display: "contents" }}>
                    {over?.state === s.id && dragKey && vIndex === over.index && i.key !== dragKey && <div className="drop-line" />}
                    <Card issue={i} onOpen={onOpen} draggable={data.canEdit} dragging={dragKey === i.key}
                          onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", i.key); setDragKey(i.key); }}
                          onDragEnd={() => { setDragKey(null); setOver(null); }} />
                  </div>
                );
              })}
              {over?.state === s.id && dragKey && over.index >= visible.length && visible.length > 0 && <div className="drop-line" />}
              {list.length === 0 && <div className="col-empty">{t("board.empty")}</div>}
            </div>
          </section>
        );
      })}
    </div>
  );
}
