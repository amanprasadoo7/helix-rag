# ADR 0001: Parse Markdown natively and defer Docling

- **Status:** Accepted
- **Date:** 2026-10-25
- **Checkpoint:** 1.1

## Context

The roadmap names Docling and Markdown for the parser stage. The pinned corpus,
however, is 2,500 Markdown files from two Git repositories. It contains no PDFs,
scanned pages, or HTML documents. Docling earns its keep on layout-heavy formats
(PDF, DOCX, images), where reading order and tables are hard to recover. On
plain Markdown it adds a large model/runtime dependency without adding accuracy.

We still need a stable intermediate representation before the ACL classifier and
chunker run, so parsing cannot be skipped.

## Decision

Parse Markdown with a small native parser in `packages/helix/parsing.py`.
Emit one deterministic JSON document per source file with:

- frontmatter as JSON-safe metadata,
- a heading tree with breadcrumbs and unique anchor-style ids,
- typed blocks with normalized text plus the source excerpt.

Docling is deferred. It becomes an adapter behind the same document model when a
non-Markdown source enters the corpus.

## Alternatives considered

| Option | Why not now |
|---|---|
| Docling for every file | Heavy dependency and model downloads; Markdown needs no layout inference. |
| `markdown-it-py` token stream | Good CommonMark coverage, but another dependency and still needs Hugo/HTML cleanup. |
| Python-Markdown to HTML, then parse HTML | Adds a lossy round trip; heading scopes and code blocks are easier from source. |
| Unstructured | Broad format support, but heavier and less predictable than the corpus needs. |
| Raw text split, no structure | The chunker needs headings, lists, tables, and code fences to preserve meaning. |

## Consequences

- Fast and deterministic: the full corpus parses in about 13 seconds with no
  network or model access.
- The parser is intentionally corpus-shaped. It understands the Markdown and
  Hugo/HTML patterns actually present, not every CommonMark edge case.
- Setext headings and four-space indented code blocks are not implemented.
  Neither appears in the pinned snapshot; add them with tests if a new source
  uses them.
- Dynamic shortcodes (team lists, generated tables) disappear. A document that
  consists only of such a shortcode parses to an empty document with a warning.
- Tables in the corpus occasionally contain unescaped pipes inside shortcodes or
  code spans. Those are protected before splitting; other malformed tables may
  still split at the wrong cell.

## Revisit when

- A PDF, DOCX, HTML, or scanned source is added to the corpus.
- The golden set shows retrieval failures caused by lost structure.
- A second Markdown dialect appears and the native parser starts accumulating
  special cases.
