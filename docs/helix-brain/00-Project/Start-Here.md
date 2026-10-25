---
type: guide
status: active
day: 3
tags: [process, navigation, docs]
related: ["[[Checklist]]", "[[Project-Map]]", "[[Study-Guide]]", "[[2026-10-25]]", "[[Ingestion-M1]]", "[[Parsing]]", "[[Document-Normalization]]", "[[Parser-Lab]]", "[[Foundations]]", "[[Compose-Stack]]", "[[Storage-Layers]]", "[[Evaluation-101]]"]
---

# Start here

**Short answer:** Helix is a permission-aware RAG service over a pinned snapshot
of the public GitLab handbook and product docs. This note is the entry point to
the vault: it tells you what is current, what to read first, and where to write.

## Current state

> [!info] Checkpoint 1.1
> The Markdown parser is implemented and committed. It converts 2,500 pinned
> documents into structured JSON. User verification is still pending, so
> checkpoint 1.2 has not started.

The repo has a working API skeleton, local services, a pinned corpus, and a
parser. It does not yet have ACL classification, chunking, embeddings, retrieval,
generation, auth, or a UI.

Use `make checklist` for the live status. The checklist, not this note, is the
source of truth for the active checkpoint.

## Read first

| If you want to... | Read |
|---|---|
| Know what is in scope right now | [[Checklist]] |
| Understand the whole system | [[Project-Map]] |
| Work on the vault or generated guide | [[Study-Guide]] |
| See the latest build log | [[2026-10-25]] |
| Understand the next milestone | [[Ingestion-M1]] |

## Reading paths

### New to the project

1. [[Checklist]] for the current checkpoint and handoff rules.
2. [[Project-Map]] for the repo layout and target architecture.
3. [[Foundations]] for the Python, async, config, and Makefile foundations.
4. [[Compose-Stack]] and [[Storage-Layers]] for the local services.

### Understand ingestion

1. [[Ingestion-M1]] for the full M1 pipeline.
2. [[Parsing]] for the document model and parser.
3. [[Document-Normalization]] for format adapters and correctness checks.
4. [[Parser-Lab]] for the native vs Docling vs Unstructured comparison.

### Prepare for interviews

1. [[Project-Map]] for the architecture story.
2. [[Foundations]] and [[Compose-Stack]] for engineering choices.
3. [[Storage-Layers]] for why Postgres, Redis, Qdrant, and MinIO each exist.
4. [[Parsing]] and [[Document-Normalization]] for ingestion trade-offs.
5. [[Evaluation-101]] for how quality is measured.

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
