import { MouseEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, Page, PageBrief } from "../api";
import { Markdown, Modal, timeAgo } from "../components/bits";
import { useT } from "../i18n";
import type { ProjectData } from "./ProjectView";

type Tree = Map<string | null, PageBrief[]>;

function buildTree(pages: PageBrief[]): Tree {
  const ids = new Set(pages.map((p) => p.id));
  const tree: Tree = new Map();
  for (const p of pages) {
    const parent = p.parent_id && ids.has(p.parent_id) ? p.parent_id : null;
    tree.set(parent, [...(tree.get(parent) ?? []), p]);
  }
  for (const list of tree.values()) list.sort((a, b) => a.position - b.position || a.title.localeCompare(b.title));
  return tree;
}

function ancestors(pages: PageBrief[], id: string | undefined): string[] {
  const byId = new Map(pages.map((p) => [p.id, p]));
  const out: string[] = [];
  let cur = id ? byId.get(id) : undefined;
  while (cur?.parent_id && byId.has(cur.parent_id) && !out.includes(cur.parent_id)) {
    out.push(cur.parent_id);
    cur = byId.get(cur.parent_id);
  }
  return out;
}

function subtree(tree: Tree, id: string): Set<string> {
  const out = new Set([id]);
  const walk = (pid: string) => (tree.get(pid) ?? []).forEach((c) => { out.add(c.id); walk(c.id); });
  walk(id);
  return out;
}

function TreeNodes({ tree, parent, base, active, open, toggle, depth }: {
  tree: Tree; parent: string | null; base: string; active?: string; open: Set<string>; toggle: (id: string) => void; depth: number;
}) {
  const { t } = useT();
  const items = tree.get(parent) ?? [];
  if (!items.length) return null;
  return (
    <ul role={depth ? "group" : "tree"} aria-label={depth ? undefined : t("docs.tree")}>
      {items.map((p) => {
        const kids = (tree.get(p.id) ?? []).length > 0;
        const expanded = open.has(p.id);
        return (
          <li key={p.id} role="treeitem" aria-expanded={kids ? expanded : undefined} aria-selected={p.id === active}>
            <div className={`doc-node${p.id === active ? " active" : ""}`} style={{ paddingLeft: 4 + depth * 14 }}>
              {kids
                ? <button className="twisty" onClick={() => toggle(p.id)} aria-label={expanded ? t("docs.collapse") : t("docs.expand")}>
                    {expanded ? "▾" : "▸"}</button>
                : <span className="twisty" />}
              <Link to={`${base}/${p.id}`}>{p.title}</Link>
            </div>
            {kids && expanded && <TreeNodes tree={tree} parent={p.id} base={base} active={active} open={open} toggle={toggle} depth={depth + 1} />}
          </li>
        );
      })}
    </ul>
  );
}

function ParentSelect({ tree, value, exclude, onChange }: {
  tree: Tree; value: string | null; exclude?: string; onChange: (v: string | null) => void;
}) {
  const { t } = useT();
  const banned = exclude ? subtree(tree, exclude) : new Set<string>();
  const rows: { p: PageBrief; depth: number }[] = [];
  const walk = (pid: string | null, depth: number) => (tree.get(pid) ?? []).forEach((p) => {
    if (banned.has(p.id)) return;
    rows.push({ p, depth });
    walk(p.id, depth + 1);
  });
  walk(null, 0);
  return (
    <label className="field"><span>{t("docs.parent")}</span>
      <select className="select" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">{t("docs.root")}</option>
        {rows.map(({ p, depth }) => <option key={p.id} value={p.id}>{"  ".repeat(depth) + p.title}</option>)}
      </select>
    </label>
  );
}

function Editor({ projectKey, page, parentId, tree, onSaved, onCancel }: {
  projectKey: string; page: Page | null; parentId: string | null; tree: Tree;
  onSaved: (p: Page) => void; onCancel: () => void;
}) {
  const { t } = useT();
  const [title, setTitle] = useState(page?.title ?? "");
  const [body, setBody] = useState(page?.body ?? "");
  const [parent, setParent] = useState<string | null>(page ? page.parent_id : parentId);
  const [preview, setPreview] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError("");
    try {
      const saved = page
        ? await api.patchPage(projectKey, page.id, { title: title.trim(), body, ...(parent !== page.parent_id ? { parent_id: parent } : {}) })
        : await api.addPage(projectKey, { title: title.trim(), body, parent_id: parent });
      onSaved(saved);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("err.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="doc-edit">
      {error && <div className="banner" role="alert">{error}</div>}
      <label className="field"><span>{t("docs.title")}</span>
        <input className="input doc-title-input" autoFocus value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} /></label>
      <ParentSelect tree={tree} value={parent} exclude={page?.id} onChange={setParent} />
      <div className="field">
        <div className="doc-edit-head">
          <span>{t("docs.body")}</span>
          <div className="seg" role="group" aria-label={t("docs.body")}>
            <button className={preview ? "" : "on"} onClick={() => setPreview(false)}>{t("docs.write")}</button>
            <button className={preview ? "on" : ""} onClick={() => setPreview(true)}>{t("docs.preview")}</button>
          </div>
        </div>
        {preview
          ? <div className="doc-preview">{body.trim() ? <Markdown text={body} /> : <span className="hint">{t("docs.emptyBody")}</span>}</div>
          : <textarea className="textarea doc-text" value={body} aria-label={t("docs.body")} placeholder={t("docs.mdHint")}
                      onChange={(e) => setBody(e.target.value)} />}
      </div>
      <div className="doc-actions">
        <button className="btn primary" disabled={busy || !title.trim()} onClick={save}>{t("docs.save")}</button>
        <button className="btn" onClick={onCancel}>{t("docs.cancel")}</button>
      </div>
    </div>
  );
}

function PageView({ data, pages, tree, reload }: {
  data: ProjectData; pages: PageBrief[]; tree: Tree; reload: () => Promise<void>;
}) {
  const { t, lang } = useT();
  const { pageId = "", mode } = useParams();
  const nav = useNavigate();
  const key = data.project.key;
  const base = `/p/${key}/docs`;
  const [page, setPage] = useState<Page | null>(null);
  const [missing, setMissing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const canEdit = data.can("docs.edit");

  useEffect(() => {
    setMissing(false);
    api.page(key, pageId).then(setPage).catch(() => { setPage(null); setMissing(true); });
  }, [key, pageId]);

  // links between pages are plain hrefs in Markdown: keep them inside the app
  const follow = useCallback((e: MouseEvent<HTMLDivElement>) => {
    const a = (e.target as HTMLElement).closest("a");
    const href = a?.getAttribute("href");
    if (href?.startsWith("/") && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      nav(href);
    }
  }, [nav]);

  if (missing) return <div className="empty"><h2>{t("docs.notFound")}</h2></div>;
  if (!page || page.id !== pageId) return null;
  const trail = ancestors(pages, page.id).reverse().map((id) => pages.find((p) => p.id === id)!);
  const kids = tree.get(page.id) ?? [];

  if (mode === "edit" && canEdit) {
    return <Editor projectKey={key} page={page} parentId={page.parent_id} tree={tree} onCancel={() => nav(`${base}/${page.id}`)}
                   onSaved={async (p) => { setPage(p); await reload(); nav(`${base}/${p.id}`); }} />;
  }
  return (
    <article className="doc-page">
      {trail.length > 0 && (
        <nav className="crumbs" aria-label={t("docs.trail")}>
          {trail.map((p) => <span key={p.id}><Link to={`${base}/${p.id}`}>{p.title}</Link> / </span>)}
        </nav>
      )}
      <div className="doc-head">
        <h2>{page.title}</h2>
        {canEdit && (
          <div className="doc-actions">
            <button className="btn sm" onClick={() => nav(`${base}/${page.id}/edit`)}>{t("docs.edit")}</button>
            <button className="btn sm" onClick={() => nav(`${base}/new?parent=${page.id}`)}>+ {t("docs.subpage")}</button>
            <button className="btn sm ghost danger" onClick={() => setConfirm(true)}>{t("docs.delete")}</button>
          </div>
        )}
      </div>
      <div className="hint">{t("docs.updated", { when: timeAgo(page.updated_at, lang), who: page.updated_by?.display_name ?? "—" })}</div>
      <div className="doc-body" onClick={follow}>
        {page.body.trim() ? <Markdown text={page.body} /> : <p className="hint">{t("docs.emptyBody")}</p>}
      </div>
      {kids.length > 0 && (
        <section className="doc-kids">
          <h3>{t("docs.children")}</h3>
          <ul>{kids.map((k) => <li key={k.id}><Link to={`${base}/${k.id}`}>{k.title}</Link></li>)}</ul>
        </section>
      )}
      {confirm && (
        <Modal title={t("docs.delete")} onClose={() => setConfirm(false)} footer={<>
          <button className="btn" onClick={() => setConfirm(false)}>{t("docs.cancel")}</button>
          <button className="btn primary" onClick={async () => {
            await api.deletePage(key, page.id);
            setConfirm(false);
            await reload();
            nav(page.parent_id ? `${base}/${page.parent_id}` : base);
          }}>{t("docs.delete")}</button>
        </>}>
          <p style={{ margin: 0 }}>{t(subtree(tree, page.id).size > 1 ? "docs.deleteTree" : "docs.deleteOne", { title: page.title, n: subtree(tree, page.id).size - 1 })}</p>
        </Modal>
      )}
    </article>
  );
}

function NewPage({ data, tree, reload }: { data: ProjectData; tree: Tree; reload: () => Promise<void> }) {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const parent = params.get("parent");
  const base = `/p/${data.project.key}/docs`;
  return <Editor projectKey={data.project.key} page={null} parentId={parent} tree={tree}
                 onCancel={() => nav(parent ? `${base}/${parent}` : base)}
                 onSaved={async (p) => { await reload(); nav(`${base}/${p.id}`); }} />;
}

function Start({ data, tree }: { data: ProjectData; tree: Tree }) {
  const { t } = useT();
  const first = (tree.get(null) ?? [])[0];
  const nav = useNavigate();
  useEffect(() => { if (first) nav(`/p/${data.project.key}/docs/${first.id}`, { replace: true }); }, [first, nav, data.project.key]);
  if (first) return null;
  return (
    <div className="empty">
      <h2>{t("docs.none")}</h2>
      <p>{t("docs.noneSub")}</p>
      {data.can("docs.edit") && <Link className="btn primary" to={`/p/${data.project.key}/docs/new`}>{t("docs.first")}</Link>}
    </div>
  );
}

export default function Docs({ data }: { data: ProjectData }) {
  const { t } = useT();
  const key = data.project.key;
  const [pages, setPages] = useState<PageBrief[] | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const params = useParams();
  const active = (params["*"] ?? "").split("/")[0] || undefined;
  const reload = useCallback(async () => setPages(await api.pages(key)), [key]);
  useEffect(() => { setPages(null); reload().catch(() => setPages([])); }, [reload]);
  const tree = useMemo(() => buildTree(pages ?? []), [pages]);

  // the path to the open page is always unfolded
  useEffect(() => {
    if (!pages || !active) return;
    const up = ancestors(pages, active);
    if (up.some((id) => !open.has(id))) setOpen((o) => new Set([...o, ...up]));
  }, [pages, active, open]);

  if (!pages) return null;
  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const base = `/p/${key}/docs`;
  const found = q.trim() ? pages.filter((p) => p.title.toLowerCase().includes(q.trim().toLowerCase())) : null;

  return (
    <div className="page docs">
      <aside className="doc-tree">
        <div className="doc-tree-head">
          <input className="input" type="search" placeholder={t("docs.search")} aria-label={t("docs.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          {data.can("docs.edit") && <Link className="btn sm" to={`${base}/new`} title={t("docs.new")} aria-label={t("docs.new")}>+</Link>}
        </div>
        {found
          ? <ul className="doc-found">{found.map((p) => <li key={p.id}><Link className={p.id === active ? "active" : ""} to={`${base}/${p.id}`}>{p.title}</Link></li>)}
              {found.length === 0 && <li className="hint">{t("docs.nothing")}</li>}</ul>
          : <TreeNodes tree={tree} parent={null} base={base} active={active} open={open} toggle={toggle} depth={0} />}
      </aside>
      <div className="doc-main">
        <Routes>
          <Route index element={<Start data={data} tree={tree} />} />
          <Route path="new" element={data.can("docs.edit") ? <NewPage data={data} tree={tree} reload={reload} /> : null} />
          <Route path=":pageId" element={<PageView data={data} pages={pages} tree={tree} reload={reload} />} />
          <Route path=":pageId/:mode" element={<PageView data={data} pages={pages} tree={tree} reload={reload} />} />
        </Routes>
      </div>
    </div>
  );
}
