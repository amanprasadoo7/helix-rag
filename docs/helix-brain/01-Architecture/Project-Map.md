---
type: architecture
status: active
day: 2
tags: [architecture, repo, roadmap, retrieval, security, interview]
related: ["[[Start-Here]]", "[[Checklist]]", "[[Roadmap-Review]]", "[[ACL-Classification]]", "[[Foundations]]", "[[Compose-Stack]]", "[[Corpus]]", "[[Parsing]]", "[[Document-Normalization]]", "[[Parser-Lab]]", "[[Ingestion-M1]]", "[[Storage-Layers]]", "[[Evaluation-101]]", "[[Tracing-a-Document]]"]
---

# Project map: the repo and the architecture behind it

**Short answer:** Helix is a permission-aware RAG service over a pinned snapshot
of the public GitLab handbook and product docs. The repo is organized around one
idea: keep the data pipeline, the retrieval logic, the agent, and the evaluation
harness separate enough to test them independently, but small enough for one
person to understand and run.

Think of it as a staffed research library:

| Library | Helix |
|---|---|
| Books and manuals | The GitLab corpus |
| Catalog and checkout records | Postgres metadata and ACLs |
| Shelf index for finding passages | Qdrant vectors |
| Archive room for original documents | MinIO object storage |
| Work queue at the front desk | Redis jobs and cache |
| Librarian who answers questions | Retrieval + agent pipeline |
| Quality review after an answer | Evals and security gates |

> [!info] Current state
> Checkpoint 1.1 is verified; 1.2 ACL classification is implemented and awaiting
> user verification. The repo has a working API skeleton, local services, a
> pinned corpus, a Markdown parser that emits structured JSON, a deterministic
> ACL sidecar, and a docs/eval seed. It does **not** yet have chunking,
> embeddings, retrieval, generation, auth, or a UI. MinIO is running but its
> archive checkpoint is 1.5b. This note explains the target architecture and
> marks what exists now.

## What lives where

| Path | What it is | Why it exists |
|---|---|---|
| `apps/api` | FastAPI entrypoint and local dev server | The HTTP boundary: health now, chat and admin later |
| `packages/helix` | Shared domain code | Keeps config, corpus, retrieval, agent, and eval logic out of the web layer |
| `scripts` | Reproducible operational tasks | Corpus fetch, corpus cleanup, docs generation, checklist status |
| `tests` | Unit and integration tests | Unit tests run in CI; integration tests use the real local stack |
| `evals` | Golden-set data | Stores the questions and expected answers used to measure quality |
| `infra` | Docker Compose stack | One command starts Postgres, Redis, Qdrant, and MinIO |
| `docs/helix-brain` | Obsidian vault | The source of truth for explanations, decisions, and the build log |
| `docs/theory.html` | Generated study guide | A portable, searchable, printable view of the vault |
| `data` | Local corpus and manifest | Downloaded data; gitignored because it is large and reproducible |
| `NOTICE` | Corpus attribution | Records the upstream licenses and attribution requirements |

The root files are the interface to the project:

| File | Purpose |
|---|---|
| `Makefile` | The shared command surface: `make ci`, `make docs`, `make corpus`, `make up` |
| `pyproject.toml` | Python version, dependencies, Ruff, mypy, and pytest configuration |
| `AGENTS.md` | Working instructions for coding agents |
| `README.md` | Human quickstart and current status |
| `.env.example` | Documented local configuration; `.env` is ignored |

## The target architecture

The diagram below is the destination, not the current implementation. Today the
API health path, the local services, the corpus, and the parser exist; the
retrieval and agent layers do not.

```text
                    Browser / future Next.js UI
                              |
                         HTTP / SSE
                              |
                    FastAPI API (apps/api)
                 auth, chat, admin, health
                              |
                 helix domain (packages/helix)
              ingest, retrieve, agent, evaluate
                    /          |          \
             Postgres       Qdrant       MinIO
             truth          vectors      blobs
                    \          |          /
                         Redis
                  jobs, cache, rate limits
```

There are two important flows.

### Ingestion flow

```text
pinned Git repo
   -> selected Markdown + manifest
   -> parse
   -> classify ACLs
   -> parent/child chunks
   -> dense + sparse embeddings
   -> Postgres metadata + Qdrant points + MinIO originals
```

Ingestion is a batch pipeline. It is allowed to be slower than a chat request,
so CPU-heavy parsing and embedding belong in a worker, not in the API event
loop.

### Query flow

```text
user question
   -> authenticate and resolve role
   -> rewrite / expand the query
   -> hybrid retrieval with ACL pre-filter
   -> rerank
   -> expand child chunks to parent context
   -> assemble a token-budgeted context with citations
   -> generate an answer
   -> verify citations and grounding
   -> answer, or abstain when evidence is missing
```

The query path is latency-sensitive. The design keeps network-bound work async
and pushes optional work, such as broad query expansion, behind a bounded budget.

Until 4.1 adds JWT auth, checkpoint 2.0 supplies a localhost-only trusted role
header and a typed identity object. The ACL pre-filter uses that interface; 4.1
replaces the resolver with JWT claims without changing retrieval code.

## What exists now vs what comes next

| Layer | Now | Next |
|---|---|---|
| API | `/`, `/health/live`, `/health/ready` | Chat, streaming, admin ingest |
| Ingestion | Pinned corpus, manifest, Markdown parser | ACL classifier, chunker, embedder, MinIO archive |
| Storage | Four running services, empty | Schemas, collections, buckets |
| Retrieval | None | Hybrid dense + sparse, RRF, reranker |
| Agent | None | LangGraph plan/retrieve/grade loop |
| Security | Localhost-only services | JWT, RBAC/ABAC, ACL filtering, audit log |
| Evaluation | Seven seed questions | Larger golden set, metric runner, gates |
| Docs | Vault and generated HTML | ADRs, final guide, demo script |

This table is deliberately blunt. It prevents the notes from describing a
system that has not been built yet.

## Why these choices

| Decision | Why | Trade-off |
|---|---|---|
| Modular monolith, not microservices | One repo, one API, and clear package boundaries are easier to test and explain; a worker can be split out later | Less independent scaling than separate services |
| FastAPI + async I/O | Most request time is waiting on databases, search, or an LLM; SSE streaming is naturally async | CPU-heavy work must move to a worker or threadpool |
| Postgres as the source of truth | Transactions, joins, constraints, ACLs, jobs, conversations, and audit need relational guarantees | Not the best place for vectors or large blobs |
| Qdrant for retrieval | Dense and sparse vectors plus payload filters; ACL filters can run before ranking | Another service to operate and back up |
| MinIO for blobs | Keeps originals and parsed artifacts out of the database; S3 API makes cloud migration realistic | Another dependency; local image is a pinned community mirror |
| Redis for jobs and cache | Fast ephemeral operations, TTLs, counters, and locks | Not durable truth; jobs must be recoverable from Postgres |
| Pinned corpus + manifest | Same text, same citations, same eval baseline | Deliberately stale until the pin is refreshed |
| Parent/child chunks | Small children retrieve precisely; larger parents preserve enough context to answer | More metadata and a parent-expansion step |
| Hybrid retrieval + RRF | Dense vectors catch meaning; sparse vectors catch IDs, versions, and exact terms; RRF combines rankings without score calibration | More moving parts than dense-only |
| Reranker + parent expansion | Cheap retrieval can return a wide candidate set; a cross-encoder improves the final order, and parents restore context | Extra latency and compute |
| ACL pre-filter | Security must not depend on the model ignoring forbidden text | Filtering can reduce recall if ACL metadata is wrong |
| Bounded LangGraph loop | Some questions need rewrite, decomposition, or a corrective retry; a graph makes state and traces explicit | More complexity than a single prompt |
| Offline eval gates | Retrieval and generation fail differently; measure them separately before release | A good golden set takes manual effort |
| Generated HTML from Markdown | One source of truth, no Node toolchain, one offline file | The Markdown subset is intentionally small |

## Why not the simpler option?

| Simpler option | Why we did not start there | When it would be reasonable |
|---|---|---|
| One Postgres with `pgvector` | Fine at small scale, but filtered hybrid search and quantization are easier in Qdrant | A small prototype or a team that wants one fewer service |
| Dense-only retrieval | Misses exact error codes, product names, and version strings | A corpus with mostly natural-language prose |
| Fixed-size chunks only | Splits procedures and headings apart; citations become vague | A first prototype before structure-aware chunking |
| Filter ACLs after retrieval | A forbidden passage may already be in the prompt or logs | Never for a security boundary |
| A full static-site generator | Adds a Node toolchain for a small personal vault | The vault starts using many Obsidian plugins |
| Microservices from day one | Too much operational overhead before the product is understood | Independent teams, scaling, or deployment constraints |

## A future request, end to end

Take the seed question: **"When is an account considered In Collections?"**

1. The API authenticates the user and resolves their role.
2. The query is rewritten to include the terms `invoice balance`, `days
   overdue`, and `In Collections`.
3. Qdrant searches with an ACL filter, so the user only sees allowed documents.
4. Dense and sparse rankings are fused; the top candidates are reranked.
5. The best child chunk is expanded to its parent section, which contains the
   full condition.
6. The context builder includes the section heading, path, and commit.
7. The model answers with a citation to that heading.
8. A citation check confirms the cited passage actually supports the answer.
9. If no allowed passage supports the answer, the system abstains instead of
   guessing.

This is why retrieval metrics and citation validity are separate: a fluent
answer can still be unsupported, and a perfect citation can still come from a
passage the user is not allowed to see.

## How to read the repo

1. Start with [[Start-Here]] for the current checkpoint and reading paths.
2. Read [[Foundations]] for the Python, async, config, and Makefile ideas.
3. Read [[Compose-Stack]] and [[Storage-Layers]] for the local services.
4. Read [[Corpus]] for how the source snapshot is pinned and selected, then
   [[Parsing]] for how Markdown becomes structured JSON.
5. Read [[Evaluation-101]] for how quality is measured.
6. Read [[Tracing-a-Document]] for the chain from a manifest entry to a seed
   question.
7. Use [[Checklist]] for what is actually in scope right now.

## Interview angle

- "The architecture is a modular monolith with clear package boundaries, not a
  distributed system pretending to be a product."
- "Each store exists for an access pattern: Postgres for truth, Qdrant for
  filtered vector search, MinIO for blobs, Redis for ephemeral work."
- "Retrieval quality is a ceiling. If the right passage is not retrieved, no
  prompt can reliably recover it."
- "ACL filtering happens before ranking because security cannot depend on the
  model obeying instructions."
- "I add complexity only when an ablation shows a measurable gain."
