from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import markdown

VAULT_ROOT = Path("docs/helix-brain")
THEORY_PATH = Path("docs/theory.html")
EXCLUDED_DIRS = {".obsidian", "_templates", "Helix"}
SECTION_ORDER = {
    "Project": 0,
    "Architecture": 1,
    "Evaluation": 2,
    "Journal": 3,
}
SECTION_TITLES = {
    "00-Project": "Project",
    "01-Architecture": "Architecture",
    "02-Evaluation": "Evaluation",
    "03-Journal": "Journal",
}
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
CALLOUT_RE = re.compile(r"^\s*>\s*\[!([A-Za-z0-9_-]+)\]\s*(.*)$")
INTERNAL_ANCHOR_RE = re.compile(r"\]\(#([^)]+)\)")


@dataclass(frozen=True)
class Note:
    path: Path
    relative_path: str
    slug: str
    section: str
    title: str
    meta: dict[str, str | list[str]]
    body: str


def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if end is None:
        return {}, text

    meta: dict[str, str | list[str]] = {}
    for line in "".join(lines[1:end]).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [
                _unquote(item.strip())
                for item in value[1:-1].split(",")
                if item.strip()
            ]
            meta[key] = items
        else:
            meta[key] = _unquote(value)

    return meta, "".join(lines[end + 1 :]).lstrip("\n")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def strip_inline_markdown(value: str) -> str:
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return value.strip()


def extract_title(body: str, fallback: str) -> tuple[str, str]:
    match = H1_RE.search(body)
    if match is None:
        return fallback, body
    title = strip_inline_markdown(match.group(1))
    return title, (body[: match.start()] + body[match.end() :]).lstrip("\n")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold())
    return slug.strip("-") or "section"


def section_for(relative_path: str) -> str:
    first = Path(relative_path).parts[0]
    return SECTION_TITLES.get(first, "Notes")


def collect_notes(vault: Path = VAULT_ROOT) -> list[Note]:
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault not found: {vault}")

    notes: list[Note] = []
    for path in sorted(vault.rglob("*.md")):
        relative = path.relative_to(vault)
        if any(
            part in EXCLUDED_DIRS or part.startswith(".") for part in relative.parts
        ):
            continue

        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        fallback = path.stem
        title, body = extract_title(body, fallback)
        meta_title = meta.get("title")
        if isinstance(meta_title, str) and meta_title.strip():
            title = meta_title.strip()

        relative_path = relative.as_posix()
        notes.append(
            Note(
                path=path,
                relative_path=relative_path,
                slug=slugify(relative.with_suffix("").as_posix()),
                section=section_for(relative_path),
                title=title,
                meta=meta,
                body=body,
            )
        )

    notes.sort(
        key=lambda note: (
            SECTION_ORDER.get(note.section, 99),
            note.relative_path,
        )
    )
    return notes


def build_index(notes: list[Note]) -> dict[str, Note]:
    index: dict[str, Note] = {}
    for note in notes:
        stem = Path(note.relative_path).stem
        for key in (
            note.relative_path.removesuffix(".md"),
            stem,
            note.title,
            note.slug,
        ):
            index.setdefault(key.casefold(), note)
    return index


def replace_wikilinks(
    text: str,
    index: dict[str, Note],
    page_slug: str,
) -> str:
    def replace(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        heading = (match.group(2) or "").strip()
        label = (match.group(3) or "").strip()
        note = index.get(target.casefold())

        if note is None:
            text_value = label or target
            return (
                '<span class="missing-link" '
                f'title="Missing note: {html.escape(target, quote=True)}">'
                f"{html.escape(text_value)}</span>"
            )

        href = f"#{note.slug}"
        if heading:
            href = f"{href}--{slugify(heading)}"
        text_value = label or heading or target
        return f'<a href="{href}">{html.escape(text_value)}</a>'

    output: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            output.append(line)
            continue
        if in_fence:
            output.append(line)
            continue
        segments = re.split(r"(`[^`]*`)", line)
        for index_value, segment in enumerate(segments):
            if index_value % 2 == 0:
                segments[index_value] = WIKILINK_RE.sub(replace, segment)
        output.append("".join(segments))
    return "".join(output)


def rewrite_internal_anchors(text: str, page_slug: str) -> str:
    return INTERNAL_ANCHOR_RE.sub(
        lambda match: f"](#{page_slug}--{slugify(match.group(1))})",
        text,
    )


def convert_callouts(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0

    while index < len(lines):
        match = CALLOUT_RE.match(lines[index])
        if match is None:
            output.append(lines[index])
            index += 1
            continue

        kind = match.group(1).casefold()
        title = match.group(2).strip() or kind.replace("-", " ").title()
        body: list[str] = []
        index += 1
        while index < len(lines) and lines[index].lstrip().startswith(">"):
            line = lines[index].lstrip()
            if line == ">":
                body.append("")
            elif line.startswith("> "):
                body.append(line[2:])
            else:
                body.append(line[1:])
            index += 1

        safe_title = re.sub(
            r"`([^`]+)`",
            r"<code>\1</code>",
            html.escape(title),
        )
        output.append(f'<div class="callout {kind}" markdown="1">')
        output.append(f'<p class="callout-title">{safe_title}</p>')
        output.append("")
        output.extend(body)
        output.append("")
        output.append("</div>")

    return "\n".join(output)


def make_slugify(page_slug: str) -> Callable[[str, str], str]:
    def slugify_for_page(value: str, _separator: str) -> str:
        return f"{page_slug}--{slugify(value)}"

    return slugify_for_page


def render_markdown(text: str, page_slug: str) -> tuple[str, list[dict[str, object]]]:
    prepared = rewrite_internal_anchors(text, page_slug)
    prepared = convert_callouts(prepared)
    converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "md_in_html", "sane_lists"],
        extension_configs={
            "toc": {
                "slugify": make_slugify(page_slug),
                "toc_depth": "2-3",
                "anchorlink": False,
            }
        },
    )
    body = converter.convert(prepared)
    tokens = getattr(converter, "toc_tokens", [])
    return body, tokens


def _meta_text(value: str | list[str] | None) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value).strip() if value is not None else ""


def _meta_list(value: str | list[str] | None) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def render_toc(tokens: list[dict[str, object]]) -> str:
    if not tokens:
        return ""

    def items(nodes: list[dict[str, object]]) -> str:
        parts: list[str] = []
        for node in nodes:
            identifier = str(node.get("id", ""))
            name = str(node.get("name", ""))
            children = node.get("children")
            child_html = items(children) if isinstance(children, list) else ""
            nested = f"<ul>{child_html}</ul>" if child_html else ""
            parts.append(
                f'<li><a href="#{identifier}">{html.escape(name)}</a>{nested}</li>'
            )
        return "".join(parts)

    return (
        '<div class="toc"><p class="toctitle">On this page</p>'
        f"<ul>{items(tokens)}</ul></div>"
    )


def render_note(note: Note, index: dict[str, Note]) -> str:
    linked_body = replace_wikilinks(note.body, index, note.slug)
    body_html, toc_tokens = render_markdown(linked_body, note.slug)

    note_type = _meta_text(note.meta.get("type"))
    status = _meta_text(note.meta.get("status"))
    kicker = " · ".join(part for part in (note.section, note_type, status) if part)
    tags = _meta_list(note.meta.get("tags"))
    chips = "".join(f'<span class="chip">{html.escape(tag)}</span>' for tag in tags)
    related = _meta_list(note.meta.get("related"))
    related_html = ""
    if related:
        related_items = " ".join(
            f'<span class="chip">{replace_wikilinks(item, index, note.slug)}</span>'
            for item in related
        )
        related_html = (
            '<div class="related"><strong>Related:</strong> '
            f"{related_items}</div>"
        )

    toc_html = render_toc(toc_tokens)
    return f"""<article class="note" id="{note.slug}"
data-title="{html.escape(note.title, quote=True)}">
<header class="note-header">
<p class="kicker">{html.escape(kicker)}</p>
<h2>{html.escape(note.title)}</h2>
{chips}
</header>
{toc_html}
<div class="content">
{body_html}
</div>
{related_html}
</article>"""


def render_html(notes: list[Note], title: str = "Helix Study Guide") -> str:
    if not notes:
        raise ValueError("No notes to render")

    index = build_index(notes)
    groups: dict[str, list[Note]] = {}
    for note in notes:
        groups.setdefault(note.section, []).append(note)

    nav_parts: list[str] = []
    for section, section_notes in groups.items():
        nav_parts.append('<div class="nav-group">')
        nav_parts.append(f"<h2>{html.escape(section)}</h2>")
        for note in section_notes:
            nav_parts.append(
                f'<a href="#{note.slug}" data-target="{note.slug}">'
                f"{html.escape(note.title)}</a>"
            )
        nav_parts.append("</div>")

    rendered_notes = "\n".join(render_note(note, index) for note in notes)
    stats = f"{len(notes)} notes · {len(groups)} sections"
    escaped_title = html.escape(title)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="helix docs">
<title>{escaped_title}</title>
<style>{STYLE}</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
<a class="brand" href="#top">Helix</a>
<p class="tagline">Permission-aware RAG</p>
<label class="visually-hidden" for="search">Search notes</label>
<input id="search" class="search" type="search"
  placeholder="Search notes... (press /)" autocomplete="off">
<nav class="nav" aria-label="Notes">
{''.join(nav_parts)}
</nav>
</aside>
<main id="top">
<header class="hero">
<p class="eyebrow">Helix · study guide</p>
<h1>{escaped_title}</h1>
<p>Generated from <code>docs/helix-brain</code>.
Edit the Markdown, then run <code>make docs</code>.</p>
<p class="stats">{stats}</p>
</header>
{rendered_notes}
<footer class="page-footer">
Source of truth: the Obsidian vault. This file is generated; do not edit it by hand.
</footer>
</main>
</div>
<script>{SCRIPT}</script>
</body>
</html>
"""


def write_theory(
    vault: Path = VAULT_ROOT,
    output: Path = THEORY_PATH,
    title: str = "Helix Study Guide",
) -> int:
    notes = collect_notes(vault)
    if not notes:
        raise ValueError(f"No notes found in {vault}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(notes, title=title), encoding="utf-8")
    return len(notes)


STYLE = """
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --sidebar: #fbfbfc;
  --fg: #1f2328;
  --muted: #5f6b7a;
  --border: #d8dee4;
  --accent: #4f46e5;
  --hover: #eef2ff;
  --input: #ffffff;
  --code: #f3f4f6;
  --table-head: #f6f8fa;
  --quote: #f8fafc;
  --callout: #f8fafc;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115;
    --surface: #151922;
    --sidebar: #11141a;
    --fg: #e6edf3;
    --muted: #9aa7b4;
    --border: #2a313c;
    --accent: #a5b4fc;
    --hover: #1e2530;
    --input: #0f1115;
    --code: #1b2029;
    --table-head: #1b2029;
    --quote: #161b23;
    --callout: #161b23;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.65;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.layout {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  max-width: 1440px;
  margin: 0 auto;
}
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  padding: 1.5rem 1.25rem;
  border-right: 1px solid var(--border);
  background: var(--sidebar);
}
.brand { font-size: 1.4rem; font-weight: 800; letter-spacing: -0.03em; color: var(--fg); }
.tagline { margin: 0.15rem 0 1.2rem; color: var(--muted); font-size: 0.85rem; }
.search {
  width: 100%;
  padding: 0.65rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--input);
  color: var(--fg);
  font: inherit;
}
.search:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.nav { margin-top: 1.25rem; }
.nav-group { margin-bottom: 1.2rem; }
.nav-group h2 {
  margin: 0 0 0.4rem;
  color: var(--muted);
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.nav a {
  display: block;
  padding: 0.3rem 0.55rem;
  border-radius: 6px;
  color: var(--fg);
  font-size: 0.9rem;
}
.nav a:hover {
  background: var(--hover);
  text-decoration: none;
}
main {
  min-width: 0;
  padding: 2.5rem clamp(1.25rem, 4vw, 4rem) 5rem;
}
.hero {
  margin-bottom: 3rem;
  padding-bottom: 2rem;
  border-bottom: 1px solid var(--border);
}
.eyebrow {
  margin: 0 0 0.5rem;
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.hero h1 {
  margin: 0;
  font-size: clamp(2rem, 5vw, 3.4rem);
  letter-spacing: -0.04em;
  line-height: 1.05;
}
.hero p {
  max-width: 65ch;
  color: var(--muted);
}
.stats {
  margin-top: 1rem;
  font-size: 0.85rem;
}
.note {
  margin: 0 0 4.5rem;
  scroll-margin-top: 1.5rem;
}
.note-header {
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 2px solid var(--fg);
}
.kicker {
  margin: 0 0 0.4rem;
  color: var(--muted);
  font-size: 0.72rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.note-header h2 {
  margin: 0;
  font-size: clamp(1.7rem, 3vw, 2.4rem);
  letter-spacing: -0.02em;
  line-height: 1.15;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.8rem;
}
.chip {
  padding: 0.15rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--muted);
  font-size: 0.75rem;
}
.content {
  max-width: 78ch;
}
.content h2,
.content h3,
.content h4 {
  margin-top: 2rem;
  line-height: 1.25;
  scroll-margin-top: 1rem;
}
.content h2 {
  padding-bottom: 0.3rem;
  border-bottom: 1px solid var(--border);
}
.content p,
.content li {
  font-size: 1rem;
}
.content table {
  display: block;
  width: 100%;
  margin: 1rem 0;
  border-collapse: collapse;
  font-size: 0.9rem;
  overflow-x: auto;
}
.content th,
.content td {
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}
.content th {
  background: var(--table-head);
}
.content pre {
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--code);
  overflow-x: auto;
}
.content code {
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  background: var(--code);
  font-size: 0.9em;
}
.content pre code {
  padding: 0;
  background: transparent;
}
.content blockquote {
  margin: 1rem 0;
  padding: 0.5rem 1rem;
  border-left: 4px solid var(--accent);
  background: var(--quote);
  color: var(--muted);
}
.content hr {
  margin: 2rem 0;
  border: 0;
  border-top: 1px solid var(--border);
}
.callout {
  margin: 1.2rem 0;
  padding: 0.8rem 1rem;
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
  border-radius: 8px;
  background: var(--callout);
}
.callout.warning {
  border-left-color: #d97706;
}
.callout-title {
  margin: 0 0 0.4rem;
  font-weight: 700;
}
.callout p:last-child {
  margin-bottom: 0;
}
.toc {
  max-width: 78ch;
  margin: 0 0 2rem;
  padding: 0.8rem 1rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.toc .toctitle {
  margin: 0 0 0.4rem;
  color: var(--muted);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.toc ul {
  margin: 0;
  padding-left: 1.1rem;
}
.toc li {
  margin: 0.15rem 0;
}
.toc a {
  color: var(--fg);
  font-size: 0.9rem;
}
.related {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.85rem;
}
.missing-link {
  color: #b91c1c;
  border-bottom: 1px dotted currentColor;
}
footer.page-footer {
  margin-top: 4rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.85rem;
}
@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .sidebar {
    position: static;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }
  .nav {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
  }
  .nav-group {
    margin: 0;
  }
  main {
    padding-top: 1.5rem;
  }
}
@media print {
  .sidebar, .search, .toc { display: none; }
  .layout { display: block; }
  main { padding: 0; }
  .note { break-inside: avoid; }
  a { color: inherit; }
}
"""

SCRIPT = """
const search = document.getElementById('search');
const notes = Array.from(document.querySelectorAll('.note'));
const links = Array.from(document.querySelectorAll('.nav a'));
const groups = Array.from(document.querySelectorAll('.nav-group'));

function applyFilter() {
  const query = search.value.trim().toLowerCase();
  notes.forEach((note) => {
    note.hidden = query !== '' && !note.textContent.toLowerCase().includes(query);
  });
  links.forEach((link) => {
    const target = document.getElementById(link.dataset.target);
    link.hidden = !target || target.hidden;
  });
  groups.forEach((group) => {
    group.hidden = !Array.from(group.querySelectorAll('a')).some((link) => !link.hidden);
  });
}

search.addEventListener('input', applyFilter);
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && document.activeElement !== search) {
    event.preventDefault();
    search.focus();
  }
});
"""
