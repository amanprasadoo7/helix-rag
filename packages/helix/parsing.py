"""Markdown parser for the pinned corpus.

The corpus is Markdown, not PDF or HTML, so the first parser is native. It
turns one source file into a stable document model:

- frontmatter, preserved as JSON-safe metadata;
- a heading tree, with breadcrumbs and unique anchor-style ids;
- typed blocks (paragraph, list, code, table, quote/callout, html) carrying
  normalized text for retrieval and the source excerpt for debugging.

The chunker and ACL classifier consume this model instead of re-reading
Markdown. Parsing stays deterministic: the same input produces the same JSON.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

BlockType = Literal["paragraph", "list", "code", "table", "quote", "callout", "html"]


class Block(BaseModel):
    """One content block. ``text`` is what retrieval sees; ``raw`` is the source."""

    type: BlockType
    text: str
    raw: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class Section(BaseModel):
    """A heading scope. Level 0 is the document root and holds the preamble."""

    id: str
    level: int
    title: str
    heading: str = ""
    breadcrumb: list[str] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    children: list[Section] = Field(default_factory=list)

    def walk(self) -> Iterator[Section]:
        yield self
        for child in self.children:
            yield from child.walk()


class DocumentStats(BaseModel):
    sections: int = 0
    blocks: int = 0
    words: int = 0
    chars: int = 0
    code_blocks: int = 0
    tables: int = 0
    shortcodes_removed: int = 0


class Document(BaseModel):
    schema_version: int = SCHEMA_VERSION
    source: str
    path: str
    commit: str = ""
    title: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    root: Section
    stats: DocumentStats = Field(default_factory=DocumentStats)
    warnings: list[str] = Field(default_factory=list)

    def walk(self) -> Iterator[Section]:
        yield from self.root.walk()

    def blocks(self) -> Iterator[Block]:
        for section in self.walk():
            yield from section.blocks

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


# --- Markdown patterns -------------------------------------------------------

_ATX_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([^\s`]*)")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>[ \t]?(.*)$")
_THEMATIC_BREAK = re.compile(r"^\s{0,3}((\*[ \t]*){3,}|(-[ \t]*){3,}|(_[ \t]*){3,})$")
_LINK_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s+\S+")
_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_HTML_BLOCK_START = re.compile(
    r"^\s*<(?:address|article|aside|blockquote|details|div|dl|fieldset|figcaption|"
    r"figure|footer|form|h[1-6]|header|hr|iframe|img|li|main|nav|ol|p|pre|section|"
    r"summary|table|ul|video)\b",
    re.IGNORECASE,
)

_SHORTCODE = re.compile(r"\{\{[<%]\s*/?\s*[A-Za-z0-9_-]+.*?[>%]\}\}")
_SHORTCODE_TITLE = re.compile(r"""title\s*=\s*["']([^"']+)["']""")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_REFERENCE_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>]+)>")
_INLINE_CODE = re.compile(r"`+([^`\n]+?)`+")
_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*")
_BOLD_UNDER = re.compile(r"__(.+?)__")
_STRIKE = re.compile(r"~~(.+?)~~")
_EM_STAR = re.compile(r"(?<!\w)\*([^*\n]+?)\*(?!\w)")
_EM_UNDER = re.compile(r"(?<!\w)_([^_\n]+?)_(?!\w)")
_ESCAPE = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>])")

_BLOCK_HTML_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_SKIP_HTML_TAGS = frozenset({"script", "style"})


class _HTMLTextExtractor(HTMLParser):
    """Flatten inline/block HTML to plain text, keeping visible content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        if tag in _SKIP_HTML_TAGS:
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f" {alt} ")
        elif tag in _BLOCK_HTML_TAGS:
            self.parts.append("\n")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_HTML_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_HTML_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)


def _html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # malformed HTML should not fail a document
        return value
    return "".join(parser.parts)


def normalize_text(value: str) -> str:
    """Strip Markdown/HTML syntax so the text is usable for retrieval."""
    text = _COMMENT.sub(" ", value)

    code_spans: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        code_spans.append(html.unescape(match.group(1)))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = _INLINE_CODE.sub(stash_code, text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _REFERENCE_LINK.sub(r"\1", text)
    text = _AUTOLINK.sub(r"\1", text)

    if "<" in text or "&" in text:
        text = _html_to_text(text)

    text = _BOLD_STAR.sub(r"\1", text)
    text = _BOLD_UNDER.sub(r"\1", text)
    text = _STRIKE.sub(r"\1", text)
    text = _EM_STAR.sub(r"\1", text)
    text = _EM_UNDER.sub(r"\1", text)
    text = _ESCAPE.sub(r"\1", text)
    text = html.unescape(text)
    text = " ".join(text.split())
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)

    for index, code in enumerate(code_spans):
        text = text.replace(f"\x00CODE{index}\x00", code)
    return text.strip()


def _strip_shortcodes(line: str) -> tuple[str, int]:
    """Remove Hugo shortcode tokens, keeping the content they wrap."""

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("{{< yes"):
            return "Yes"
        if token.startswith("{{< no"):
            return "No"
        if token.startswith("{{< tab"):
            title = _SHORTCODE_TITLE.search(token)
            if title:
                return f"\n\n**{title.group(1)}**\n\n"
        return ""

    replaced, count = _SHORTCODE.subn(replace, line)
    return replaced, count


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text, []

    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            raw = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            try:
                parsed = yaml.safe_load(raw) or {}
            except yaml.YAMLError as exc:
                return {}, body, [f"frontmatter: {type(exc).__name__}"]
            if not isinstance(parsed, dict):
                return {}, body, ["frontmatter: expected a mapping"]
            return _json_safe(parsed), body, []

    return {}, text, ["frontmatter: missing closing delimiter"]


def _fallback_title(path: str) -> str:
    source = PurePosixPath(path)
    stem = source.stem
    if stem == "_index":
        stem = source.parent.name or "index"
    return stem.replace("-", " ").replace("_", " ").title()


def _frontmatter_title(frontmatter: dict[str, Any]) -> str:
    title = frontmatter.get("title")
    return title.strip() if isinstance(title, str) else ""


def _first_h1(lines: list[str]) -> str:
    in_fence: str | None = None
    for line in lines:
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if in_fence is None:
                in_fence = marker
            elif marker[0] == in_fence[0] and len(marker) >= len(in_fence):
                in_fence = None
            continue
        if in_fence:
            continue
        cleaned, _ = _strip_shortcodes(line)
        heading = _ATX_HEADING.match(cleaned)
        if heading and len(heading.group(1)) == 1:
            return normalize_text(heading.group(2))
    return ""


def _slugify(value: str, seen: dict[str, int]) -> str:
    base = normalize_text(value).lower()
    base = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE)
    base = re.sub(r"\s+", "-", base.strip())
    base = re.sub(r"-{2,}", "-", base).strip("-") or "section"

    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}-{count}"


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines) or "|" not in lines[index]:
        return False
    separator = lines[index + 1]
    return "|" in separator and _TABLE_SEPARATOR.match(separator) is not None


def _clean_table_row(line: str) -> tuple[list[str], int]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]

    protected: list[str] = []

    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00CELL{len(protected) - 1}\x00"

    value = re.sub(r"\{\{[<%].*?[>%]\}\}|`+[^`\n]+?`+", stash, value)
    cells = re.split(r"(?<!\\)\|", value)
    cleaned: list[str] = []
    removed = 0
    for cell in cells:
        for position, token in enumerate(protected):
            cell = cell.replace(f"\x00CELL{position}\x00", token)
        text, count = _strip_shortcodes(cell.replace("\\|", "|"))
        removed += count
        cleaned.append(normalize_text(text))
    return cleaned, removed


def _starts_block(lines: list[str], index: int) -> bool:
    line = lines[index]
    if not line.strip():
        return True
    if _FENCE.match(line) or _ATX_HEADING.match(line):
        return True
    if _LIST_ITEM.match(line) or _QUOTE.match(line):
        return True
    if _THEMATIC_BREAK.match(line) or _LINK_DEFINITION.match(line):
        return True
    if _HTML_BLOCK_START.match(line):
        return True
    return _is_table_start(lines, index)


def _append_list_item(
    entries: list[dict[str, Any]], current: list[str], level: int
) -> None:
    text = normalize_text(" ".join(current))
    if text:
        entries.append({"text": text, "level": level})


def _count_words(root: Section) -> int:
    words = 0
    for section in root.walk():
        if section.level > 0:
            words += len(section.title.split())
        for block in section.blocks:
            words += len(block.text.split())
    return words


def parse_markdown(
    text: str,
    *,
    source: str,
    path: str,
    commit: str = "",
) -> Document:
    """Parse one Markdown document into the normalized model."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    frontmatter_raw, body, warnings = _split_frontmatter(text)
    lines = body.split("\n")

    removed = 0
    title = _frontmatter_title(frontmatter_raw)
    title_heading = ""
    if not title:
        title = _first_h1(lines)
        title_heading = title
    if not title:
        title = _fallback_title(path)

    root = Section(
        id="root",
        level=0,
        title=title,
        heading="",
        breadcrumb=[title],
    )
    stack: list[Section] = [root]
    seen_slugs: dict[str, int] = {}
    block_count = 0
    code_blocks = 0
    tables = 0

    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            language = fence.group(2).lower()
            fence_indent = len(line) - len(line.lstrip(" "))
            prefix = " " * fence_indent
            start = index
            index += 1
            code_lines: list[str] = []
            while index < len(lines):
                if re.match(
                    rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$",
                    lines[index],
                ):
                    break
                code_line = lines[index]
                if fence_indent:
                    code_line = (
                        code_line[fence_indent:]
                        if code_line.startswith(prefix)
                        else code_line.lstrip(" ")
                    )
                code_lines.append(code_line)
                index += 1
            if index >= len(lines):
                warnings.append(f"code fence at line {start + 1}: missing closing fence")
                raw = "\n".join(lines[start:])
            else:
                raw = "\n".join(lines[start : index + 1])
                index += 1
            stack[-1].blocks.append(
                Block(
                    type="code",
                    text="\n".join(code_lines).rstrip("\n"),
                    raw=raw,
                    meta={"language": language},
                )
            )
            block_count += 1
            code_blocks += 1
            continue

        line, count = _strip_shortcodes(line)
        removed += count

        heading = _ATX_HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            heading_text = normalize_text(heading.group(2))
            if not heading_text:
                index += 1
                continue
            if title_heading:
                is_title_heading = level == 1 and heading_text == title_heading
                title_heading = ""
                if is_title_heading:
                    index += 1
                    continue
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1]
            section = Section(
                id=_slugify(heading_text, seen_slugs),
                level=level,
                title=heading_text,
                heading=heading_text,
                breadcrumb=[*parent.breadcrumb, heading_text],
            )
            parent.children.append(section)
            stack.append(section)
            index += 1
            continue

        if _THEMATIC_BREAK.match(line) or _LINK_DEFINITION.match(line):
            index += 1
            continue

        if _is_table_start(lines, index):
            start = index
            headers, count = _clean_table_row(lines[index])
            removed += count
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                row, count = _clean_table_row(lines[index])
                removed += count
                if len(row) < len(headers):
                    row.extend([""] * (len(headers) - len(row)))
                rows.append(row)
                index += 1
            text = "\n".join(" | ".join(row) for row in [headers, *rows])
            stack[-1].blocks.append(
                Block(
                    type="table",
                    text=text,
                    raw="\n".join(lines[start:index]),
                    meta={"headers": headers, "rows": rows},
                )
            )
            block_count += 1
            tables += 1
            continue

        item = _LIST_ITEM.match(line)
        if item:
            base_indent = len(item.group(1))
            ordered = item.group(2)[0].isdigit()
            start = index
            entries: list[dict[str, Any]] = []
            indent_stack = [base_indent]
            current: list[str] = []
            current_level = 0

            while index < len(lines):
                raw_line = lines[index]
                if not raw_line.strip():
                    lookahead = index + 1
                    while lookahead < len(lines) and not lines[lookahead].strip():
                        lookahead += 1
                    if lookahead < len(lines):
                        next_item = _LIST_ITEM.match(lines[lookahead])
                        indented = len(lines[lookahead]) - len(lines[lookahead].lstrip())
                        if next_item or indented > base_indent:
                            index += 1
                            continue
                    break
                if _FENCE.match(raw_line):
                    break
                nested = _LIST_ITEM.match(line if index == start else raw_line)
                if nested:
                    indent = len(nested.group(1))
                    if indent < base_indent:
                        break
                    while len(indent_stack) > 1 and indent < indent_stack[-1]:
                        indent_stack.pop()
                    if indent > indent_stack[-1]:
                        indent_stack.append(indent)
                    if index == start:
                        item_text = nested.group(3)
                    else:
                        item_text, count = _strip_shortcodes(nested.group(3))
                        removed += count
                    _append_list_item(entries, current, current_level)
                    current = [item_text]
                    current_level = len(indent_stack) - 1
                    index += 1
                    continue
                indented = len(raw_line) - len(raw_line.lstrip())
                if indented > indent_stack[-1]:
                    if index == start:
                        cleaned = line
                    else:
                        cleaned, count = _strip_shortcodes(raw_line)
                        removed += count
                    current.append(cleaned.strip())
                    index += 1
                    continue
                break
            _append_list_item(entries, current, current_level)
            if entries:
                stack[-1].blocks.append(
                    Block(
                        type="list",
                        text="\n".join(entry["text"] for entry in entries),
                        raw="\n".join(lines[start:index]),
                        meta={"ordered": ordered, "items": entries},
                    )
                )
                block_count += 1
            continue

        quote = _QUOTE.match(line)
        if quote:
            start = index
            quoted: list[str] = []
            while index < len(lines):
                if index == start:
                    cleaned = quote.group(1)
                else:
                    match = _QUOTE.match(lines[index])
                    if not match:
                        break
                    cleaned, count = _strip_shortcodes(match.group(1))
                    removed += count
                quoted.append(cleaned)
                index += 1
            callout_type = ""
            if quoted:
                callout = re.match(r"^\[!([A-Za-z]+)\]\s*(.*)$", quoted[0])
                if callout:
                    callout_type = callout.group(1).lower()
                    quoted[0] = f"{callout.group(1).title()} {callout.group(2)}"
            quoted_text = normalize_text("\n".join(quoted))
            if quoted_text:
                stack[-1].blocks.append(
                    Block(
                        type="callout" if callout_type else "quote",
                        text=quoted_text,
                        raw="\n".join(lines[start:index]),
                        meta={"callout": callout_type} if callout_type else {},
                    )
                )
                block_count += 1
            continue

        start = index
        paragraph: list[str] = []
        while index < len(lines):
            raw_line = lines[index]
            if not raw_line.strip():
                break
            if paragraph and _starts_block(lines, index):
                break
            if index == start:
                cleaned = line
            else:
                cleaned, count = _strip_shortcodes(raw_line)
                removed += count
            paragraph.append(cleaned)
            index += 1
        paragraph_text = normalize_text("\n".join(paragraph))
        if paragraph_text:
            is_html = bool(_HTML_BLOCK_START.match(line))
            stack[-1].blocks.append(
                Block(
                    type="html" if is_html else "paragraph",
                    text=paragraph_text,
                    raw="\n".join(lines[start:index]),
                )
            )
            block_count += 1

    stats = DocumentStats(
        sections=sum(1 for _ in root.walk()),
        blocks=block_count,
        words=_count_words(root),
        chars=sum(len(block.text) for section in root.walk() for block in section.blocks),
        code_blocks=code_blocks,
        tables=tables,
        shortcodes_removed=removed,
    )

    if block_count == 0:
        warnings.append("document has no content blocks")

    return Document(
        source=source,
        path=path,
        commit=commit,
        title=title,
        frontmatter=frontmatter_raw,
        root=root,
        stats=stats,
        warnings=warnings,
    )


def parse_file(
    file_path: str | Path,
    *,
    source: str,
    path: str | None = None,
    commit: str = "",
) -> Document:
    """Read and parse one UTF-8 Markdown file."""
    resolved = Path(file_path)
    text = resolved.read_text(encoding="utf-8")
    return parse_markdown(
        text,
        source=source,
        path=path or resolved.as_posix(),
        commit=commit,
    )


Section.model_rebuild()
