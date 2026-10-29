---
type: guide
status: active
day: 4
tags: [process, navigation, docs]
related: ["[[Checklist]]", "[[Project-Map]]", "[[Study-Guide]]", "[[Roadmap-Review]]", "[[ACL-Classification]]", "[[Chunking]]", "[[2026-10-25]]", "[[2026-10-27]]", "[[2026-10-29]]", "[[Ingestion-M1]]", "[[Parsing]]", "[[Document-Normalization]]", "[[Parser-Lab]]", "[[Foundations]]", "[[Compose-Stack]]", "[[Storage-Layers]]", "[[Evaluation-101]]"]
---

# Start here

**Short answer:** Helix is a permission-aware RAG service over a pinned snapshot
of the public GitLab handbook and product docs. This note is the entry point to
the vault: it tells you what is current, what to read first, and where to write.

## Current state

> [!info] Checkpoint 1.3
> The parser (1.1) and ACL classifier (1.2) are verified; the ACL design and
> results are in [[ACL-Classification]]. The chunker (1.3) is implemented and
> awaiting user verification; the design and results are in [[Chunking]]. The
> roadmap review adds 1.5b MinIO archive, 1.7 eval seed expansion, and 2.0
> identity context.

The repo has a working API skeleton, local services, a pinned corpus, a parser,
and a deterministic ACL sidecar. It does not yet have chunking, embeddings,
retrieval, generation, auth, or a UI. MinIO is running but its archive checkpoint
is 1.5b.

Use `make checklist` for the live status. The checklist, not this note, is the
source of truth for the active checkpoint.

## Read first

| If you want to... | Read |
|---|---|
| Know what is in scope right now | [[Checklist]] |
| Understand the whole system | [[Project-Map]] |
| Work on the vault or generated guide | [[Study-Guide]] |
| See the latest build log | [[2026-10-29]] |
| Understand the next milestone | [[Ingestion-M1]] |
| Review roadmap gaps and ordering | [[Roadmap-Review]] |
| Understand who may see each document | [[ACL-Classification]] |
| Understand how documents become searchable pieces | [[Chunking]] |

## Reading paths

### New to the project

1. [[Checklist]] for the current checkpoint and handoff rules.
2. [[Project-Map]] for the repo layout and target architecture.
3. [[Foundations]] for the Python, async, config, and Makefile foundations.
4. [[Compose-Stack]] and [[Storage-Layers]] for the local services.

### Understand ingestion

1. [[Ingestion-M1]] for the full M1 pipeline.
2. [[Parsing]] for the document model and parser.
3. [[ACL-Classification]] for the permission model and 1.2 design.
4. [[Chunking]] for the retrieval unit and the 1.3 design.
5. [[Document-Normalization]] for format adapters and correctness checks.
6. [[Parser-Lab]] for the native vs Docling vs Unstructured comparison.

### Prepare for interviews

1. [[Project-Map]] for the architecture story.
2. [[Foundations]] and [[Compose-Stack]] for engineering choices.
3. [[Storage-Layers]] for why Postgres, Redis, Qdrant, and MinIO each exist.
4. [[Parsing]], [[ACL-Classification]], [[Chunking]], and
   [[Document-Normalization]] for ingestion trade-offs.
5. [[Evaluation-101]] for how quality is measured.
6. [[Roadmap-Review]] for the gaps and ordering decisions.

### Continue implementation

1. [[Checklist]] for the active checkpoint.
2. [[Ingestion-M1]] for the milestone plan.
3. The concept note for the current step.
4. The latest journal entry for what changed and what remains.

## How the vault is organized

- Four top-level folders: project, architecture, evaluation, and journal.
- Keep notes flat inside those folders for now. Use links, tags, and maps of
  content instead of deeper folders.
- Add architecture subfolders only when the folder reaches roughly 15–20 notes
  or has three stable subdomains.
- See [[Study-Guide]] for the note contract, tag conventions, generator
  constraints, and the subfolder rule.

## Working agreement

- The agent implements, tests, documents, and commits.
- The user runs the manual test and replies `pass`.
- Only the user marks `User verified`. A checkpoint is not done before that.
- Run `make ci` before every commit.
