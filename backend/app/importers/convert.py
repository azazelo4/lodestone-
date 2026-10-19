"""Converting Jira ADF, Jira wiki markup and HTML (Plane, Confluence storage format) to Markdown.

The goal is readable Markdown, not a lossless copy: unknown macros keep their text, images become placeholders
(attachments are not downloaded). Links to other Confluence pages become "page:<title>" and are rewritten to
local pages once every page of the space exists.
"""
import re
from html.parser import HTMLParser

PAGE_LINK = "page:"


def _esc_cell(s: str) -> str:
    return " ".join(s.replace("|", "\\|").split())


def _table(rows: list[tuple[list[str], bool]]) -> str:
    if not rows:
        return ""
    width = max(len(cells) for cells, _ in rows)
    rows = [(cells + [""] * (width - len(cells)), head) for cells, head in rows]
    if not rows[0][1]:  # Markdown tables need a header row
        rows.insert(0, ([""] * width, True))
    out = ["| " + " | ".join(_esc_cell(c) for c in rows[0][0]) + " |", "|" + " --- |" * width]
    out += ["| " + " | ".join(_esc_cell(c) for c in cells) + " |" for cells, _ in rows[1:]]
    return "\n".join(out)


def _fence(code: str, lang: str = "") -> str:
    ticks = "```"
    while ticks in code:
        ticks += "`"
    return f"{ticks}{lang}\n{code.strip(chr(10))}\n{ticks}"


def _indent(text: str, prefix: str, first: str) -> str:
    lines = text.split("\n")
    return "\n".join([first + lines[0]] + [(prefix + ln) if ln else prefix.rstrip() for ln in lines[1:]])


def _tidy(md: str) -> str:
    md = re.sub(r"[ \t]+\n", "\n", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


# ---------- Atlassian Document Format (Jira Cloud REST API v3)
def adf_to_md(doc) -> str:
    if not doc:
        return ""
    if isinstance(doc, str):
        return doc
    return _tidy(_adf_blocks(doc.get("content", [])))


def _adf_blocks(nodes: list) -> str:
    return "\n\n".join(b for b in (_adf_block(n) for n in nodes) if b)


def _adf_inline(nodes: list) -> str:
    out = []
    for n in nodes or []:
        t = n.get("type")
        a = n.get("attrs", {})
        if t == "text":
            s = n.get("text", "")
            for m in n.get("marks", []):
                mt = m.get("type")
                if mt == "code":
                    s = f"`{s}`"
                elif mt == "strong":
                    s = f"**{s}**"
                elif mt == "em":
                    s = f"*{s}*"
                elif mt == "strike":
                    s = f"~~{s}~~"
                elif mt == "link":
                    s = f"[{s}]({m.get('attrs', {}).get('href', '')})"
            out.append(s)
        elif t == "hardBreak":
            out.append("  \n")
        elif t == "mention":
            out.append("@" + (a.get("text") or "").lstrip("@"))
        elif t == "emoji":
            out.append(a.get("text") or a.get("shortName", ""))
        elif t in ("inlineCard", "blockCard"):
            out.append(f"<{a.get('url', '')}>")
        elif t == "date":
            out.append(str(a.get("timestamp", "")))
        elif t == "status":
            out.append(f"`{a.get('text', '')}`")
        elif "content" in n:
            out.append(_adf_inline(n["content"]))
    return "".join(out)


def _adf_list(n: dict, ordered: bool) -> str:
    items = []
    for i, li in enumerate(n.get("content", []), 1):
        mark = f"{i}. " if ordered else "- "
        items.append(_indent(_adf_blocks(li.get("content", [])).replace("\n\n", "\n"), " " * len(mark), mark))
    return "\n".join(items)


def _adf_block(n: dict) -> str:
    t = n.get("type")
    a = n.get("attrs", {})
    c = n.get("content", [])
    if t == "paragraph":
        return _adf_inline(c)
    if t == "heading":
        return "#" * min(int(a.get("level", 1)), 6) + " " + _adf_inline(c)
    if t == "bulletList":
        return _adf_list(n, False)
    if t == "orderedList":
        return _adf_list(n, True)
    if t == "taskList":
        return "\n".join(("- [x] " if i.get("attrs", {}).get("state") == "DONE" else "- [ ] ") + _adf_inline(
            i.get("content", [])) for i in c)
    if t == "codeBlock":
        return _fence("".join(x.get("text", "") for x in c), a.get("language") or "")
    if t in ("blockquote", "panel"):
        return _indent(_adf_blocks(c), "> ", "> ")
    if t == "rule":
        return "---"
    if t == "table":
        rows = []
        for r in c:
            cells = r.get("content", [])
            rows.append(([_adf_blocks(x.get("content", [])).replace("\n", " ") for x in cells],
                         bool(cells) and all(x.get("type") == "tableHeader" for x in cells)))
        return _table(rows)
    if t in ("mediaSingle", "mediaGroup", "media"):
        names = [m.get("attrs", {}).get("alt") or m.get("attrs", {}).get("id", "") for m in (c or [n])]
        return " ".join(f"*[image: {x}]*" for x in names if x) or "*[image]*"
    if t in ("expand", "nestedExpand"):
        title = a.get("title")
        return (f"**{title}**\n\n" if title else "") + _adf_blocks(c)
    if c:
        return _adf_blocks(c) if any("content" in x or x.get("type") != "text" for x in c) else _adf_inline(c)
    return ""


# ---------- Jira wiki markup (Jira Server / Data Center, REST API v2)
_WIKI_INLINE = [
    (re.compile(r"\{\{(.+?)\}\}"), r"`\1`"),
    (re.compile(r"\[~([^\]]+)\]"), r"@\1"),
    (re.compile(r"\[([^|\]\n]+)\|([^\]\n]+)\]"), r"[\1](\2)"),
    (re.compile(r"\[((?:https?|mailto):[^\]\n]+)\]"), r"<\1>"),
    (re.compile(r"\{color(?::[^}]*)?\}"), ""),
    (re.compile(r"(?<![\w*])\*(\S(?:.*?\S)?)\*(?![\w*])"), r"**\1**"),
    (re.compile(r"(?<![\w_])_(\S(?:.*?\S)?)_(?![\w_])"), r"*\1*"),
    (re.compile(r"(?<![\w-])-(\S(?:.*?\S)?)-(?![\w-])"), r"~~\1~~"),
    (re.compile(r"!([^!\s|]+)(?:\|[^!]*)?!"), r"*[image: \1]*"),
]


def _wiki_inline(s: str) -> str:
    # code spans first, kept out of the other rules
    parts = re.split(r"(\{\{.+?\}\})", s)
    out = []
    for p in parts:
        if p.startswith("{{") and p.endswith("}}"):
            out.append(f"`{p[2:-2]}`")
            continue
        for rx, rep in _WIKI_INLINE[1:]:
            p = rx.sub(rep, p)
        out.append(p)
    return "".join(out)


def wiki_to_md(src: str | None) -> str:
    if not src:
        return ""
    lines = src.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^\s*\{(code|noformat)(?::([^}]*))?\}(.*)$", ln)
        if m:
            lang = ""
            if m.group(2):
                opts = m.group(2).split("|")
                lang = next((o for o in opts if "=" not in o), "")
                lang = lang or next((o.split("=", 1)[1] for o in opts if o.startswith("language=")), "")
            body, rest = [], m.group(3)
            close = "{" + m.group(1) + "}"
            while True:
                if close in rest:
                    body.append(rest.split(close, 1)[0])
                    break
                body.append(rest)
                i += 1
                if i >= len(lines):
                    break
                rest = lines[i]
            out += ["", _fence("\n".join(body), lang.strip()), ""]
            i += 1
            continue
        if ln.strip().startswith("{quote}"):
            body = []
            rest = ln.strip()[7:]
            while "{quote}" not in rest and i + 1 < len(lines):
                body.append(rest)
                i += 1
                rest = lines[i]
            body.append(rest.split("{quote}", 1)[0])
            out += ["", "\n".join("> " + _wiki_inline(b) for b in body if b.strip()), ""]
            i += 1
            continue
        if ln.startswith("||") or (ln.startswith("|") and ln.rstrip().endswith("|")):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                row = lines[i].strip()
                head = row.startswith("||")
                cells = [c.strip() for c in re.split(r"\|\|?", row.strip("|"))]
                rows.append(([_wiki_inline(c) for c in cells], head))
                i += 1
            out += ["", _table(rows), ""]
            continue
        h = re.match(r"^h([1-6])\.\s*(.*)$", ln)
        lm = re.match(r"^([*#-]+)\s+(.*)$", ln)
        if h:
            out += ["", "#" * int(h.group(1)) + " " + _wiki_inline(h.group(2)), ""]
        elif ln.startswith("bq. "):
            out.append("> " + _wiki_inline(ln[4:]))
        elif lm and not (lm.group(1) == "-" * len(lm.group(1)) and len(lm.group(1)) > 1):
            marks = lm.group(1)
            bullet = "1. " if marks[-1] == "#" else "- "
            out.append("   " * (len(marks) - 1) + bullet + _wiki_inline(lm.group(2)))
        elif ln.strip() == "----":
            out.append("---")
        else:
            out.append(_wiki_inline(ln))
        i += 1
    return _tidy("\n".join(out))


# ---------- HTML / Confluence storage format
VOID = {"br", "hr", "img", "ri:page", "ri:attachment", "ri:url", "ri:user", "ac:parameter-void", "col", "input"}


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def find(self, tag: str):
        for c in self.children:
            if isinstance(c, _Node):
                if c.tag == tag:
                    return c
                f = c.find(tag)
                if f:
                    return f
        return None

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)

    def unknown_decl(self, data):
        if data.startswith("CDATA["):
            self.cur.children.append(_Raw(data[6:]))


class _Raw(str):
    """CDATA: text kept verbatim (code, plain-text link bodies)."""


BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "pre", "blockquote", "table", "hr",
         "ac:structured-macro", "ac:task-list", "section", "article", "li"}
CALLOUTS = {"info": "Info", "note": "Note", "warning": "Warning", "tip": "Tip", "panel": ""}


class _Md:
    def blocks(self, node: _Node) -> str:
        out, inline = [], []

        def flush():
            s = "".join(inline).strip()
            if s:
                out.append(s)
            inline.clear()

        for c in node.children:
            if isinstance(c, _Node) and (c.tag in BLOCK or c.tag == "ac:layout" or c.tag.startswith("ac:layout")):
                flush()
                b = self.block(c)
                if b:
                    out.append(b)
            else:
                inline.append(self.inline_one(c))
        flush()
        return "\n\n".join(out)

    def inline(self, node: _Node) -> str:
        return "".join(self.inline_one(c) for c in node.children)

    def inline_one(self, c) -> str:
        if isinstance(c, _Raw):
            return c
        if isinstance(c, str):
            return re.sub(r"\s+", " ", c)
        t = c.tag
        if t in ("strong", "b"):
            s = self.inline(c).strip()
            return f"**{s}**" if s else ""
        if t in ("em", "i"):
            s = self.inline(c).strip()
            return f"*{s}*" if s else ""
        if t in ("s", "del", "strike"):
            return f"~~{self.inline(c)}~~"
        if t == "code":
            return f"`{c.text()}`"
        if t == "br":
            return "  \n"
        if t == "a":
            href = c.attrs.get("href") or ""
            label = self.inline(c).strip() or href
            return f"[{label}]({href})" if href else label
        if t == "img":
            src = c.attrs.get("src", "")
            return f"![{c.attrs.get('alt', '')}]({src})" if src.startswith(("http://", "https://")) else "*[image]*"
        if t == "ac:link":
            return self.ac_link(c)
        if t == "ac:image":
            att = c.find("ri:attachment")
            url = c.find("ri:url")
            if url is not None and url.attrs.get("ri:value"):
                return f"![]({url.attrs['ri:value']})"
            return f"*[image: {att.attrs.get('ri:filename', '')}]*" if att is not None else "*[image]*"
        if t == "ri:user":
            return "@user"
        if t == "ac:emoticon":
            return c.attrs.get("ac:emoji-fallback", "")
        if t == "time":
            return c.attrs.get("datetime", "")
        if t in ("ac:parameter", "ac:placeholder"):
            return ""
        if t in BLOCK:
            return self.block(c)
        return self.inline(c)

    def ac_link(self, c: _Node) -> str:
        body = c.find("ac:plain-text-link-body") or c.find("ac:link-body")
        label = (body.text() if body is not None else "").strip()
        page = c.find("ri:page")
        if page is not None:
            title = page.attrs.get("ri:content-title", "")
            return f"[{label or title}]({PAGE_LINK}{_quote(title)})" if title else label
        att = c.find("ri:attachment")
        if att is not None:
            return f"*[{label or att.attrs.get('ri:filename', 'attachment')}]*"
        user = c.find("ri:user")
        if user is not None:
            return label or "@user"
        anchor = c.attrs.get("ac:anchor")
        return label or (f"#{anchor}" if anchor else "")

    def list(self, c: _Node, ordered: bool) -> str:
        items, n = [], 0
        for li in c.children:
            if not isinstance(li, _Node) or li.tag != "li":
                continue
            n += 1
            mark = f"{n}. " if ordered else "- "
            body = self.blocks(li).replace("\n\n", "\n")
            items.append(_indent(body, " " * len(mark), mark))
        return "\n".join(items)

    def macro(self, c: _Node) -> str:
        name = c.attrs.get("ac:name", "")
        params = {p.attrs.get("ac:name", ""): p.text() for p in c.children
                  if isinstance(p, _Node) and p.tag == "ac:parameter"}
        plain = c.find("ac:plain-text-body")
        rich = c.find("ac:rich-text-body")
        if name in ("code", "noformat") or (plain is not None and rich is None):
            return _fence(plain.text() if plain is not None else "", params.get("language", ""))
        if name in CALLOUTS:
            label = params.get("title") or CALLOUTS[name]
            body = self.blocks(rich) if rich is not None else ""
            text = (f"**{label}**\n\n" if label else "") + body
            return _indent(text, "> ", "> ") if text else ""
        if name == "expand":
            body = self.blocks(rich) if rich is not None else ""
            return (f"**{params.get('title', '')}**\n\n" if params.get("title") else "") + body
        if name == "status":
            return f"`{params.get('title', '')}`"
        if rich is not None:
            return self.blocks(rich)
        return ""  # toc, children, jira issue lists... have no content of their own

    def table(self, c: _Node) -> str:
        rows = []

        def walk(n: _Node):
            for r in n.children:
                if not isinstance(r, _Node):
                    continue
                if r.tag == "tr":
                    cells = [x for x in r.children if isinstance(x, _Node) and x.tag in ("td", "th")]
                    rows.append(([self.blocks(x).replace("\n", " ") for x in cells],
                                 bool(cells) and all(x.tag == "th" for x in cells)))
                elif r.tag in ("thead", "tbody", "tfoot"):
                    walk(r)
        walk(c)
        return _table(rows)

    def block(self, c: _Node) -> str:
        t = c.tag
        if t in ("h1", "h2", "h3", "h4", "h5", "h6"):
            s = self.inline(c).strip()
            return "#" * int(t[1]) + " " + s if s else ""
        if t == "ul":
            return self.list(c, False)
        if t == "ol":
            return self.list(c, True)
        if t == "pre":
            return _fence(c.text())
        if t == "blockquote":
            s = self.blocks(c)
            return _indent(s, "> ", "> ") if s else ""
        if t == "hr":
            return "---"
        if t == "table":
            return self.table(c)
        if t == "ac:structured-macro":
            return self.macro(c)
        if t == "ac:task-list":
            out = []
            for task in c.children:
                if isinstance(task, _Node) and task.tag == "ac:task":
                    st = task.find("ac:task-status")
                    body = task.find("ac:task-body")
                    done = st is not None and st.text().strip() == "complete"
                    out.append(("- [x] " if done else "- [ ] ") + (self.inline(body).strip() if body else ""))
            return "\n".join(out)
        if t == "li":
            return "- " + self.blocks(c)
        return self.blocks(c)


def _quote(title: str) -> str:
    return title.replace("%", "%25").replace(" ", "%20").replace(")", "%29").replace("(", "%28")


def _unquote(s: str) -> str:
    return s.replace("%20", " ").replace("%29", ")").replace("%28", "(").replace("%25", "%")


def html_to_md(src: str | None) -> str:
    if not src:
        return ""
    tree = _Tree()
    tree.feed(src)
    tree.close()
    return _tidy(_Md().blocks(tree.root))


def resolve_page_links(md: str, url_of) -> str:
    """Rewrites [text](page:Title) using url_of(title) -> url or None (then only the text stays)."""
    def rep(m):
        url = url_of(_unquote(m.group(2)))
        return f"[{m.group(1)}]({url})" if url else m.group(1)
    return re.sub(r"\[([^\]]*)\]\(" + PAGE_LINK + r"([^)\s]*)\)", rep, md)
