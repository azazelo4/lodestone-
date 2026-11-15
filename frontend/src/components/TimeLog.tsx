import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import { api, IssueWorklogs } from "../api";
import { T, useT } from "../i18n";
import type { ProjectData } from "../pages/ProjectView";
import { Avatar } from "./bits";

/** "1h 30m", "1ч 30м", "90m", "1.5" or "1,5" (hours) -> minutes; null if it doesn't read as time. */
export function parseDuration(text: string): number | null {
  const s = text.trim().toLowerCase().replace(",", ".");
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) return Math.round(Number(s) * 60) || null;
  const m = s.match(/^(?:(\d+(?:\.\d+)?)\s*(?:h|ч|час\S*))?\s*(?:(\d+)\s*(?:m|м|мин\S*))?$/);
  if (!m || (!m[1] && !m[2])) return null;
  return Math.round(Number(m[1] ?? 0) * 60 + Number(m[2] ?? 0)) || null;
}

export function formatDuration(t: T, minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return t("time.m", { n: m });
  return m ? `${t("time.h", { n: h })} ${t("time.m", { n: m })}` : t("time.h", { n: h });
}

export function useMoney(currency: string) {
  const { lang } = useT();
  return (v: number | null, digits = 0) => (v === null ? "—" : new Intl.NumberFormat(lang, {
    style: "currency", currency, minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(v));
}

const today = () => new Date().toISOString().slice(0, 10);

/** Time logged on an issue, with a form to log more. Shown in the issue panel. */
export default function TimeLog({ issueKey, ctx }: { issueKey: string; ctx: ProjectData }) {
  const { t } = useT();
  const { user } = useSession();
  const [logs, setLogs] = useState<IssueWorklogs | null>(null);
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState(today);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => { api.worklogs(issueKey).then(setLogs).catch(() => setLogs(null)); }, [issueKey]);
  useEffect(load, [load]);

  async function submit() {
    const minutes = parseDuration(amount);
    if (!minutes) { setError(t("time.bad")); return; }
    setError("");
    try {
      await api.logTime(issueKey, { minutes, work_date: day, note: note.trim() });
      setAmount("");
      setNote("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.generic"));
    }
  }

  const money = useMoney(logs?.currency ?? "USD");
  if (!logs) return null;
  const canLog = ctx.can("time.log");
  if (!canLog && !logs.items.length) return null;
  const canEditAll = ctx.can("finance.manage");

  return (
    <>
      <div className="section-h">
        {t("time.section")}
        {logs.total_minutes > 0 && <span className="n num">{t("time.logged", { t: formatDuration(t, logs.total_minutes) })}</span>}
        {logs.estimate !== null && <span className="n num">· {t("time.ofEstimate", { n: logs.estimate })}</span>}
      </div>
      {logs.items.length === 0 && <p className="hint" style={{ margin: "0 0 8px" }}>{t("time.none")}</p>}
      <div className="worklogs">
        {logs.items.map((w) => (
          <div className="worklog" key={w.id}>
            {w.user && <Avatar user={w.user} />}
            <span className="who">{w.user?.display_name ?? "—"}</span>
            <span className="num dur">{formatDuration(t, w.minutes)}</span>
            <span className="note" title={w.note}>{w.note}</span>
            {w.cost !== null && <span className="num hint">{money(w.cost, 2)}</span>}
            <span className="hint num">{w.work_date}</span>
            {((w.user?.id === user.id && canLog) || canEditAll) && (
              <button className="btn ghost sm" aria-label={t("time.delete")} title={t("time.delete")}
                      onClick={() => api.deleteWorklog(w.id).then(load)}>×</button>
            )}
          </div>
        ))}
      </div>
      {canLog && (
        <form className="worklog-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <input className="input num" aria-label={t("time.amount")} placeholder={t("time.amountPh")} value={amount}
                 onChange={(e) => setAmount(e.target.value)} />
          <input className="input" type="date" aria-label={t("time.date")} value={day} max={today()} onChange={(e) => setDay(e.target.value)} />
          <input className="input" aria-label={t("time.note")} placeholder={t("time.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn" disabled={!amount.trim()}>{t("time.log")}</button>
        </form>
      )}
      {error && <div className="banner" role="alert" style={{ marginTop: 8 }}>{error}</div>}
    </>
  );
}
