import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Category, Progress } from "../api";
import { useT } from "../i18n";

/* Small dependency-free SVG charts. Colors come from CSS tokens (--viz-*), so light and dark themes
   swap in one place; text always uses ink tokens, never the series color. */

export interface Series { key: string; name: string; color: string; dashed?: boolean }
export interface Row { label: string; tip: string; values: Record<string, number | null> }

const M = { l: 36, r: 12, t: 12, b: 24 };

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * step >= v) return m * step;
  return 10 * step;
}

const fmt = (v: number | null) => (v === null ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(1));

export function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null;
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.key}><i className={s.dashed ? "dashed" : ""} style={{ background: s.dashed ? undefined : s.color, borderColor: s.color }} />{s.name}</span>
      ))}
    </div>
  );
}

function Tooltip({ x, width, title, items }: { x: number; width: number; title: string; items: { s: Series; v: number | null }[] }) {
  const left = x + 192 > width ? Math.max(x - 192, 0) : x + 12;
  return (
    <div className="viz-tip" style={{ left }} role="status">
      <div className="viz-tip-title">{title}</div>
      {items.map(({ s, v }) => (
        <div key={s.key} className="viz-tip-row">
          <i className={s.dashed ? "dashed" : ""} style={{ background: s.dashed ? undefined : s.color, borderColor: s.color }} />
          <b className="num">{fmt(v)}</b><span>{s.name}</span>
        </div>
      ))}
    </div>
  );
}

function YAxis({ max, h, w }: { max: number; h: number; w: number }) {
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  return (
    <g className="viz-axis">
      {ticks.map((v) => {
        const y = M.t + (h - M.t - M.b) * (1 - v / max);
        return (
          <g key={v}>
            <line x1={M.l} x2={w - M.r} y1={y} y2={y} className={v === 0 ? "base" : "grid"} />
            <text x={M.l - 6} y={y} dy="0.32em" textAnchor="end">{fmt(v)}</text>
          </g>
        );
      })}
    </g>
  );
}

function XLabels({ rows, x, h, w }: { rows: Row[]; x: (i: number) => number; h: number; w: number }) {
  const every = Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor((w - M.l - M.r) / 64))));
  return (
    <g className="viz-axis">
      {rows.map((r, i) => (i % every === 0 || i === rows.length - 1) && (i === rows.length - 1 || rows.length - 1 - i >= every) && (
        <text key={i} x={x(i)} y={h - 6} textAnchor={i === 0 ? "start" : i === rows.length - 1 ? "end" : "middle"}>{r.label}</text>
      ))}
    </g>
  );
}

/** Lines over time (mode "line") or a stacked area (mode "stack"), with a crosshair readout. */
export function TimeChart({ rows, series, mode = "line", height = 220, label }: {
  rows: Row[]; series: Series[]; mode?: "line" | "stack"; height?: number; label: string;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const h = height;
  const n = rows.length;
  const x = (i: number) => M.l + (n <= 1 ? 0 : (i * (w - M.l - M.r)) / (n - 1));
  const sums = rows.map((r) => series.reduce((a, s) => a + (r.values[s.key] ?? 0), 0));
  const max = niceMax(Math.max(1, ...(mode === "stack" ? sums : rows.flatMap((r) => series.map((s) => r.values[s.key] ?? 0)))));
  const y = (v: number) => M.t + (h - M.t - M.b) * (1 - v / max);

  const lines = series.map((s) => {
    let d = "";
    let pen = false;
    rows.forEach((r, i) => {
      const v = r.values[s.key];
      if (v === null || v === undefined) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return { s, d };
  });

  const areas = mode === "stack" ? series.map((s, k) => {
    const top = rows.map((r) => series.slice(0, k + 1).reduce((a, q) => a + (r.values[q.key] ?? 0), 0));
    const bottom = rows.map((r) => series.slice(0, k).reduce((a, q) => a + (r.values[q.key] ?? 0), 0));
    const edge = top.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const down = bottom.map((_, i) => `L${x(n - 1 - i).toFixed(1)},${y(bottom[n - 1 - i]).toFixed(1)}`).join("");
    return { s, d: `${edge}${down}Z`, edge };
  }) : [];

  function move(e: React.PointerEvent<SVGRectElement>) {
    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - box.left;
    const i = n <= 1 ? 0 : Math.round(((px - M.l) / (w - M.l - M.r)) * (n - 1));
    setHover(Math.min(n - 1, Math.max(0, i)));
  }
  function key(e: React.KeyboardEvent) {
    if (e.key === "ArrowRight") setHover((v) => Math.min(n - 1, (v ?? -1) + 1));
    if (e.key === "ArrowLeft") setHover((v) => Math.max(0, (v ?? n) - 1));
    if (e.key === "Escape") setHover(null);
  }

  return (
    <div className="viz" ref={ref}>
      {w > 0 && n > 0 && (
        <svg width={w} height={h} role="img" aria-label={label} tabIndex={0} onKeyDown={key} onBlur={() => setHover(null)}>
          <YAxis max={max} h={h} w={w} />
          {areas.map(({ s, d }) => <path key={s.key} d={d} fill={s.color} />)}
          {areas.map(({ s, edge }) => <path key={`e${s.key}`} d={edge} fill="none" stroke="var(--surface)" strokeWidth={1.5} />)}
          {mode === "line" && lines.map(({ s, d }) => (
            <path key={s.key} d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                  strokeDasharray={s.dashed ? "5 4" : undefined} />
          ))}
          <XLabels rows={rows} x={x} h={h} w={w} />
          {hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={h - M.b} className="viz-hair" />
              {mode === "line" && series.map((s) => {
                const v = rows[hover].values[s.key];
                return v === null || v === undefined ? null
                  : <circle key={s.key} cx={x(hover)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />;
              })}
            </g>
          )}
          <rect x={M.l} y={M.t} width={Math.max(0, w - M.l - M.r)} height={h - M.t - M.b} fill="transparent"
                onPointerMove={move} onPointerLeave={() => setHover(null)} />
        </svg>
      )}
      {hover !== null && rows[hover] && (
        <Tooltip x={x(hover)} width={w} title={rows[hover].tip}
                 items={[...series].reverse().map((s) => ({ s, v: rows[hover].values[s.key] ?? null }))} />
      )}
    </div>
  );
}

/** Grouped vertical bars, one group per row; hovering a group shows its values. */
export function BarChart({ rows, series, height = 200, label }: { rows: Row[]; series: Series[]; height?: number; label: string }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const h = height;
  const n = rows.length;
  const max = niceMax(Math.max(1, ...rows.flatMap((r) => series.map((s) => r.values[s.key] ?? 0))));
  const y = (v: number) => M.t + (h - M.t - M.b) * (1 - v / max);
  const band = n ? (w - M.l - M.r) / n : 0;
  const barW = Math.max(2, Math.min(18, (band * 0.7 - 2 * (series.length - 1)) / series.length));
  const groupW = barW * series.length + 2 * (series.length - 1);
  const cx = (i: number) => M.l + band * i + band / 2;
  const bar = (x0: number, v: number) => {
    const top = y(v);
    const base = y(0);
    const r = Math.min(4, barW / 2, base - top);
    if (base - top < 0.5) return "";
    return `M${x0},${base}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + barW - r}Q${x0 + barW},${top} ${x0 + barW},${top + r}V${base}Z`;
  };
  return (
    <div className="viz" ref={ref}>
      {w > 0 && (
        <svg width={w} height={h} role="img" aria-label={label} tabIndex={0}
             onKeyDown={(e) => {
               if (e.key === "ArrowRight") setHover((v) => Math.min(n - 1, (v ?? -1) + 1));
               if (e.key === "ArrowLeft") setHover((v) => Math.max(0, (v ?? n) - 1));
             }} onBlur={() => setHover(null)}>
          <YAxis max={max} h={h} w={w} />
          {rows.map((r, i) => (
            <g key={i} opacity={hover === null || hover === i ? 1 : 0.45}>
              {series.map((s, k) => (
                <path key={s.key} d={bar(cx(i) - groupW / 2 + k * (barW + 2), r.values[s.key] ?? 0)} fill={s.color} />
              ))}
              <rect x={M.l + band * i} y={M.t} width={band} height={h - M.t - M.b} fill="transparent"
                    onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)} />
            </g>
          ))}
          <XLabels rows={rows} x={cx} h={h} w={w} />
        </svg>
      )}
      {hover !== null && rows[hover] && (
        <Tooltip x={cx(hover)} width={w} title={rows[hover].tip} items={series.map((s) => ({ s, v: rows[hover].values[s.key] ?? null }))} />
      )}
    </div>
  );
}

/** Horizontal stacked bars with the label on the left and the numbers on the right. */
export function HBars({ rows, series, label }: { rows: { label: string; values: Record<string, number> }[]; series: Series[]; label: string }) {
  const max = Math.max(1, ...rows.map((r) => series.reduce((a, s) => a + (r.values[s.key] ?? 0), 0)));
  return (
    <div className="hbars" role="table" aria-label={label}>
      {rows.map((r) => {
        const total = series.reduce((a, s) => a + (r.values[s.key] ?? 0), 0);
        return (
          <div className="hbar" role="row" key={r.label}>
            <span className="hbar-label" role="rowheader" title={r.label}>{r.label}</span>
            <span className="hbar-track" role="cell">
              {series.map((s) => {
                const v = r.values[s.key] ?? 0;
                return v > 0 ? <i key={s.key} title={`${s.name}: ${v}`} style={{ width: `${(100 * v) / max}%`, background: s.color }} /> : null;
              })}
            </span>
            <span className="hbar-num num" role="cell">{series.length > 1 ? series.map((s) => r.values[s.key] ?? 0).join(" / ") : total}</span>
          </div>
        );
      })}
    </div>
  );
}

/** A chart with its title, legend and a switch to a plain table of the same numbers. */
export function ChartCard({ title, hint, series, rows, children, wide }: {
  title: string; hint?: string; series: Series[]; rows: Row[] | null; children: React.ReactNode; wide?: boolean;
}) {
  const { t } = useT();
  const [table, setTable] = useState(false);
  return (
    <section className={`chart-card${wide ? " wide" : ""}`}>
      <div className="chart-head">
        <h3>{title}</h3>
        {rows && <button className="btn ghost sm" onClick={() => setTable(!table)}>{table ? t("chart.chart") : t("chart.table")}</button>}
      </div>
      {hint && <p className="hint" style={{ margin: "-6px 0 8px" }}>{hint}</p>}
      <Legend series={series} />
      {table && rows ? (
        <div className="viz-table-wrap">
          <table className="viz-table">
            <thead><tr><th />{series.map((s) => <th key={s.key}>{s.name}</th>)}</tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}><th>{r.tip}</th>{series.map((s) => <td key={s.key} className="num">{fmt(r.values[s.key] ?? null)}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>
      ) : children}
    </section>
  );
}

/** Thin progress bar split by status: done, in progress, the rest. */
export function ProgressBar({ p }: { p: Progress }) {
  const scope = p.scope || 0;
  const part = (c: Category) => (scope ? (100 * (p.by_category?.[c] ?? 0)) / scope : 0);
  return (
    <span className="pbar" aria-hidden="true">
      <i style={{ width: `${part("done")}%`, background: "var(--c-done)" }} />
      <i style={{ width: `${part("in_progress")}%`, background: "var(--c-in_progress)" }} />
    </span>
  );
}

export function Stat({ value, label, sub }: { value: string; label: string; sub?: string }) {
  return (
    <div className="stat">
      <div className="stat-value num">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="hint">{sub}</div>}
    </div>
  );
}

/** Formats an ISO date as a short day label in the UI language. */
export function useDayLabel() {
  const { lang } = useT();
  const [f, setF] = useState(() => new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", timeZone: "UTC" }));
  useEffect(() => setF(new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", timeZone: "UTC" })), [lang]);
  return (iso: string) => f.format(new Date(`${iso}T00:00:00Z`));
}
