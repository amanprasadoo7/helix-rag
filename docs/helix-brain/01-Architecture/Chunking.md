---
type: architecture
status: implemented
day: 5
tags: [chunking, ingestion, retrieval, architecture, interview]
related: ["[[Ingestion-M1]]", "[[Parsing]]", "[[ACL-Classification]]", "[[Evaluation-101]]", "[[Checklist]]", "[[Project-Map]]", "[[2026-10-29]]"]
---

# Chunking: cutting documents into searchable cards

**Short answer:** The chunker cuts each parsed section into small cards that can
be searched independently. Each card keeps its heading path, never crosses into
another section, and never splits a code block. Tables stay whole while they fit;
a table larger than the budget is split by rows with the header repeated. The
section itself is kept as a larger **parent** so the answer step still has enough
context.

This note is the 1.3 design and implementation. The chosen rule is **one small
card per section**; short sections are allowed to stay small.

## Where chunking fits

```text
raw Markdown
   -> parser: headings, paragraphs, tables, code
   -> ACL: who may see the document
   -> chunker: small searchable cards          <-- this note
   -> embedder: numeric fingerprints
   -> vector store: searchable index
   -> chat: retrieve cards, then answer
```

The parser already understands the document. The chunker decides the **unit of
retrieval**. If that unit is wrong, no amount of prompt engineering fixes it.

## The index-card analogy

You have 2,500 books and one librarian. You cannot hand a visitor the whole
library, so you write index cards:

- one card per topic, not one card per book;
- enough text to be useful on its own;
- the chapter name written at the top;
- no card cut through the middle of a table.

When a question arrives, the librarian finds the best cards and puts them on the
desk. The visitor never sees the rest of the library.

A **chunk** is one card. The **breadcrumb** is the chapter name at the top.

## Why not cut every 500 words?

Fixed-size cutting ignores meaning. It produces cards that:

- start in the middle of a sentence;
- contain the end of one topic and the start of another;
- cut a table or command in half;
- forget which heading they belong to.

Those cards are hard to match and hard to cite. We cut along the document's own
structure instead.

## What makes a good chunk

| Property | Meaning |
|---|---|
| Focused | One topic, not three |
| Self-contained | Understandable without the previous page |
| Unbroken | Table rows and code are not cut |
| Traceable | Source path and heading are known |
| Right-sized | Not one sentence, not a whole chapter |

## Chunking strategies

| Strategy | How it cuts | Good | Weakness here |
|---|---|---|---|
| Fixed size | Every N characters or tokens | Simple and predictable | Cuts sentences, tables, and code; ignores headings |
| Sliding window | Fixed size, repeating the tail | Keeps continuity | Still ignores structure; more storage |
| Paragraph or sentence | At blank lines or full stops | Natural boundaries | A long table stays huge; tiny paragraphs stay tiny |
| Recursive character | Tries large separators, then smaller ones | General-purpose; common default | Does not know typed blocks or the heading tree |
| Heading or structure-aware | At headings, keeping blocks together | Fits documentation | Very short sections become small chunks |
| Semantic | Embeds sentences and cuts where meaning changes | Adapts to content | Costly, non-deterministic, unnecessary when headings exist |
| Parent-child | Searches small children, returns the parent | Precise search plus context | More storage and a little more complexity |
| LLM or agentic | Asks a model where to cut | Flexible | Slow, costly, non-deterministic; not enforceable |

Helix uses **structure-aware chunking with parent and child records**:

- the **parent** is the parsed section, kept for context;
- the **child** is the card that is embedded and searched;
- retrieval finds a child, then expands to the parent section.

## The corpus is already finely sectioned

The parsed corpus has 37,610 sections. Their own text, excluding child sections,
is distributed like this:

| Sections | Median | p75 | p90 | p95 | p99 | Over 300 words |
|---:|---:|---:|---:|---:|---:|---:|
| 37,610 | 55 words | 114 | 203 | 290 | 567 | 4.6% |

Most sections are already smaller than a target card. That changes the job:

- the chunker is mostly **packing blocks and preserving structure**;
- splitting only happens for the long tail;
- a strict minimum size would force unrelated sections together, which hurts
  citation precision.

This is why the chosen rule is one card per section, not merge-until-large.

## How the chunker works

1. Load one parsed document.
2. Walk its sections in order.
3. Collect each section's own blocks. Child sections get their own cards.
4. If the section fits the budget, emit one child. No overlap.
5. If it does not fit, pack whole blocks into children up to the target size.
6. Split a paragraph, list, or quote only at sentence or item boundaries.
7. Keep code whole. Keep a table whole while it fits; a larger table is split by
   rows with the header repeated, so no row or field name is lost.
8. If one table row is itself over the hard maximum, keep that row whole and flag
   it `oversize`.
9. When a section is split, repeat the last sentence or block from the previous
   child at the start of the next one. This is the overlap.
10. Prepend the breadcrumb and section title to the embedding text.
11. Write the parent record with its child ids, and the children with their
    parent id.
12. Save deterministic JSON under `data/chunks` plus a `summary.json`.

## Technical contract

| Decision | Value | Reason |
|---|---|---|
| Child scope | Inside one section only | Keeps topics separate and citations precise |
| Target size | 200-400 tokens, about 150-300 English words | Small enough to search, large enough to mean something |
| Hard maximum | About 400 words per prose child | Avoids oversized embeddings |
| Overlap | 10-15%, about 20-40 words | The next card knows what came before |
| Overlap boundary | Sentence or block boundary | Avoids cutting mid-sentence |
| Tables | Whole while they fit; row groups with a repeated header after that | A large table is still searchable; a half row is not |
| Code | Whole | Half a command is dangerous |
| Oversized block | Keep and flag `oversize` | Better a large card than a broken one |
| Breadcrumb | Included in embedding text | "Accounts" is ambiguous; "Zuora > Accounts" is not |
| Chunk id | UUID5 of source, path, section id, content hash | Unchanged text keeps a stable id |
| Ordinal | Position in the document | Keeps output ordered and inspectable |
| Output | `data/chunks/<source>/<path>.json` plus `summary.json` | Mirrors the parser and is easy to inspect |
| ACL | Not copied in the chunker | The document owns permissions; storage attaches them later |
| Timestamp | None | Two runs over the same input must be identical |

Word counts are the proxy for tokens in 1.3: one English word is about 1.3
BGE-M3 tokens. The real tokenizer is available in 1.4, before anything is
stored, so the estimate can be validated there without re-indexing.

## Implementation

| Piece | Purpose |
|---|---|
| `packages/helix/chunking.py` | Models, block packing, ordering, overlap, ids |
| `scripts/chunk_corpus.py` | Manifest -> parsed JSON -> `data/chunks` + summary |
| `make chunk` | Full corpus |
| `make chunk-sample` | Five evenly spaced documents, one line each |
| `tests/test_chunking.py` | 14 tests for size, overlap, tables, code, ids, determinism |

## Worked examples

These examples come from the parsed Zuora Collect guide in the real corpus.

### A good short section

Heading: `How to assign Agents to an account?`

The section is 77 words and becomes one child:

```text
breadcrumb: Zuora Collect module > FAQ > How to assign Agents to an account?

For a video tutorial, click here.
Open the Collections Window and click on the Accounts tab.
Search for the account that needs to be assigned and open it...
The collections agent for the account is displayed on the top left...
Click the agent name or Unassigned.
Select an agent from the dropdown list.
Click Update to save the settings.
Refresh the page to see the changes.
```

It is focused on one procedure, self-contained, and directly answers "How do you
assign a collections agent?". Splitting it would make both halves worse.

### A very small section

Heading: `How to edit a comment?`

The section is 8 words and becomes one child:

```text
breadcrumb: Zuora Collect module > FAQ > How to edit a comment?
text: Comments cannot be edited or deleted by design.
```

This is far below the target, but it is the correct answer to "Can comments be
edited or deleted?". The breadcrumb supplies the topic. That is the accepted
trade-off of rule A.

### A long section that must be split

Heading: `Accounts`

The section is 356 words, about 460 tokens, so it becomes two children:

**Child 1**, about 156 words, ends with:

```text
Manage accounts in collections
Click on an account name to view the details of the account...
On this page, the user can perform the following operations:
```

**Child 2**, about 200 words, starts with the overlap and keeps the long list
whole:

```text
On this page, the user can perform the following operations:   <-- overlap
Assign collections agents to accounts...
View contact details of the account...
Update the collection status of this account...
View invoice details, payments, or retry status...
Enter comments regarding the particular account...
The user can add or reply to comments... Comments cannot be edited or deleted by design.
```

Both children keep the breadcrumb:

```text
Zuora Collect module > Business Solution > How to use Zuora Collect > Collections Window > Accounts
```

The **parent** is the whole `Accounts` section, so a search that finds child 1
can still return the full section to the answer step.

### What a bad split would look like

A fixed 250-word cutter might produce a card containing the end of "Business
Solution" and the start of "Collections Window", followed by a card that starts
inside the 163-word Accounts list and ends in "Invoices". That card is about two
topics and is cut mid-list. Structure-aware chunking avoids it.

## How retrieval uses the cards

| Question | Matching child | What is returned |
|---|---|---|
| How do you assign an agent to an account? | The 77-word procedure card | That section |
| When is an account considered "In Collections"? | Child 1 of `Accounts` | The full `Accounts` parent |
| Can comments be edited or deleted? | The 8-word FAQ card | That card |

This is the point of parent and child records: search stays precise, while the
model still receives enough context.

## Current result

| Measure | Value |
|---|---:|
| Documents | 2,500 |
| Sections / parents | 37,614 |
| Children | 38,165 |
| Source words | 3,447,243 |
| Child words | 3,475,366 |
| Overlap words | 25,092 |
| Size p50 / p90 / p95 / p99 | 66 / 213 / 244 / 384 words |
| Children under 100 words | 25,040 (66%) |
| Oversize children | 78 (34 code blocks, 44 single-row tables) |
| Largest child | 2,174 words, a code block (~2,800 tokens) |
| Documents without chunks | 26 (empty pages) |
| Runtime | ~8 seconds |
| Output size | ~137 MB |
| Deterministic rerun | Yes, identical SHA-256 tree |

The median child is 66 words, not 250. That is the expected consequence of rule
A: the corpus has many short FAQ and reference sections, and they stay small so
their citations remain exact. The large sections still split; the `Accounts`
example below is 156 and 210 words with a 10-word overlap.

The 78 oversize children are all under the BGE-M3 context window. Code blocks are
kept whole by design, and the large tables are ones where a single row (usually
a field plus a long description) exceeds 400 words. Splitting that row would
separate the field name from its description, so it stays whole and is flagged.

## Validation

The full-corpus run reports:

- 2,500 documents, 37,614 parents, 38,165 children;
- p50 66, p90 213, p95 244, p99 384, max 2,174 words;
- 25,040 children under 100 words;
- 78 oversize children, all from code blocks or single giant table rows;
- zero children crossing a section boundary;
- zero split code blocks; every split table repeats its header and keeps rows
  whole;
- byte-identical output across two runs;
- manual inspection of the Zuora guide and the long engineering/reference pages.

## What the chunker does not do

- It does not call an LLM.
- It does not use semantic chunking; the headings already carry structure.
- It does not split code blocks.
- It does not split a table row; a giant row is kept whole and flagged.
- It does not assign ACLs; permissions belong to the document.
- It does not embed anything; that is 1.4.
- It does not merge small sections; that was option B and was rejected for now.

## Why rule A instead of merging small sections

Merging adjacent small sections would produce denser embeddings, but the card
would span several headings. A citation would then point at a card covering
multiple FAQ answers, which is harder to verify and explain. The corpus is
documentation with meaningful headings, so precision is worth more than uniform
card size. If retrieval evaluation later shows that tiny cards are being missed,
merging can be revisited with evidence.

## Interview angle

- "I chunk along the document's own heading tree so retrieval units match topics,
  not arbitrary token counts."
- "The corpus median section is 55 words, so I do not force a 300-token floor;
  I preserve citations and validate the size distribution instead."
- "Code is atomic, and tables split only by whole rows with the header repeated.
  I would rather flag one oversized row than lose the field name."
- "Child chunks are for matching; parent sections are for generation context."
- "Chunk ids are content-addressed, so an unchanged chunk keeps its id when its
  neighbours change."
