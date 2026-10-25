---
type: architecture
status: active
day: 3
tags: [parsing, docling, unstructured, markdown, ingestion, evaluation]
related: ["[[Parsing]]", "[[Document-Normalization]]", "[[Ingestion-M1]]", "[[Project-Map]]", "[[Checklist]]", "[[2026-10-25]]"]
---

# Parser lab: native vs Docling vs Unstructured

**Short answer:** `make compare FILE=...` parses one file with all three parsers
and writes their raw JSON plus a side-by-side summary to
`data/parser-lab/<file-stem>/`. It is a local experiment, not part of the ingest
pipeline or CI.

## Why a CLI instead of an API route?

A route would be convenient, but the wrong first tool here:

- Docling and Unstructured load models and can take seconds per file;
- a request would block the event loop or need a background worker;
- uploading a file into the API process expands the attack surface for a
  one-off comparison;
- the output is large JSON that is easier to inspect as files.

The API should get an upload route later, after ingestion is a background job
with size limits, type validation, and object storage. For now the CLI gives the
same answer with less machinery.

## Usage

```bash
make compare FILE=data/corpus/gitlab-docs/doc/user/import/third_party_systems/clearcase.md
```

Options:

```bash
make compare FILE=path/to/file \
  OUT=data/parser-lab/run1 \
  PARSERS=native,docling \
  STRATEGY=fast
```

The first run installs the optional parser dependencies and may download Docling
models. The base project does not install them, so `make ci` stays fast.

## Outputs

For `FILE=.../clearcase.md`, the output directory is
`data/parser-lab/clearcase/`:

| File | What it is |
|---|---|
| `native.json` | our `Document` model: sections, breadcrumbs, typed blocks |
| `docling.json` | Docling's own `DoclingDocument` export |
| `docling.md` | Docling's Markdown export, useful for human review |
| `unstructured.json` | list of Unstructured elements with metadata |
| `summary.json` | status, timing, counts, and previews for all parsers |

Counts are not apples-to-apples. Native counts blocks, Docling counts layout
items, Unstructured counts elements. The summary is for orientation; inspect the
raw files for the real comparison.

## Example: Markdown

On the ClearCase page:

| Parser | Items | Tables | Chars | Time |
|---|---:|---:|---:|---:|
| native | 6 blocks | 1 | 914 | ~0.003 s |
| Docling | 18 layout items | 1 | 2,148 | ~4.9 s |
| Unstructured | 14 elements | 1 | 1,232 | ~5.5 s |

What the difference looks like:

- **Native** uses YAML frontmatter for the title, removes Hugo shortcodes, turns
  links into labels, and stores the table as headers plus rows. Its output is
  smaller and already shaped for chunking.
- **Docling** treats the frontmatter and `{{< details >}}` shortcodes as ordinary
  text. It preserves the table and headings well, but it does not know this
  site's frontmatter or shortcode semantics.
- **Unstructured** also keeps frontmatter and shortcodes as text. It classifies
  elements as `Title`, `ListItem`, `Table`, `NarrativeText`, and
  `UncategorizedText`. Categories are useful, but the Markdown-specific cleanup
  is still missing.

This is why the native parser remains the right default for this corpus. Docling
and Unstructured are better at layout-heavy formats, not at this site's
Markdown conventions.

## Example: DOCX

Run on a small generated DOCX:

```bash
make compare FILE=/tmp/sample.docx
```

```text
native       unsupported
docling      ok   9 items   1 table
unstructured ok   9 items   1 table
```

Docling exports clean Markdown with headings, a table, a numbered list, and a
code block. Unstructured returns the same content as typed elements. Native is
correctly marked unsupported because it only handles Markdown/text.

## Unstructured in more detail

Unstructured is not a document converter in the Docling sense. It is a
**document preprocessor that returns a flat list of typed elements**.

```text
PDF / DOCX / MD / HTML / image
              |
              v
       Unstructured partition
              |
              v
[Title, NarrativeText, ListItem, Table, Image, ...]
```

Each element has a category, text, and metadata. Common categories are `Title`,
`NarrativeText`, `ListItem`, `Table`, `Image`, `FigureCaption`, `Header`,
`Footer`, `PageNumber`, `Address`, `Formula`, and `UncategorizedText`.

The elements are flat. A `Title` is a label on one element, not a section that
owns the elements below it. Some partitioners attach a `parent_id` pointing to
the nearest title, but that is not a guaranteed section tree.

### How it works internally

`partition(filename=...)` detects the file type and routes to a format-specific
partitioner:

- Markdown → converted to HTML → HTML partitioner → NLP classification;
- HTML → lxml/BeautifulSoup parsing → element classification;
- PDF → `fast` reads the text layer, `hi_res` uses layout models and OCR,
  `ocr_only` forces OCR;
- DOCX/PPTX/XLSX → python-docx/python-pptx/openpyxl;
- images → OCR plus layout.

The Markdown path is why frontmatter and Hugo shortcodes show up as ordinary
text: Unstructured does not parse MD semantics, it converts to HTML and
classifies the result.

### Output details that matter

- The `Table` element’s `text` is flattened, but
  `metadata.text_as_html` contains the full `<table>` markup. Use that to
  recover headers and rows.
- PDF elements can carry `page_number`, coordinates, and languages.
- `parent_id` is a useful hint, not a full hierarchy.
- `.category` in Python is serialized as `type` by `to_dict()`.

### Strategies and extras

```text
fast      text layer only, fastest
hi_res    layout model + OCR + table detection
ocr_only  force OCR for scanned documents
auto      choose based on file type and installed extras
```

The base package does not include every format. The lab installs
`unstructured[md,pdf,docx,pptx,xlsx]`. The PDF/image extras pull
`unstructured-inference`, OCR tooling, and model dependencies. `all-docs` also
pulls audio/whisper, which is out of scope.

The OSS library is free to use. The banner shown in the lab advertises the
commercial hosted API, not a limit of the local library. Model weights and OCR
binaries may have their own licenses.

### What it is good and bad at

Good:

- one API for many formats;
- useful element taxonomy for ingestion;
- table HTML metadata and PDF provenance;
- optional OCR and layout strategies;
- `chunk_by_title` helpers.

Weak:

- flat output; you reconstruct sections yourself;
- no frontmatter, shortcode, or site-convention awareness;
- heuristic categories that vary by format and version;
- heavy PDF/image dependency stack;
- the Markdown path is slower and less precise than the native parser.

### How it would fit Helix

Do not feed raw elements into retrieval. Write an adapter:

```text
Unstructured elements -> Document / Section / Block
```

- `Title` → new section;
- `NarrativeText` / `UncategorizedText` → paragraph;
- `ListItem` → grouped list block;
- `Table` → table block from `text_as_html`;
- `Image` / `FigureCaption` → image metadata plus caption;
- preserve page, coordinates, `parent_id`, and filename.

Then the existing chunker and embedder work unchanged. Unstructured is a
candidate adapter for DOCX/PPTX/HTML and possibly PDFs, not the default for this
Markdown corpus.

## The spaCy fallback

On this machine, `en_core_web_sm` fails to deserialize with an `OverflowError`
inside spaCy's tokenizer. The lab therefore detects the failure and gives
Unstructured a blank English pipeline with a sentencizer. The summary records a
warning. Element categories may differ slightly from a normal Unstructured run;
do not use this fallback for a quality benchmark.

The fallback is a lab convenience, not a production decision. For a real
evaluation, pin a working spaCy/model combination in an isolated environment.

## Does this approach make sense for many formats?

Yes, with one correction: do not build the product around one parser.

Use **adapters** behind one stable document model:

| Input | Adapter | Why |
|---|---|---|
| Markdown, text | native parser | fast, deterministic, site conventions |
| PDF (text layer) | Docling | reading order, tables, page layout |
| PDF (scanned), images | OCR + layout, or Docling OCR | text needs to be recovered |
| DOCX, PPTX, ODT | Docling or native office parser | styles, tables, slide structure |
| XLSX, CSV | openpyxl/pandas | sheets and headers, not prose |
| HTML | trafilatura or Docling | main content vs navigation |
| Source code | tree-sitter | functions and classes, not paragraphs |

The common contract stays:

```text
parse_file(path) -> Document
```

Every adapter produces the same `Document` / `Section` / `Block` types, so the
chunker and embedder do not care about the original format. Keep provenance in
block metadata: `page`, `bbox`, `ocr_confidence`, `extraction_method`.

### What to choose in the long run

- **Native Markdown**: default for this corpus. It is faster, deterministic, and
  understands frontmatter, shortcodes, and the site's table conventions.
- **Docling**: default for PDFs and layout-heavy office files. It preserves
  reading order, tables, and page provenance. It is slower and model-heavy.
- **Unstructured**: useful for broad format coverage and quick element typing,
  especially DOCX/PPTX/HTML. Its value is the element taxonomy; its Markdown
  cleanup is weaker than the native parser.

Do not run all three in production. Use one adapter per source type, then
normalize the output. Keep the raw file in MinIO for re-parsing.

### How to decide with evidence

1. Build a small golden set: 10–20 files per format, including tables, code,
   scanned pages, and multi-column PDFs.
2. Compare extraction quality, not just counts: heading recovery, table cell
   accuracy, reading order, text coverage, OCR confidence.
3. Measure cost: seconds per page, memory, model download size, failure rate.
4. Run the downstream retrieval eval. A parser that produces prettier JSON but
   worse retrieval loses.
5. Pin the chosen adapter and model versions per source. Parsers change.

## Limits of this lab

- It compares raw outputs, not normalized retrieval quality.
- Docling on Markdown is not its intended use; the frontmatter/shortcode result is
  expected.
- Unstructured here uses the spaCy fallback.
- Images and scanned PDFs are not tested yet; OCR quality is the real bottleneck
  there.
- No upload UI, size limit, or background job. Those belong in the ingestion
  service, not this script.

## Interview angle

- “I keep parsers behind an adapter interface and normalize to one document
  model, so chunking and retrieval are format-agnostic.”
- “I use the native Markdown parser for this corpus because it understands
  frontmatter and shortcodes; Docling is for layout-heavy PDFs, not for
  re-implementing Markdown.”
- “I compare parsers on a golden set using extraction quality and downstream
  retrieval, not on element counts.”
- “The parser lab is a CLI because model-heavy parsing belongs in a background
  worker, not inside an HTTP request.”
