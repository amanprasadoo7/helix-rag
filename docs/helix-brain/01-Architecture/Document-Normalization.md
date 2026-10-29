---
type: architecture
status: active
day: 3
tags: [parsing, normalization, ingestion, acl, pdf, docling, unstructured, interview]
related: ["[[Parsing]]", "[[Parser-Lab]]", "[[Ingestion-M1]]", "[[Corpus]]", "[[Project-Map]]", "[[Checklist]]"]
---

# Document normalization: why and how

**Short answer:** we do not chunk raw files. We parse each source once into one
internal model — a document, a section tree, typed blocks, normalized text plus
the raw excerpt, and metadata. Chunking, ACLs, embedding, retrieval, and
citations all work from that model instead of re-interpreting Markdown, PDF, or
DOCX syntax.

## What “normalize” means here

It does **not** mean “convert everything to Markdown.” It means “convert every
source into the same internal shape.”

```text
Markdown / PDF / DOCX / HTML
             |
             v
      Document model
      ├── Document: source, path, title, frontmatter, warnings
      ├── Section: heading level, breadcrumb, child sections
      └── Block: paragraph, list, table, code, quote, callout
             |
             v
   chunker -> ACL -> embedder -> stores
```

Each block carries:

- `type`: what it is;
- `text`: normalized for retrieval and embedding;
- `raw`: the original excerpt for debugging and citations;
- `meta`: type-specific details such as table headers and rows, list levels, or
  code language.

JSON is the serialization format. It is not the database and it is not the
product. It is an inspectable, deterministic intermediate representation.

For this repo, the parser is `packages/helix/parsing.py` and the output is written
by `scripts/parse_corpus.py`. See [[Parsing]] for the model and [[Ingestion-M1]]
for where it sits in the full ingest pipeline.

## Why normalize before chunking

### 1. One interpretation of structure

If the chunker parses Markdown itself, it re-implements fences, headings, tables,
lists, shortcodes, and HTML. Every consumer then has a slightly different idea of
what a heading is. A single parser makes the rules explicit and testable.

### 2. Chunks are the retrieval unit, but sections are the context unit

A chunk needs a parent section, a breadcrumb, and a source path. Those are cheap
to produce during parsing and awkward to reconstruct after splitting raw text.

### 3. Citations need structure

A good citation is not “somewhere in this 40 KB file.” It is “this document,
this section, this path.” The section tree gives the citation its address.

### 4. Permissions must attach before storage

Chunks are what get embedded and retrieved. ACL metadata has to exist before the
first chunk is written. Normalization is where a document gets its identity,
path, and classification inputs. The ACL step (1.2) then adds classification and
allowed roles before chunking.

### 5. Determinism makes re-ingestion cheap

The same source produces byte-identical JSON. There are no timestamps, random
ids, or set iteration in the output. That makes review possible, content hashes
stable, and a rerun a no-op when nothing changed.

### 6. Format independence

Retrieval should not care whether a paragraph came from Markdown, a PDF, or a
DOCX. Once every adapter produces the same `Document` model, the chunker and
embedder stay unchanged. Only the adapters and provenance metadata differ.

## Why a native parser for this corpus

The pinned corpus is Markdown, not PDF. It also has site-specific conventions:

- YAML frontmatter with the page title;
- Hugo shortcodes such as `{{< details >}}`;
- tables with escaped pipes and pipes inside shortcodes;
- fenced code inside list items.

A native parser handles those directly. It is fast (about 13 seconds for 2,500
documents), deterministic, and has no model download.

Docling is the right tool for layout-heavy formats, but it is not a Markdown
semantic parser. In the parser lab, Docling treated frontmatter and shortcodes
as ordinary text. That is expected: it is solving a different problem. The
decision is recorded in [ADR 0001](../../adr/0001-markdown-parser.md).

## Why JSON

JSON is not chosen because “RAG needs JSON.” It is chosen because the parser
output should be:

- inspectable by a human;
- diffable between runs;
- serializable across languages and services;
- easy to validate with Pydantic;
- stable enough for content hashes.

The model could be stored in Postgres later. The file is just the handoff
artifact.

## How we know parsing is correct

We cannot manually read 2,500 files, and “it ran without crashing” is not
correctness. The assurance stack is:

1. **Fixture tests.** `tests/test_parsing.py` has 13 small Markdown files. Each
   one pins a rule: fences, headings, tables, lists, shortcodes, HTML, title
   fallback, duplicate slugs, determinism, warnings.
2. **Corpus-wide invariants.** I ran a check over all 2,500 parsed documents:
   stats agree with the tree, section ids are unique, breadcrumbs are consistent,
   blocks are non-empty, no shortcodes leak into normalized text, and table rows
   match their header width. Result: `docs=2500, errors=0`.
3. **An independent audit.** I counted ATX headings directly from the source,
   ignoring fenced code, and compared the count with the parsed section tree. One
   document out of 2,500 differed. The cause was a code fence opened inside a
   numbered list and an intended closing fence with an info string; under
   Markdown rules the block stays open, so two visible “headings” were actually
   code. The parser was following Markdown semantics. The audit did its job by
   surfacing an ambiguity worth reviewing.
4. **Warnings and failures.** The full run reports 0 failures and 26 warnings.
   All 26 are pages whose only content is a dynamic shortcode, so there is no
   static text to extract. The parser names the problem instead of silently
   indexing nothing.
5. **Human sampling.** Read the largest, smallest, table-heavy, and code-heavy
   files alongside their JSON. This catches output that is structurally valid but
   semantically useless.
6. **Determinism.** Re-parsing unchanged input produces identical JSON, so
   unexpected diffs stand out.
7. **Downstream eval.** The real test is whether retrieval answers correctly with
   valid citations. Unit tests and invariants reduce risk; they do not replace
   end-to-end measurement.

The honest interview answer is: “I don’t prove every file is perfect. I make the
rules testable, check invariants over every file, surface anomalies, review a
sample, and measure retrieval. One anomaly found by the heading audit was a
malformed fence, not a parser bug.”

## How to handle PDFs, images, DOCX, and other formats

Keep the same model and add adapters:

| Input | Adapter | What to preserve |
|---|---|---|
| Markdown, text | native parser | headings, lists, tables, code, frontmatter |
| Text PDF | Docling or PyMuPDF | reading order, pages, tables |
| Scanned PDF / image | OCR + layout, or Docling OCR | text, confidence, bounding boxes |
| DOCX, PPTX, ODT | Docling or native office parser | heading styles, lists, tables, notes |
| XLSX, CSV | openpyxl or pandas | sheets, headers, row ranges |
| HTML | trafilatura or Docling | main content, headings, tables |
| Source code | tree-sitter | functions, classes, imports |

The contract stays:

```python
parse_file(path: str) -> Document
```

A registry picks the adapter by MIME type or extension. All adapters produce the
same `Section` and `Block` types, so chunking and embedding do not change.

For non-text sources, keep provenance in block metadata:

```json
{
  "type": "paragraph",
  "text": "...",
  "meta": {
    "page": 3,
    "bbox": [72, 144, 520, 210],
    "ocr_confidence": 0.91,
    "extraction_method": "docling"
  }
}
```

Also:

- keep the raw file in MinIO; parsed JSON is a derivative;
- detect text PDFs vs scanned PDFs before choosing OCR;
- treat tables as structure, not OCR prose;
- do not print DOCX/PPTX to PDF when the native structure is available;
- benchmark each adapter on a format-specific golden set;
- pin parser and model versions per source;
- audio and video are out of scope for now.

See [[Parser-Lab]] for the native vs Docling vs Unstructured comparison and the
detailed Unstructured notes.

## Trade-offs

- **Output size.** Keeping `raw` and `text` roughly doubles storage. That is
  cheap compared with the cost of losing the source excerpt.
- **Parser drift.** Upstream format changes and parser version changes can alter
  output. Determinism and content hashes make the diff visible; pinned versions
  make it reproducible.
- **Per-format quality.** A Markdown invariant suite says little about OCR
  quality. PDFs need page coverage, table accuracy, and OCR confidence checks.
- **Not free text forever.** Normalization is lossy by design. Keep raw files so
  a better parser can re-run later.

## Interview script

### The 60-second answer

> “We normalize each source into one document model before chunking so the
> chunker and retriever share a single interpretation of headings, tables, code,
> and structure. For this corpus, which is Markdown with Hugo frontmatter and
> shortcodes, I used a native parser instead of Docling because Docling is built
> for layout-heavy formats and treats frontmatter as text. The parser emits a
> section tree, typed blocks, normalized text for retrieval, raw text for
> debugging and citations, and metadata. It is deterministic, so re-ingesting an
> unchanged corpus is a no-op at the file level. I validate it with fixture
> tests, corpus-wide invariants, warnings, sampling, and an independent heading
> audit. The design is adapter-based, so PDFs and DOCX can use Docling or
> Unstructured later while chunking and embedding stay the same.”

### Likely follow-ups

**“Why not chunk raw Markdown directly?”**

> “Then every consumer re-implements fence, heading, table, and shortcode rules.
> We also lose the parent section and breadcrumb that citations need, and there
> is no clean place to attach ACL metadata before chunks are stored.”

**“Why not use Docling for everything?”**

> “Docling is good at layout-heavy documents. This corpus has no PDFs or HTML,
> and Docling does not understand YAML frontmatter or Hugo shortcodes. Using it
> here adds models and runtime without improving structure. It becomes the PDF
> adapter later.”

**“How do you know parsing is correct?”**

> “I don’t eyeball 2,500 files. I test the rules with small fixtures, check
> structural invariants over every output, make warnings explicit, review a
> stratified sample, and verify determinism. An independent heading count found
> one anomaly in 2,500; it was a malformed fence in the source. The final signal
> is retrieval quality with valid citations.”

**“Why JSON?”**

> “It is a deterministic, inspectable serialization of the internal model. It is
> not the database. It makes diffs, tests, content hashes, and debugging
> straightforward.”

**“How would you handle PDFs, scanned pages, and DOCX?”**

> “Adapters behind the same document model. Docling for layout PDFs, OCR plus
> layout for scans, Docling or native office parsers for DOCX/PPTX,
> openpyxl/pandas for spreadsheets. Keep page, bbox, OCR confidence, and the raw
> file. Benchmark each format instead of assuming one parser wins everywhere.”

**“Why not Unstructured?”**

> “Unstructured is useful for broad format coverage and typed elements, but its
> output is flat and its Markdown path goes through HTML and NLP, so it does not
> understand this site’s frontmatter and shortcodes. It is a candidate for
> DOCX/PDF, not the default for Markdown.”

**“Why ACL before chunking?”**

> “Chunks are what get stored and retrieved. If permissions are attached later,
> there is a window where the index contains unlabeled chunks. ACLs must be part
> of the chunk payload and applied as a pre-filter before vector search.”

**“What was the hardest bug?”**

> “Hugo shortcodes and Markdown edge cases: fences inside list items, table pipes
> inside shortcode attributes, and a trailing `#` in headings such as `C#`. Each
> one became a fixture so it cannot regress.”

**“What changes at 100x scale?”**

> “Parse in parallel workers, stream or shard output, cache by content hash,
> reconcile incrementally, store raw files in object storage, version the schema,
> and benchmark adapters per source. The document contract stays the same.”

### Things not to say

- “JSON is the database.” It is an intermediate artifact.
- “Docling is bad.” It solves a different problem.
- “The parser is proven correct.” It is tested and measured, not proven.
- “We run three parsers in production.” The lab compares; production routes by
  format.

## Interview one-liner

> “Parse once, normalize to a section tree plus typed blocks, attach permissions
> before chunking, and validate with invariants and retrieval evals.”

## Current state

- 1.1 native Markdown parser: implemented, 2,500 documents, 0 failures, 26
  warnings.
- Parser lab: native vs Docling vs Unstructured, local CLI only.
- 1.2 ACL classifier is implemented and verified; 1.3 chunker is implemented and
  awaiting verification; 1.4 embedder, 1.5 stores, and 1.6 worker are still
  ahead.
- The adapter design for PDFs/DOCX/images is a plan, not implemented.
