import DOMPurify from "dompurify";
import { marked } from "marked";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type { Category, Priority, UserBrief } from "../api";
import { useT } from "../i18n";

const AVATAR_COLORS = ["#3a47d5", "#2e8b57", "#b4531f", "#7b3fb5", "#0f7f8c", "#a8326b", "#5b6472", "#8a6d00"];

export function initials(name: string) {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function colorFor(id: string) {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

export function Avatar({ user, large }: { user: UserBrief; large?: boolean }) {
  return (
    <span className={`avatar${large ? " lg" : ""}`} style={{ background: colorFor(user.id) }} title={user.display_name}>
      {initials(user.display_name)}
    </span>
  );
}

export function Avatars({ users, max = 3 }: { users: UserBrief[]; max?: number }) {
  if (!users.length) return null;
  return (
    <span className="avatars">
      {users.slice(0, max).map((u) => <Avatar key={u.id} user={u} />)}
      {users.length > max && <span className="avatar" style={{ background: "var(--muted)" }}>+{users.length - max}</span>}
    </span>
  );
}

export function StateDot({ category }: { category: Category }) {
  return <span className={`dot ${category}`} style={{ color: `var(--c-${category})` }} aria-hidden="true" />;
}

const LEVEL: Record<Priority, number> = { none: 0, low: 1, medium: 2, high: 3, urgent: 4 };

export function PriorityIcon({ priority }: { priority: Priority }) {
  const { t } = useT();
  const label = t(`priority.${priority}`);
  if (priority === "urgent") return <span className="prio urgent-mark" title={label} aria-label={label}>!</span>;
  const n = LEVEL[priority];
  return (
    <span className="prio" title={label} aria-label={label}>
      {[1, 2, 3].map((i) => (
        <i key={i} style={i <= n ? { background: `var(--p-${priority})` } : undefined} />
      ))}
    </span>
  );
}

export function isOverdue(due: string | null, category: Category) {
  if (!due || category === "done" || category === "cancelled") return false;
  return due < new Date().toISOString().slice(0, 10);
}

export function DueDate({ due, category }: { due: string | null; category: Category }) {
  const { lang } = useT();
  if (!due) return null;
  const d = new Date(due + "T00:00:00");
  const txt = d.toLocaleDateString(lang === "ru" ? "ru-RU" : "en-GB", { day: "numeric", month: "short" });
  return <span className={`due${isOverdue(due, category) ? " over" : ""}`}>{txt}</span>;
}

export function timeAgo(iso: string, lang: string) {
  const sec = (Date.now() - new Date(iso).getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  if (sec < 60) return rtf.format(0, "second");
  if (sec < 3600) return rtf.format(-Math.round(sec / 60), "minute");
  if (sec < 86400) return rtf.format(-Math.round(sec / 3600), "hour");
  if (sec < 86400 * 30) return rtf.format(-Math.round(sec / 86400), "day");
  return new Date(iso).toLocaleDateString(lang);
}

export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false, breaks: true, gfm: true }) as string), [text]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}

export function useOutside(ref: React.RefObject<HTMLElement>, onOutside: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside();
    };
    const k = (e: KeyboardEvent) => e.key === "Escape" && onOutside();
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => {
      document.removeEventListener("mousedown", h);
      document.removeEventListener("keydown", k);
    };
  }, [ref, onOutside, active]);
}

export function Modal({ title, children, onClose, footer }: {
  title: string; children: ReactNode; onClose: () => void; footer?: ReactNode;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-wrap" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <header>{title}</header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export function MultiPicker<T extends { id: string }>({
  items, selected, onChange, render, renderSelected, placeholder, disabled, searchable,
}: {
  items: T[]; selected: string[]; onChange: (ids: string[]) => void; render: (item: T) => ReactNode;
  renderSelected?: (items: T[]) => ReactNode; placeholder: string; disabled?: boolean; searchable?: (item: T) => string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, () => setOpen(false), open);
  const sel = items.filter((i) => selected.includes(i.id));
  const shown = searchable && q ? items.filter((i) => searchable(i).toLowerCase().includes(q.toLowerCase())) : items;
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <div className="picker" ref={ref}>
      <button type="button" className="picker-btn" disabled={disabled} onClick={() => setOpen((o) => !o)}>
        {sel.length ? (renderSelected ? renderSelected(sel) : sel.map((s) => <span key={s.id}>{render(s)}</span>))
          : <span style={{ color: "var(--muted)" }}>{placeholder}</span>}
      </button>
      {open && (
        <div className="pop">
          {searchable && <input className="input" autoFocus value={q} onChange={(e) => setQ(e.target.value)} />}
          {shown.map((i) => (
            <button type="button" key={i.id} className="opt" onClick={() => toggle(i.id)}>
              {render(i)}
              {selected.includes(i.id) && <span className="tick">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Toast({ text, onDone }: { text: string; onDone: () => void }) {
  useEffect(() => {
    const id = setTimeout(onDone, 1800);
    return () => clearTimeout(id);
  }, [onDone]);
  return <div className="toast" role="status">{text}</div>;
}

export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--ink)" />
      <path d="M16 5 L21 16 L16 27 L11 16 Z" fill="var(--bg)" />
      <path d="M16 5 L21 16 L11 16 Z" fill="var(--accent)" />
    </svg>
  );
}
