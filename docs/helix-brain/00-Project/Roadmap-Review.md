---
type: process
status: active
day: 4
tags: [process, roadmap, planning, security, evaluation]
related: ["[[Start-Here]]", "[[Checklist]]", "[[Project-Map]]", "[[ACL-Classification]]", "[[Evaluation-101]]", "[[Storage-Layers]]", "[[2026-10-27]]"]
---

# Roadmap review: gaps and ordering fixes

**Short answer:** The roadmap is sound in shape, but three things were missing or
misordered: MinIO had no owning checkpoint, ACL filtering was planned before the
identity that supplies roles, and retrieval tuning was planned before the eval set
was large enough to tune against. This note records the fixes and the remaining
open questions.

## Current shape

| Phase | Checkpoints | Purpose |
|---|---|---|
| M0 | 0.1–0.5 | Foundations, local stack, corpus, docs, CI |
| M1 | 1.1–1.6 | Markdown to a searchable, permission-labelled index |
| M2 | 2.1–2.6 | Retrieval, ACL pre-filter, generation context, chat |
| M3 | 3.1–3.7 | Agent loop, query rewriting, grading, citations |
| M4 | 4.1–4.6 | Real auth, RBAC/ABAC, audit, admin, hardening |
| M5 | 5.1–5.6 | Golden set, metrics, ablations, tracing, gates |
| M6 | 6.1–6.5 | MCP server and client |
| M7 | 7.1–7.5 | Load/failure tests, final guide, ADRs, demo |

The M0 and M1 order is still correct: parse, classify, chunk, embed, store, then
automate. The fixes below preserve that order.

## Gaps found

### 1. MinIO had no owner

The stack runs MinIO, and [[Storage-Layers]] explains why object storage exists,
but no checkpoint created a bucket or uploaded anything. The raw corpus and
manifest are reproducible, but a realistic pipeline should still archive the
exact snapshot it indexed.

**Fix:** add `1.5b MinIO raw + manifest snapshot` after 1.5. It stores immutable
keys, records SHA-256 checksums, and treats a re-upload of the same commit as a
no-op.

### 2. ACL filtering came before identity

Checkpoint 2.2 applies an ACL pre-filter, but roles arrive with JWT auth at 4.1.
Without a role source, 2.2 cannot be tested honestly.

**Fix:** add `2.0 Identity context + trusted dev role resolver` before 2.1. The
development resolver reads a role header from a localhost-only request and
returns a typed identity. Checkpoint 4.1 replaces it with JWT claims without
changing the retrieval interface. The API must not be exposed beyond localhost
while the trusted header exists.

### 3. The golden set was too late

2.1 tunes hybrid retrieval, but 5.1 expands the golden set to roughly 110 cases.
Seven seed cases are enough to prove the pipeline runs, not enough to tune
recall@k or compare ablations.

**Fix:** add `1.7 Eval seed expansion` before M2. Grow the set to at least 25–30
cases covering lookup, procedural, conditional, multi-hop, unanswerable, and
permission cases. M5 still owns the full ~110-case set, LLM-judge validation, and
CI gates. Do not tune retrieval on the seven seeds.

### 4. Seed roles and the ACL taxonomy disagree

The seven seeds use `billing` (five cases) and `finance` (two cases) on the Zuora
guide under `content/handbook/business-technology/`. `billing` was not in the
role model, and `business-technology` sat under `internal:eng`, which did not
include finance.

**Resolved on 2026-10-27:** `billing` is an alias for `finance`, and
`business-technology` moves to `internal:company`. The seed file can keep
`billing` until 1.7 normalizes it, but the classifier and matcher use `finance`.
See [[ACL-Classification]] for the final role and count tables.

### 5. Postgres schema and migrations were implicit

1.5 says "Postgres holds the document/chunk map", but does not name a migration
tool, constraints, or uniqueness rules.

**Fix, inside 1.5:** use Alembic from the first table. Add a unique constraint on
`(source, path)` for documents and `(document_id, ordinal)` for chunks, plus
foreign keys and an index on content hash. No separate checkpoint.

### 6. Embedding model version was not tracked

1.4 embeds chunks, but a model change means vectors from different spaces cannot
be mixed. The roadmap did not say how to detect or migrate that.

**Fix, inside 1.4/1.5:** store `embedding_model`, `embedding_model_version`, and
`embedding_dim` in Postgres and the Qdrant payload. Name the collection with the
model version, for example `chunks_bge_m3_v1`. A model change creates a new
collection and triggers a re-index; it never writes into the old one.

### 7. Worker reliability was underspecified

1.6 covers idempotency and tombstones, but not retries, poison jobs, or scheduled
refresh.

**Fix, inside 1.6:** bounded retries with backoff, a dead-letter queue, a job
record in Postgres, a lock per ingest run, and a documented refresh command. The
config hash includes parser, ACL policy, chunker, and embedding-model versions so
a policy change forces the right work.

### 8. Tenant was a payload field without a tenant model

Qdrant payload includes `tenant`, but the product is single-user and there is no
tenant table, header, or isolation rule.

**Fix, inside 1.5/4.2:** keep `tenant` as a reserved field with the local value
`default`; document single-tenant scope. Do not imply multi-tenancy until there
is a tenant table, claim, and isolation test. If multi-tenancy is added, it needs
its own checkpoint and security review.

### 9. Frontend auth integration was not explicit

4.1 covers JWT issuance and rotation, but the Next.js app at 2.6 needs to send
the token, handle refresh, and show permission-denied states.

**Fix, inside 4.1:** include the UI login/token-refresh path and a permission
denial state. 2.6 can use the trusted dev role header until then.

### 10. Operational recovery was thin

7.1 covers load and failure injection, but not backup/restore of Postgres,
Qdrant, and MinIO, or a re-index runbook.

**Fix, inside 7.1/7.3:** add a backup/restore drill for all durable stores, a
"restore then re-index" runbook, and a documented recovery time. This is a
portfolio project, not a production SLO, but the failure story should be real.

### 11. API contract details were implicit

2.5 says "chat API" without naming the error model, request IDs, CORS, or the
development identity header.

**Fix, inside 2.5:** define the error envelope, request ID, CORS allowlist,
OpenAPI examples, and the temporary dev role header. Keep streaming for 3.6.

## Revised sequence

```text
1.1 parser
  -> 1.2 ACL classifier
  -> 1.3 chunker
  -> 1.4 embedder
  -> 1.5 Qdrant + Postgres
  -> 1.5b MinIO raw + manifest snapshot
  -> 1.6 worker + reconcile
  -> 1.7 eval seed expansion
  -> 2.0 identity context + dev role resolver
  -> 2.1 hybrid retrieval
  -> 2.2 ACL pre-filter
  -> ...
```

1.7 and 2.0 are small checkpoints. They exist because M2 cannot be evaluated or
secured without them.

## Decisions

- Add `1.5b`, `1.7`, and `2.0` to [[Checklist]].
- Fold migrations, model versioning, worker reliability, tenant scope, frontend
  auth, and recovery into the existing checkpoints rather than creating a row for
  every concern.
- Keep the local stack single-tenant and localhost-only.
- Start the golden set before retrieval tuning, not after the agent is built.
- Treat `billing` as an alias for `finance` and move `business-technology` to
  `internal:company`; 1.2 can proceed with the corrected table.

## Open questions

1. Is `legal` access to all HR and finance documents too broad for the demo? If
   so, split labor/acquisition documents into narrower rules.
2. Is single-tenant scope acceptable for the portfolio, or is tenant isolation a
   planned checkpoint? Recommended single-tenant for now.
