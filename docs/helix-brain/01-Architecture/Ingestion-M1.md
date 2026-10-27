---
type: architecture
status: active
day: 4
tags: [ingestion, roadmap, parsing, acl, chunking, embeddings, qdrant, interview]
related: ["[[Parsing]]", "[[Document-Normalization]]", "[[Parser-Lab]]", "[[ACL-Classification]]", "[[Corpus]]", "[[Storage-Layers]]", "[[Project-Map]]", "[[Checklist]]", "[[Roadmap-Review]]", "[[2026-10-27]]"]
---

# Ingestion M1: from Markdown to a searchable index

**Short answer:** M0 built the building and the shelves. M1 fills them. It turns
the frozen Markdown corpus into structured, permission-labelled, embedded chunks,
stores those chunks in Qdrant and Postgres, and automates the whole flow with an
idempotent worker.

> [!info] Status
> Checkpoint 1.1 is verified. Checkpoint 1.2 is implemented and awaiting user
> verification. Checkpoints 1.3–1.6 are the plan, not built yet. The 1.2 design
> and implementation are in [[ACL-Classification]]; 1.5b adds the MinIO snapshot.
> This note is updated as each checkpoint lands.

## The library analogy

You have 2,500 books and no librarian.

| Step | Book analogy | Helix |
|---|---|---|
| 1.1 Parser | Read each book and build a clean table of contents | Markdown → structured JSON |
| 1.2 ACL | Stick a label on each book: HR only, engineers, public | Path → classification + roles |
| 1.3 Chunker | Cut each book into index cards small enough to search | Sections → parent/child chunks |
| 1.4 Embedder | Turn each card into a numeric fingerprint of its meaning | BGE-M3 dense + sparse vectors |
| 1.5 Storage | Put fingerprints in the smart index and card details in the catalog | Qdrant + Postgres |
| 1.5b Archive | Photograph the original shelves so they can be rebuilt later | MinIO raw + manifest |
| 1.6 Worker | Build the assembly line, and remove cards when a book is deleted | ARQ + reconcile |

The order is deliberate. Permissions must be known before chunks are stored, and
chunks must exist before they can be embedded or indexed.

```text
raw docs -> structure -> permission labels -> small chunks -> vectors -> stores -> automated pipeline
```

## The pipeline at a glance

```text
manifest
   |
   v
1.1 parser ------> parsed JSON (one file per document)
   |
   v
1.2 ACL ---------> classification + allowed roles
   |
   v
1.3 chunker -----> parent section + child chunks
   |
   v
1.4 embedder ----> dense 1024 + learned sparse
   |
   v
1.5 stores ------> Qdrant payload + Postgres chunk map
   |
   v
1.5b snapshot ---> MinIO raw + manifest, SHA-256
   |
   v
1.6 worker ------> add/update/delete, rerun is a no-op
```

---

## 1.1 Parser

**In plain language.** Read one Markdown file and produce a structured outline:
title, headings, paragraphs, lists, tables, and code blocks. A `## Accounts`
heading becomes a section, and the table below it becomes a table block inside
that section.

**Technically.** Emit one deterministic JSON document per file using `Document`,
`Section`, and `Block` models. Sections form a tree with breadcrumbs and unique
ids. Blocks carry normalized `text` for retrieval and `raw` for debugging. This
is the stable interface between raw Markdown and every later stage.

**Why first.** If the structure is wrong here, every chunk and every citation
inherits the mistake.

**Example.** The Zuora page becomes a root document titled “Zuora Collect
module”, with child sections such as “Accounts”, and the account-status table
stored as a typed table block rather than prose.

More detail: [[Parsing]]. The choice of a native parser over Docling is in
[ADR 0001](../../adr/0001-markdown-parser.md).

---

## 1.2 ACL classifier

**In plain language.** Decide who may see each document based on where it came
from. A public product page is open to any logged-in user; an engineering runbook
needs an engineering badge; HR, finance, legal, and security each have their own
locked room. An unknown path gets no badge at all.

| Source and path | Classification | Allowed roles |
|---|---|---|
| `gitlab-docs:doc/**` | `public:docs` | `authenticated` |
| `handbook:content/handbook/security/**` | `restricted:security` | `security`, `admin` |
| `handbook:.../people-group/**`, `people-policies/**`, `hiring/**`, `total-rewards/**`, `labor-and-employment-notices/**` | `confidential:hr` | `hr`, `legal`, `security`, `admin` |
| `handbook:.../finance/**`, `acquisitions/**` | `confidential:finance` | `finance`, `legal`, `security`, `admin` |
| `handbook:.../legal/**`, `board-meetings/**` | `confidential:legal` | `legal`, `security`, `admin` |
| `handbook:.../engineering/**`, `support/**`, `product/**`, `product-development/**`, `solutions-architects/**`, `it/**`, `tools-and-tips/**` | `internal:eng` | `engineer`, `support`, `security`, `admin` |
| `handbook:.../marketing/**`, `sales/**`, `customer-experience/**`, `eta/**`, `company/**`, `leadership/**`, `communication/**`, `upstream-studios/**`, `enterprise-data/**`, `resellers/**`, `about/**`, `entity/**`, `values/**`, `business-technology/**`, `_index.md` | `internal:company` | `employee`, `admin` |
| anything unmatched | `restricted:unknown` | none, deny |

Roles are additive sets. `authenticated` is the public sentinel, `employee` is
the internal baseline, and functional roles are added on top. A user can have
several roles, and the document is allowed if any role intersects the allow list.
`billing` is an alias for `finance`; the matcher always sees `finance`.

These permissions are synthetic. The source content is public; the demo layers a
plausible organisation and sensitivity model on top. `project:atlas` is deferred:
there are no tag overrides in v1.

**Technically.** A deterministic source-and-path rule table maps each parsed
document to `classification` and `allowed_roles`. Matching is boundary-safe and
longest-prefix first; unknown paths default to deny, never public. Each decision
records `rule_id`, `matched_prefix`, and `reason`, plus a top-level
`policy_version`. The output is a sidecar index under `data/acl`, not a mutation
of the parsed JSON, so the corpus can be reclassified without re-parsing.

Tests cover source distinction, prefix boundaries, longest-prefix precedence, the
path × role matrix, unknown deny, duplicate `(source, path)` keys, and full
corpus coverage. The result is later copied into the Qdrant payload, where it
becomes a **pre-filter applied before vector search**, not a prompt instruction.

**Built.** `packages/helix/acl.py` holds the policy and matcher;
`scripts/classify_corpus.py` writes `data/acl/index.json` and
`data/acl/summary.json`; `make classify` and `make classify-sample` run it. The
full run classified 2,500 documents with zero unknown paths, and the output is
deterministic across runs because it records the manifest SHA-256 instead of a
timestamp.

**Why here.** Permissions must exist before chunks are written. Retrofitting ACLs
after indexing means every stored chunk is temporarily unsafe.

The full explanation, role model, and the `business-technology` correction are in
[[ACL-Classification]].

---

## 1.3 Chunker

**In plain language.** Split a long page into index cards of roughly 200–400
tokens, but keep related things together. A table or code block should not be
cut in half. Small child chunks are good for finding; the larger parent section
is kept so the model gets enough context.

**Technically.** Structure-aware parent/child chunking:

- parent = a section from the parser;
- child = 200–400 tokens with 10–15% overlap;
- breadcrumb (`Handbook > Finance > Zuora > Accounts`) prepended to embedding text;
- tables and code kept whole;
- deterministic chunk ids and ordinals;
- inspect the chunk-size distribution before moving on.

**Why here.** The parser gives sections; the chunker chooses the actual retrieval
unit. Parent/child keeps retrieval precise without starving generation of context.

---

## 1.4 Embedder

**In plain language.** Turn each chunk into a numeric fingerprint so that “reset
my password” and “password recovery steps” land near each other even though the
words differ. Exact terms such as error codes and version numbers also need to
match, so produce two views: meaning (dense) and exact words (sparse).

**Technically.** BGE-M3 produces a 1024-dimension dense vector plus learned
sparse weights. Run in batches, cache by content hash, measure throughput on 10
chunks, and keep it local so there is no per-query API cost.

**Why here.** You can only embed what the chunker produced, and you can only
store what the embedder produced.

---

## 1.5 Qdrant + Postgres metadata

**In plain language.** Put the fingerprints into a smart search index (Qdrant)
and the catalog information into Postgres. Qdrant answers “which chunks are
semantically near this question?” Postgres answers “which document is this, what
section, what hash, what parent, when was it ingested?”

**Technically.**

- Qdrant collection `chunks_bge_m3_v1` with named vectors `dense` and `sparse`;
- payload: tenant, document, chunk, parent, classification, roles, source/path,
  section path, content hash, embedding model/version/dimension;
- deterministic point ids, for example UUID5 of `document:ordinal:content_hash`;
- Postgres holds the document/chunk map and parent-child relationships, managed
  by Alembic from the first table;
- unique constraints on `(source, path)` for documents and
  `(document_id, ordinal)` for chunks, plus foreign keys and a content-hash index;
- `tenant` is a reserved field with the local value `default`; the system is
  single-tenant until a tenant table and isolation test exist;
- verify counts and fetch 100 chunks by id.

**Why both.** The vector database is an index, not the source of truth. Postgres
is where you join, audit, and explain. The collection name includes the embedding
model version because vectors from different models must never be mixed.

---

## 1.5b MinIO raw + manifest snapshot

**In plain language.** Take a photograph of the exact shelves that were indexed.
If the source repository disappears, or a parser change needs the original bytes,
the snapshot is still there. The raw corpus and manifest are small enough to
archive; parsed output is optional because it can be regenerated.

**Technically.**

- bucket `helix-corpus`;
- keys `raw/<source>/<commit>/<path>` and
  `manifests/<source>/<commit>.json`;
- optional `parsed/<source>/<commit>/<parser_version>/<path>.json`;
- record SHA-256 in object metadata and reject a different payload under the same
  immutable key;
- re-uploading the same commit and checksum is a no-op;
- verify by downloading one raw file and one manifest and comparing hashes.

**Why after 1.5.** MinIO is not required to make retrieval work, so it must not
block the first searchable index. It is still a real S3-compatible archive, and
the same code works against AWS S3 or Cloudflare R2. The checkpoint is `1.5b`
rather than a new phase because it is one focused concern.

---

## 1.6 Worker + full ingest + reconcile

**In plain language.** Build the assembly line that runs the whole pipeline over
all 2,500 documents in the background. If nothing changed, a second run should do
nothing. If a document is deleted upstream, its chunks must disappear.

**Technically.**

- ARQ worker backed by Redis;
- job key = source + commit + config hash;
- config hash includes parser, ACL policy, chunker, and embedding-model versions,
  so a policy or model change forces the right work;
- content-hash diff detects added, changed, and deleted documents;
- add/update/delete, with tombstones for removals;
- bounded retries with backoff, a dead-letter queue, a job record in Postgres, and
  a lock per ingest run;
- idempotent rerun: the second run reports zero work;
- verify counts, sample retrieval, and the ACL invariant after each run;
- integration test against the live stack.

**Why last.** It orchestrates the other five steps, so it is the only checkpoint
that can prove the whole pipeline is correct and repeatable.

---

## Technical summary

| Step | Input → output | Main technology | Main failure to test |
|---|---|---|---|
| 1.1 | Markdown → structured document JSON | Pydantic, native parser | lost headings, tables, or code |
| 1.2 | document → classification + roles | source/path rule table | unknown path leaking as public |
| 1.3 | document → parent/child chunks | structure-aware chunker | chunk crosses a heading or splits a table |
| 1.4 | chunk → dense + sparse vectors | BGE-M3 | wrong dimensions, slow batches |
| 1.5 | chunks → Qdrant points + Postgres rows | Qdrant, Postgres | id/count drift, missing payload |
| 1.5b | raw corpus + manifest → S3 objects | MinIO, SHA-256 | duplicate keys, checksum drift |
| 1.6 | corpus → indexed, reconciled store | ARQ, Redis, hashes | rerun duplicates, deletes not propagating |

## End-to-end example

Question: “When does an account move to Collections?”

1. **Parser** finds the `Accounts` section and the status table.
2. **ACL** labels the page `internal:company`, visible to employees and admins.
3. **Chunker** creates a child chunk such as “An account is moved to Collections
   when the total invoice balance is more than zero and at least one invoice is
   past due.” The child points to the `Accounts` parent.
4. **Embedder** turns the child into one dense vector and one sparse vector.
5. **Storage** writes the vectors plus ACL, path, section, and hash to Qdrant,
   and the document/chunk rows to Postgres.
6. **Snapshot** archives the raw Markdown and manifest in MinIO with checksums.
7. **Worker** performs those steps for the whole corpus, then a second run
   reports no changes.
8. **Query time** applies the `internal:company` filter before search, retrieves
   the child, expands to the parent, and cites the source path and section.

## M1 exit criteria

- 2,500 documents parsed and indexed.
- Every stored chunk carries classification and allowed roles.
- The raw corpus and manifest are archived in MinIO with matching SHA-256 values.
- A second full ingest is a no-op.
- Deleting one upstream document removes its chunks from both stores.
- Qdrant and Postgres counts agree.
- A sample query returns the expected chunks with valid citations.
- Chunk-size distribution is sane and embed throughput is measured.

---

## What was built in 1.1, step by step

1. **Decided scope and wrote an ADR.** The corpus is Markdown-only, so a native
   parser is enough. Docling is deferred until a PDF or HTML source appears.
   Recorded in [ADR 0001](../../adr/0001-markdown-parser.md).
2. **Designed the document model** in `packages/helix/parsing.py`:
   - `Document`: source, path, commit, title, frontmatter, root, stats, warnings;
   - `Section`: heading level, title, id, breadcrumb, blocks, children;
   - `Block`: type, normalized text, raw source, type-specific metadata.
3. **Parsed frontmatter** with PyYAML and converted values to JSON-safe types.
   Title fallback: frontmatter title → first H1 → filename. If the first H1
   supplied the title, it is not duplicated as a child section.
4. **Built the heading tree.** Headings outside code fences create sections;
   breadcrumbs and duplicate anchors (`install`, `install-1`) are generated.
5. **Built the block scanner:**
   - fenced code first, so `#` inside code is never a heading;
   - tables with separator detection, escaped pipes, and pipes inside
     shortcodes or inline code protected;
   - ordered and unordered lists with nested levels and continuations;
   - blockquotes and `[!warning]` callouts;
   - paragraphs with inline normalization;
   - HTML flattened to text.
6. **Normalized inline Markdown:** links become labels, images become alt text,
   emphasis disappears, inline code is protected from the HTML and emphasis
   passes, entities are decoded, and spacing around punctuation is cleaned.
7. **Handled Hugo shortcodes:** remove the `{{< ... >}}` tokens but keep wrapped
   content; map `yes` and `no` to text; keep tab titles; count what was removed.
8. **Wrote the CLI** `scripts/parse_corpus.py` and added `make parse` and
   `make parse-sample`. It reads the manifest, filters or evenly samples entries,
   writes one JSON file per source document, and a `summary.json` with failures
   and warnings.
9. **Wrote 13 unit tests** covering frontmatter, title fallback, heading tree,
   duplicate slugs, code fences, code inside lists, tables, lists, callouts,
   shortcodes, HTML, determinism, warnings, and file reading.
10. **Ran the full corpus and fixed real bugs found there:**
    - false “unclosed fence” warnings because fences inside list items were
      swallowed by the list parser;
    - table pipes inside shortcode attributes split cells;
    - a trailing `#` in a heading such as `C#` was being eaten.
11. **Final result:** 2,500 documents, 37,614 sections, 113,255 blocks, 12,408
    code blocks, 7,280 tables, zero failures, 26 warnings for pages whose only
    content is a dynamic shortcode, about 13 seconds, and about 122 MB of output.
12. **Updated the notes and process:** [[Parsing]], the ADR, journal, checklist,
    [[Project-Map]], README, and generated `docs/theory.html`. `make ci` is green:
    50 passed, 1 deselected.
13. **Committed** as `5516156 feat(parser): normalize Markdown into structured JSON`.

## Common doubts

### Why not let the chunker parse Markdown?

Because then every consumer re-implements fence, table, and heading rules. One
parsed artifact also makes it possible to inspect exactly what the next stage
received.

### Why ACL before chunking?

Because chunks are what get stored and retrieved. If permissions are added later,
there is a window where the index contains chunks with no enforceable label.

### Why parent and child chunks?

The child is small enough for precise semantic search. The parent gives the
generator enough surrounding context. Keeping both avoids choosing between
precision and answer quality.

### Why use Qdrant and Postgres?

Qdrant finds nearest vectors; Postgres stores truth, joins, hashes, and audit
data. Treating the vector store as the database of record makes reconciliation
and auditing much harder.

### Why MinIO if the corpus can be re-fetched?

Re-fetching depends on the upstream repository still serving the pinned commit.
The snapshot makes the demo self-contained, gives us original bytes for a parser
change, and exercises the same S3 interface used in production. It is a
convenience and a recovery path, not a replacement for Postgres truth.

### Why must a second ingest be a no-op?

Real pipelines rerun. Without content hashes and idempotent writes, every rerun
duplicates data, inflates counts, and makes deletion impossible to reason about.

## Interview angle

- “I parse Markdown once into a document model so the chunker and retriever share
  one interpretation of headings, lists, code, and tables.”
- “ACLs are metadata applied before vector search, not a sentence in the prompt.
  The security invariant is zero unauthorized chunks in the context.”
- “The ACL rule is deterministic and source-aware. It records which rule and
  prefix matched, so a misclassification is auditable.”
- “I use parent/child chunking: small children for retrieval, the parent section
  for generation, and a breadcrumb for both context and citations.”
- “BGE-M3 gives me dense and sparse vectors from one model, so hybrid retrieval
  does not need a separate BM25 pipeline.”
- “The ingest worker is hash-based and idempotent: rerunning unchanged data is a
  no-op, and deletions propagate as tombstones.”
- “I archive the exact raw commit and manifest in S3-compatible storage with
  checksums, so a parser or embedding change can rebuild without depending on the
  upstream repository.”
