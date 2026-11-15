import { useCallback, useEffect, useState } from "react";
import { api, Expense, FinanceBucket, FinanceSettings, FinanceSummary, Rate } from "../api";
import { BarChart, ChartCard, Row, Series, Stat, TimeChart } from "../components/charts";
import { formatDuration, useMoney } from "../components/TimeLog";
import { TKey, useT } from "../i18n";
import type { ProjectData } from "./ProjectView";

const CATEGORIES = ["licenses", "hardware", "contractors", "services", "travel", "other"];
const CURRENCIES = ["KZT", "RUB", "USD", "EUR", "UZS", "KGS", "BYN", "GBP", "CNY"];
const today = () => new Date().toISOString().slice(0, 10);
const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));

/** Short axis label ("сент.", with the year in January) and a full one for tooltips ("сентябрь 2026 г."). */
function useMonthLabel() {
  const { lang } = useT();
  const short = new Intl.DateTimeFormat(lang, { month: "short", timeZone: "UTC" });
  const withYear = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit", timeZone: "UTC" });
  const long = new Intl.DateTimeFormat(lang, { month: "long", year: "numeric", timeZone: "UTC" });
  const d = (iso: string) => new Date(`${iso}T00:00:00Z`);
  return {
    label: (iso: string, first: boolean) => (first || iso.slice(5, 7) === "01" ? withYear : short).format(d(iso)),
    tip: (iso: string) => long.format(d(iso)),
  };
}

function BucketTable({ title, hint, rows, money, extra }: {
  title: string; hint?: string; rows: FinanceBucket[]; money: (v: number | null) => string;
  extra?: { head: string; cell: (b: FinanceBucket) => React.ReactNode };
}) {
  const { t } = useT();
  if (!rows.length) return null;
  return (
    <section className="chart-card">
      <div className="chart-head"><h3>{title}</h3></div>
      {hint && <p className="hint" style={{ margin: "-6px 0 8px" }}>{hint}</p>}
      <table className="viz-table">
        <thead><tr><th>{t("fin.col.name")}</th>{extra && <th>{extra.head}</th>}<th>{t("fin.col.hours")}</th><th>{t("fin.col.cost")}</th></tr></thead>
        <tbody>{rows.map((b) => (
          <tr key={`${b.id ?? b.name}`}>
            <th title={b.name}>{b.key ? <span className="num">{b.key} </span> : null}{b.name}</th>
            {extra && <td className="num">{extra.cell(b)}</td>}
            <td className="num">{b.hours}</td><td className="num">{money(b.cost)}</td>
          </tr>
        ))}</tbody>
      </table>
    </section>
  );
}

function SettingsForm({ data, settings, onSaved }: { data: ProjectData; settings: FinanceSettings; onSaved: () => void }) {
  const { t } = useT();
  const [f, setF] = useState(() => ({
    currency: settings.currency, budget: settings.budget?.toString() ?? "", budget_hours: settings.budget_hours?.toString() ?? "",
    default_rate: settings.default_rate?.toString() ?? "", start_date: settings.start_date ?? "", end_date: settings.end_date ?? "",
  }));
  const [msg, setMsg] = useState("");
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setMsg("");
    try {
      await api.saveFinance(data.project.key, {
        currency: f.currency, budget: num(f.budget), budget_hours: num(f.budget_hours), default_rate: num(f.default_rate),
        start_date: f.start_date || null, end_date: f.end_date || null,
      });
      setMsg(t("fin.saved"));
      onSaved();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : t("err.generic"));
    }
  }
  return (
    <section>
      <h3>{t("fin.settings")}</h3>
      <div className="fin-form">
        <label className="field"><span>{t("fin.budget")}</span>
          <input className="input num" inputMode="decimal" value={f.budget} onChange={set("budget")} /></label>
        <label className="field"><span>{t("fin.currency")}</span>
          <select className="select" value={f.currency} onChange={set("currency")}>
            {[...new Set([f.currency, ...CURRENCIES])].map((c) => <option key={c}>{c}</option>)}
          </select></label>
        <label className="field"><span>{t("fin.budgetHours")}</span>
          <input className="input num" inputMode="decimal" value={f.budget_hours} onChange={set("budget_hours")} /></label>
        <label className="field"><span>{t("fin.defaultRate")}</span>
          <input className="input num" inputMode="decimal" value={f.default_rate} onChange={set("default_rate")} /></label>
        <label className="field"><span>{t("fin.start")}</span>
          <input className="input" type="date" value={f.start_date} onChange={set("start_date")} /></label>
        <label className="field"><span>{t("fin.end")}</span>
          <input className="input" type="date" value={f.end_date} onChange={set("end_date")} /></label>
      </div>
      <p className="hint">{t("fin.defaultRateHint")}. {t("fin.datesHint")}</p>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button className="btn primary" onClick={save}>{t("fin.save")}</button>
        {msg && <span className="hint" role="status">{msg}</span>}
      </div>
    </section>
  );
}

function Rates({ data, rates, money, onChange }: { data: ProjectData; rates: Rate[]; money: (v: number | null, d?: number) => string; onChange: () => void }) {
  const { t } = useT();
  const key = data.project.key;
  const [user, setUser] = useState("");
  const [rate, setRate] = useState("");
  const [from, setFrom] = useState(today);
  const [error, setError] = useState("");
  async function add() {
    setError("");
    try {
      await api.setRate(key, { user_id: user, rate: num(rate) ?? 0, valid_from: from });
      setRate("");
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.generic"));
    }
  }
  return (
    <section>
      <h3>{t("fin.rates")}</h3>
      <p className="hint" style={{ marginTop: -6 }}>{t("fin.ratesHint")}</p>
      {rates.length === 0 && <p className="hint">{t("fin.noRates")}</p>}
      {rates.map((r) => (
        <div className="member-row" key={r.id}>
          <div className="name">{r.user.display_name}</div>
          <span className="num">{money(r.rate, 2)}</span>
          <span className="hint num" style={{ width: 150, whiteSpace: "nowrap" }}>{t("fin.from")} {r.valid_from}</span>
          <button className="btn ghost sm danger" onClick={() => api.deleteRate(key, r.id).then(onChange)}>{t("fin.delete")}</button>
        </div>
      ))}
      <form className="member-row" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <select className="select" style={{ width: 220 }} aria-label={t("fin.person")} value={user} onChange={(e) => setUser(e.target.value)}>
          <option value="">{t("fin.person")}</option>
          {data.members.map((m) => <option key={m.user.id} value={m.user.id}>{m.user.display_name}</option>)}
        </select>
        <input className="input num" style={{ width: 120 }} inputMode="decimal" aria-label={t("fin.rate")} placeholder={t("fin.rate")}
               value={rate} onChange={(e) => setRate(e.target.value)} />
        <input className="input" style={{ width: 160 }} type="date" aria-label={t("fin.from")} value={from} onChange={(e) => setFrom(e.target.value)} />
        <button className="btn" disabled={!user || num(rate) === null}>{t("fin.addRate")}</button>
      </form>
      {error && <div className="banner" role="alert">{error}</div>}
    </section>
  );
}

function Expenses({ data, items, money, onChange }: { data: ProjectData; items: Expense[]; money: (v: number | null, d?: number) => string; onChange: () => void }) {
  const { t } = useT();
  const key = data.project.key;
  const manage = data.can("finance.manage");
  const [f, setF] = useState({ spent_on: today(), amount: "", category: "licenses", description: "", issue_key: "", module_id: "" });
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const cat = (c: string) => (CATEGORIES.includes(c) ? t(`fin.cat.${c}` as TKey) : c);
  async function add() {
    setError("");
    try {
      await api.addExpense(key, {
        spent_on: f.spent_on, amount: num(f.amount) ?? 0, category: f.category, description: f.description.trim(),
        issue_key: f.issue_key.trim().toUpperCase() || null, module_id: f.module_id || null,
      });
      setF({ ...f, amount: "", description: "", issue_key: "" });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.generic"));
    }
  }
  return (
    <section>
      <h3>{t("fin.expenses")}</h3>
      {items.length === 0 ? <p className="hint">{t("fin.noExpenses")}</p> : (
        <table className="table">
          <thead><tr>
            <th>{t("fin.date")}</th><th>{t("fin.category")}</th><th>{t("fin.description")}</th><th>{t("fin.issueKey")}</th>
            <th>{t("fin.module")}</th><th style={{ textAlign: "right" }}>{t("fin.amount")}</th>{manage && <th />}
          </tr></thead>
          <tbody>{items.map((e) => (
            <tr key={e.id}>
              <td className="num">{e.spent_on}</td><td>{cat(e.category)}</td><td>{e.description}</td>
              <td className="num">{e.issue_key ?? ""}</td><td>{e.module?.name ?? ""}</td>
              <td className="num" style={{ textAlign: "right" }}>{money(e.amount, 2)}</td>
              {manage && <td><button className="btn ghost sm danger" onClick={() => api.deleteExpense(key, e.id).then(onChange)}>{t("fin.delete")}</button></td>}
            </tr>
          ))}</tbody>
        </table>
      )}
      {manage && (
        <form className="fin-form expense-form" onSubmit={(e) => { e.preventDefault(); add(); }}>
          <label className="field"><span>{t("fin.date")}</span><input className="input" type="date" value={f.spent_on} onChange={set("spent_on")} /></label>
          <label className="field"><span>{t("fin.amount")}</span><input className="input num" inputMode="decimal" value={f.amount} onChange={set("amount")} /></label>
          <label className="field"><span>{t("fin.category")}</span>
            <select className="select" value={f.category} onChange={set("category")}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{cat(c)}</option>)}
            </select></label>
          <label className="field wide"><span>{t("fin.description")}</span><input className="input" value={f.description} onChange={set("description")} /></label>
          <label className="field"><span>{t("fin.issueKey")}</span>
            <input className="input num" placeholder={`${key}-1`} value={f.issue_key} onChange={set("issue_key")} /></label>
          <label className="field"><span>{t("fin.module")}</span>
            <select className="select" value={f.module_id} onChange={set("module_id")}>
              <option value="" />
              {data.modules.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select></label>
          <div className="field"><span>&nbsp;</span><button className="btn" disabled={num(f.amount) === null}>{t("fin.addExpense")}</button></div>
        </form>
      )}
      {error && <div className="banner" role="alert">{error}</div>}
    </section>
  );
}

export default function Finance({ data, tick }: { data: ProjectData; tick: number }) {
  const { t, lang } = useT();
  const month = useMonthLabel();
  const key = data.project.key;
  const manage = data.can("finance.manage");
  const [s, setS] = useState<FinanceSummary | null>(null);
  const [rates, setRates] = useState<Rate[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const load = useCallback(() => {
    api.finance(key).then(setS).catch(() => setS(null));
    api.rates(key).then(setRates).catch(() => setRates([]));
    api.expenses(key).then(setExpenses).catch(() => setExpenses([]));
  }, [key]);
  useEffect(load, [load, tick]);
  const money = useMoney(s?.settings.currency ?? "USD");

  if (!data.can("finance.view") && !manage) return <div className="empty"><h2>{t("notFound")}</h2><p>{t("notFound.sub")}</p></div>;
  if (!s) return null;
  const tt = s.totals;
  const empty = tt.hours === 0 && tt.expenses === 0;
  const dayFmt = new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const day = (iso: string | null) => (iso ? dayFmt.format(new Date(`${iso}T00:00:00Z`)) : "");
  const { start_date: start, end_date: end } = s.settings;
  const overrun = tt.forecast !== null && tt.budget !== null && tt.forecast > tt.budget ? tt.forecast - tt.budget : 0;

  const planSeries: Series[] = [
    { key: "actual", name: t("chart.actual"), color: "var(--viz-a)" },
    ...(tt.budget !== null && s.months.some((m) => m.plan !== null) ? [{ key: "plan", name: t("chart.plan"), color: "var(--viz-b)", dashed: true }] : []),
  ];
  const planRows: Row[] = s.months.map((m, i) => ({ label: month.label(m.month, i === 0), tip: month.tip(m.month), values: { actual: m.actual, plan: m.plan } }));
  const monthSeries: Series[] = [
    { key: "labor", name: t("chart.labor"), color: "var(--viz-a)" },
    { key: "expenses", name: t("chart.other"), color: "var(--viz-b)" },
  ];
  const monthRows: Row[] = s.months.map((m, i) => ({ label: month.label(m.month, i === 0), tip: month.tip(m.month), values: { labor: m.labor, expenses: m.expenses } }));

  return (
    <div className="page" style={{ maxWidth: 1200 }}>
      <div className="stats money">
        <Stat value={money(tt.budget)} label={t("fin.budget")} sub={tt.budget === null ? t("fin.noBudget") : start && end ? `${day(start)} – ${day(end)}` : undefined} />
        <Stat value={money(tt.spent)} label={t("fin.spent")}
              sub={tt.percent !== null ? t("fin.ofBudget", { p: tt.percent }) : t("fin.split", { a: money(tt.labor), b: money(tt.expenses) })} />
        <Stat value={tt.remaining === null ? "—" : money(Math.abs(tt.remaining))}
              label={tt.remaining !== null && tt.remaining < 0 ? t("fin.over") : t("fin.remaining")}
              sub={t("fin.split", { a: money(tt.labor), b: money(tt.expenses) })} />
        <Stat value={formatDuration(t, Math.round(tt.hours * 60))} label={t("fin.hours")}
              sub={tt.hours_percent !== null ? t("fin.ofHours", { p: tt.hours_percent, n: tt.budget_hours ?? 0 }) : undefined} />
        <Stat value={money(tt.forecast)} label={t("fin.forecast")}
              sub={overrun ? t("fin.forecastOver", { n: money(overrun) })
                : tt.forecast !== null ? t("fin.forecastSub", { d: day(end) }) : t("fin.noForecast")} />
      </div>
      {tt.unrated_hours > 0 && <div className="banner info" style={{ marginBottom: 16 }}>{t("fin.unrated", { n: tt.unrated_hours })}</div>}
      {empty && <p className="hint">{manage ? t("fin.empty") : t("fin.emptyView")}</p>}

      {!empty && (
        <div className="chart-grid">
          <ChartCard title={t("chart.planFact")} hint={t("chart.planFactHint")} series={planSeries} rows={planRows} wide>
            <TimeChart rows={planRows} series={planSeries} height={240} label={t("chart.planFact")} />
          </ChartCard>
          <ChartCard title={t("chart.monthly")} series={monthSeries} rows={monthRows}>
            <BarChart rows={monthRows} series={monthSeries} label={t("chart.monthly")} />
          </ChartCard>
          <BucketTable title={t("fin.issues")} rows={s.issues} money={money}
                       extra={{ head: t("fin.col.estimate"), cell: (b) => b.estimate ?? "—" }} />
          <BucketTable title={t("fin.people")} rows={s.people} money={money}
                       extra={{ head: t("fin.col.rate"), cell: (b) => money(b.rate) }} />
          <BucketTable title={t("fin.modules")} hint={t("fin.modulesHint")} rows={s.modules} money={money} />
          <BucketTable title={t("fin.cycles")} rows={s.cycles} money={money} />
        </div>
      )}

      <div className="settings-grid" style={{ marginTop: 32 }}>
        <Expenses data={data} items={expenses} money={money} onChange={load} />
        {manage && <SettingsForm key={JSON.stringify(s.settings)} data={data} settings={s.settings} onSaved={load} />}
        {manage && <Rates data={data} rates={rates} money={money} onChange={load} />}
      </div>
    </div>
  );
}
