import { useMemo, useState } from "react";
import { Issue, Priority } from "../api";
import { useT } from "../i18n";
import { Avatars, DueDate, PriorityIcon, StateDot } from "./bits";

type SortKey = "key" | "title" | "state" | "priority" | "due" | "updated";
const PRIO: Record<Priority, number> = { urgent: 0, high: 1, medium: 2, low: 3, none: 4 };

export default function IssueList({ issues, onOpen, showProject }: {
  issues: Issue[]; onOpen: (k: string) => void; showProject?: boolean;
}) {
  const { t, lang } = useT();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "key", dir: -1 });
  const sorted = useMemo(() => {
    const cmp: Record<SortKey, (a: Issue, b: Issue) => number> = {
      key: (a, b) => a.key.localeCompare(b.key, undefined, { numeric: true }),
      title: (a, b) => a.title.localeCompare(b.title, lang),
      state: (a, b) => a.state.position - b.state.position,
      priority: (a, b) => PRIO[a.priority] - PRIO[b.priority],
      due: (a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"),
      updated: (a, b) => a.updated_at.localeCompare(b.updated_at),
    };
    return [...issues].sort((a, b) => cmp[sort.key](a, b) * sort.dir);
  }, [issues, sort, lang]);

  if (!issues.length) return <div className="empty">{t("list.empty")}</div>;
  const th = (key: SortKey, label: string) => (
    <th onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }))}
        aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      {label}{sort.key === key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
    </th>
  );
  return (
    <table className="table">
      <thead>
        <tr>
          {th("key", "#")}
          {th("title", t("issue.title"))}
          {th("state", t("issue.state"))}
          {th("priority", t("issue.priority"))}
          <th>{t("issue.assignees")}</th>
          {th("due", t("issue.due"))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((i) => (
          <tr key={i.id} className="row" onClick={() => onOpen(i.key)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen(i.key)}>
            <td className="key" style={{ whiteSpace: "nowrap" }}>{i.key}</td>
            <td>
              <div className="t-title">
                {i.parent_key && !showProject && <span className="sub-ind" title={i.parent_key}>↳</span>}
                <span>{i.title}</span>
                {i.subtasks_total > 0 && <span className="hint num">{i.subtasks_done}/{i.subtasks_total}</span>}
              </div>
            </td>
            <td><span className="state-cell"><StateDot category={i.state.category} />{i.state.name}</span></td>
            <td><span className="state-cell"><PriorityIcon priority={i.priority} />{t(`priority.${i.priority}`)}</span></td>
            <td><Avatars users={i.assignees} max={4} /></td>
            <td><DueDate due={i.due_date} category={i.state.category} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
