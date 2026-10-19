import { useEffect, useState } from "react";
import { api, Priority, ProjectAnalytics } from "../api";
import { BarChart, ChartCard, HBars, Row, Series, Stat, TimeChart, useDayLabel } from "../components/charts";
import { TKey, useT } from "../i18n";
import type { ProjectData } from "./ProjectView";

const PERIODS = [4, 12, 26, 52];
const PRIORITIES: Priority[] = ["urgent", "high", "medium", "low", "none"];

export default function Analytics({ data, tick }: { data: ProjectData; tick: number }) {
  const { t } = useT();
  const day = useDayLabel();
  const [weeks, setWeeks] = useState(() => {
    try { return Number(localStorage.getItem("lodestone.analytics.weeks")) || 12; } catch { return 12; }
  });
  const [r, setR] = useState<ProjectAnalytics | null>(null);
  const key = data.project.key;
  useEffect(() => { api.analytics(key, weeks).then(setR).catch(() => setR(null)); }, [key, weeks, tick]);
  const pick = (w: number) => {
    setWeeks(w);
    try { localStorage.setItem("lodestone.analytics.weeks", String(w)); } catch { /* private mode */ }
  };
  if (!r) return null;
  const tt = r.totals;
  const days = (v: number | null) => (v === null ? "—" : t("an.days", { n: v }));

  const weekly: Row[] = r.weekly.map((w) => ({
    label: day(w.week), tip: t("chart.weekOf", { d: day(w.week) }), values: { created: w.created, completed: w.completed },
  }));
  const weeklySeries: Series[] = [
    { key: "created", name: t("chart.created"), color: "var(--viz-a)" },
    { key: "completed", name: t("chart.completed"), color: "var(--viz-b)" },
  ];
  // stacked bottom-up from done; the legend lists them top-down like the picture
  const flowSeries: Series[] = [
    { key: "done", name: t("cat.done"), color: "var(--viz-4)" },
    { key: "in_progress", name: t("cat.in_progress"), color: "var(--viz-3)" },
    { key: "todo", name: t("cat.todo"), color: "var(--viz-2)" },
    { key: "backlog", name: t("cat.backlog"), color: "var(--viz-1)" },
  ];
  const flow: Row[] = r.flow.map((f) => ({
    label: day(f.date), tip: day(f.date), values: { backlog: f.backlog, todo: f.todo, in_progress: f.in_progress, done: f.done },
  }));
  const peopleSeries: Series[] = [
    { key: "todo", name: t("cat.todo"), color: "var(--viz-2)" },
    { key: "in_progress", name: t("cat.in_progress"), color: "var(--viz-3)" },
    { key: "done", name: t("chart.doneInPeriod"), color: "var(--viz-4)" },
  ];
  const prioSeries: Series[] = [{ key: "n", name: t("an.open"), color: "var(--viz-a)" }];
  const open = tt.total - (tt.by_category.done ?? 0) - (tt.by_category.cancelled ?? 0);

  return (
    <div className="page" style={{ maxWidth: 1200 }}>
      <div className="toolbar">
        <span className="hint">{t("an.period")}</span>
        <div className="seg" role="group" aria-label={t("an.period")}>
          {PERIODS.map((w) => <button key={w} className={w === weeks ? "on" : ""} onClick={() => pick(w)}>{t("an.weeks", { n: w })}</button>)}
        </div>
      </div>
      <div className="stats">
        <Stat value={String(open)} label={t("an.open")} sub={`${t("cat.in_progress")}: ${tt.by_category.in_progress ?? 0}`} />
        <Stat value={`${tt.percent}%`} label={t("an.donePct")} sub={t("progress.done", { done: tt.done, scope: tt.scope })} />
        <Stat value={String(tt.overdue)} label={t("an.overdue")} sub={`${t("an.unassigned")}: ${tt.unassigned}`} />
        <Stat value={days(r.lead_time.median)} label={t("an.lead")}
              sub={r.lead_time.count ? t("an.p85", { n: r.lead_time.p85 ?? 0 }) : t("an.noData")} />
        <Stat value={days(r.cycle_time.median)} label={t("an.cycle")}
              sub={r.cycle_time.count ? t("an.p85", { n: r.cycle_time.p85 ?? 0 }) : t("an.noData")} />
      </div>
      <div className="chart-grid">
        <ChartCard title={t("chart.flow")} hint={t("chart.flowHint")} series={[...flowSeries].reverse()} rows={flow} wide>
          <TimeChart rows={flow} series={flowSeries} mode="stack" height={240} label={t("chart.flow")} />
        </ChartCard>
        <ChartCard title={t("chart.weekly")} series={weeklySeries} rows={weekly}>
          <BarChart rows={weekly} series={weeklySeries} label={t("chart.weekly")} />
        </ChartCard>
        <ChartCard title={t("chart.priority")} series={prioSeries} rows={null}>
          <HBars label={t("chart.priority")} series={prioSeries}
                 rows={PRIORITIES.map((p) => ({ label: t(`priority.${p}` as TKey), values: { n: r.priority[p] ?? 0 } }))} />
        </ChartCard>
        {r.people.length > 0 && (
          <ChartCard title={t("chart.people")} hint={t("chart.peopleHint")} series={peopleSeries} rows={null} wide>
            <HBars label={t("chart.people")} series={peopleSeries}
                   rows={r.people.map((p) => ({ label: p.name, values: { todo: p.todo, in_progress: p.in_progress, done: p.done } }))} />
          </ChartCard>
        )}
      </div>
    </div>
  );
}
