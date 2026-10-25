---
type: architecture
status: implemented
day: 3
tags: [parsing, markdown, ingestion, structure]
related: ["[[Corpus]]", "[[Ingestion-M1]]", "[[Document-Normalization]]", "[[Parser-Lab]]", "[[Project-Map]]", "[[Checklist]]", "[[2026-10-25]]"]
---

# Parsing: Markdown to a stable document model

**Short answer:** the parser reads one Markdown file once and writes one JSON
document with metadata, a heading tree, and typed blocks. Later stages stop
thinking about Markdown and start thinking about sections, text, and structure.

## Why parse at all?

The corpus is already text, so it is tempting to hand raw Markdown to the
chunker. That breaks in predictable ways:

- a `#` inside a code fence is not a heading;
- a table row is not a paragraph;
- a list item is not a sentence to split in half;
- Hugo shortcodes and inline HTML are markup, not content;
- a citation needs a heading and a path, not a byte offset in a large file.

Parsing is where those decisions happen. If the parser gets them wrong, the
chunker and retriever inherit the mistake.

## The model

`packages/helix/parsing.py` defines four types:

| Type | What it holds |
|---|---|
| `Document` | source, path, commit, title, frontmatter, root section, stats, warnings |
| `Section` | level, title, anchor-style id, breadcrumb, blocks, child sections |
| `Block` | type, normalized `text`, source `raw`, type-specific `meta` |
| `DocumentStats` | counts for sections, blocks, words, code, tables, shortcodes |

The root section has level 0 and holds content before the first heading. When an
H1 supplies the document title, the parser uses it as the root title instead of
creating a duplicate child section.

### Block types

| Type | Examples | Useful metadata |
|---|---|---|
| `paragraph` | prose | none |
| `list` | ordered/unordered, nested | `ordered`, `items[{text, level}]` |
| `code` | fenced code | `language` |
| `table` | GFM tables | `headers`, `rows` |
| `quote` | blockquote | none |
| `callout` | `> [!warning]` | `callout` |
| `html` | `<details>`, `<dl>` | text is flattened |

Two fields look redundant but are not. `text` is normalized for retrieval:
links become their labels, emphasis disappears, HTML tags are stripped, and
whitespace is collapsed. `raw` keeps the original excerpt so a parser bug or a
citation can be traced back to the source.

## What the parser handles

- YAML frontmatter, converted to JSON-safe values (dates become ISO strings).
- ATX headings (`## Like this`), a heading tree, breadcrumbs, and duplicate
  anchors (`install`, `install-1`).
- Fenced code with any indent, including fences inside list items. Code content
  is never normalized.
- GFM tables, including escaped pipes and pipes inside shortcodes or inline code.
- Ordered and unordered lists, with nested item levels and continuation lines.
- Blockquotes and `[!note]` / `[!warning]` callouts.
- Hugo shortcodes: container tags are removed but their content stays; `yes` and
  `no` become text; a tab title becomes a label.
- Inline HTML (`<kbd>`, `<br>`, `<dl>`, `<details>`) and Markdown links, images,
  inline code, emphasis, and entities.
- Documents whose content is only a dynamic shortcode. They parse successfully
  with an empty-document warning instead of crashing the run.

## What it does not handle

- Setext headings (`Title` underlined with `===`). The pinned corpus has none.
- Four-space indented code blocks that use no fence. The corpus uses fences.
- Dynamic shortcodes such as team lists. There is no static text to extract, so
  the page is empty by design.
- Perfect CommonMark. Nested lists are flattened in `text` (levels remain in
  `meta`), and complex HTML tables are flattened rather than reconstructed.
- Cross-document links. Resolving `../other.md` is a later concern.

## Commands

```bash
make parse          # all manifest files -> data/parsed
make parse-sample   # five evenly spaced files, one line each
```

Inspect one document:

```bash
python3 -m json.tool \
  data/parsed/handbook/content/handbook/business-technology/enterprise-applications/guides/zuora-collect.json \
  | less
```

Small queries without `jq`:

```bash
python3 -c 'import json; d=json.load(open("data/parsed/...json")); print(d["stats"])'
python3 -c 'import json; d=json.load(open("data/parsed/...json")); print([s["title"] for s in d["root"]["children"]])'
```

## Current result

| Measure | Value |
|---|---:|
| Documents | 2,500 |
| Sections | 37,614 |
| Blocks | 113,255 |
| Words | 3,565,493 |
| Code blocks | 12,408 |
| Tables | 7,280 |
| Shortcodes removed | 14,523 |
| Parse time | ~13 s |
| Output size | ~122 MB |
| Failures | 0 |
| Warnings | 26 (empty pages whose only content is a dynamic shortcode) |

The word count is lower than the manifest's estimate because frontmatter, link
URLs, and shortcode arguments are not content.

## Decisions and trade-offs

### Native parser instead of Docling

Docling is for layout-heavy formats. The corpus is Markdown. Running Docling
here would add models and runtime without improving structure. See
[ADR 0001](../../adr/0001-markdown-parser.md). Docling becomes an adapter behind
the same document model when a PDF or scanned source appears.

### Heading tree instead of a flat list

A tree gives the chunker a parent section for free. Breadcrumbs make citations
readable (`Handbook > Engineering > ...`) and give the embedder context that the
child text alone lacks.

### Raw plus normalized text

Keeping both doubles output size, but it separates "what the model sees" from
"what the source said". That distinction is hard to reconstruct later.

### Deterministic JSON

The same input produces byte-identical JSON. There are no timestamps, UUIDs, or
set iteration in a document. This makes re-parsing a no-op for review and gives
the later content-hash cache a stable input.

## Common doubts

### Why not let the chunker parse Markdown?

Because then every consumer re-implements fence, table, and heading rules. A
single parsed artifact also makes it possible to inspect exactly what the next
stage received.

### Why is the output larger than the corpus?

It is pretty-printed JSON carrying both `raw` and `text`. Storage is cheap; the
point is inspectability. If size matters, write compact JSON or drop `raw` for
`code` and `table` blocks.

### Why do some documents have no blocks?

Their body is a single dynamic shortcode, for example a generated team roster.
The content exists only at build time on the upstream site. The parser records a
warning rather than inventing text.

### Why keep list levels in metadata if text is flat?

The chunker may want to split a long list or repeat the parent bullet. Flattening
only the retrieval text keeps embedding simple without throwing structure away.

### What happens when the corpus pin changes?

The parser is deterministic, so re-running `make parse` produces a new tree for
changed files. Ingestion will compare content hashes in a later checkpoint; the
parser itself does no reconciliation.

## Interview angle

- "I parse Markdown once into a document model so the chunker and retriever share
  one interpretation of headings, lists, code, and tables."
- "Normalized text is for retrieval; raw text is for debugging and citations.
  Keeping both avoids a lossy handoff."
- "I chose a native Markdown parser because the corpus has no PDFs; Docling is
  deferred behind the same interface rather than paying for unused layout
  inference."
- "The parser is deterministic, so re-ingesting an unchanged corpus is a no-op
  at the file level."
- "Twenty-six pages are empty because their content is generated by a dynamic
  shortcode. I surface that as a warning instead of silently indexing nothing."
