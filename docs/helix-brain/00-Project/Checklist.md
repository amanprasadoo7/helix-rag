---
type: process
status: active
day: 1
tags: [process, checklist, roadmap, interviews]
related: ["[[2026-10-23]]", "[[Foundations]]", "[[Compose-Stack]]"]
---

# Checkpoint checklist and handoff protocol

This is the contract for how we build Helix. It exists so neither the agent nor
the human forgets a step, and so every checkpoint ends in the same verifiable
state.

Run `make checklist` to see the current status.

---

## The two-key rule

| Key | Who marks it | Meaning |
|---|---|---|
| **Agent** | implementation, tests, docs, commit | "I built it and it passes automated checks." |
| **User** | `User verified` | "I ran the manual test myself and it works." |

The agent **never** marks `User verified`. A checkpoint is not `done` on the
roadmap until the user says `pass`. If the user finds a problem, the fix gets
its own `fix(...)` commit and the DoD is repeated.

---

## Definition of Done (every checkpoint)

- [ ] Scope is one checkpoint (split it if it grows beyond ~3 hours)
- [ ] Implementation complete
- [ ] Tests added or updated (unit; integration when a real service is involved)
- [ ] Manual test steps and expected output documented
- [ ] `make ci` green
- [ ] Notes updated: concept note, journal, roadmap row
- [ ] ADR written if an architectural decision was made
- [ ] Security check if it touches auth, data, ACLs, or external input
- [ ] Commit created with a conventional message and no secrets
- [ ] User verified (user marks after replying `pass`)

---

## Current checkpoint

### 0.3 - Corpus fetch and manifest

Goal: download a reproducible snapshot of the GitLab handbook and product docs,
pin the commit SHAs, and produce a manifest with counts, sizes, and license
attribution.

- [x] Implementation: `scripts/fetch_corpus.py` with pinned SHAs and sparse checkout
- [x] Manifest: per-path file counts, bytes, source versions, total estimate
- [x] License: `NOTICE` with attribution; corpus not committed to git
- [x] Tests: path selection and manifest counting (pure functions)
- [x] Manual: `make corpus`, inspect `data/manifest.json`, verify counts
- [x] `make ci` green
- [x] Notes: `Corpus.md` + journal + roadmap row
- [x] Commit: `feat(corpus): fetch pinned GitLab handbook and documentation`
- [ ] User verified (user marks only)

---

## Roadmap

Status values: `pending`, `in progress`, `done`, `blocked`.

| # | Checkpoint | Status | Notes |
|---|---|---|---|
| 0.1 | Walking skeleton | done | [[Foundations]] |
| 0.2 | Local stack and readiness | done | [[Compose-Stack]], [[Storage-Layers]] |
| 0.3 | Corpus fetch and manifest | in progress | [[Corpus]] |
| 0.4 | Vault, note templates, doc generator | pending | `docs/theory.html` |
| 0.5 | CI baseline | pending | ruff, mypy, pytest |
| 1.1 | Parser | pending | Docling, Markdown |
| 1.2 | ACL classifier | pending | path to classification |
| 1.3 | Chunker | pending | structure-aware, parent/child |
| 1.4 | Embedder | pending | BGE-M3 dense + sparse |
| 1.5 | Qdrant + Postgres metadata | pending | deterministic point IDs |
| 1.6 | Worker + full ingest + reconcile | pending | ARQ, tombstones |
| 2.1 | Hybrid retrieval | pending | dense + sparse + RRF |
| 2.2 | ACL pre-filter | pending | security checkpoint |
| 2.3 | Reranker + parent expansion | pending | cross-encoder |
| 2.4 | Context assembly | pending | token budget, citations |
| 2.5 | Chat API | pending | non-streaming first |
| 2.6 | Next.js chat | pending | citations, source drawer |
| 3.1 | LangGraph skeleton | pending | state + trace |
| 3.2 | Intent classifier | pending | small local model |
| 3.3 | Query rewrite | pending | multi-query, filters |
| 3.4 | Plan/decompose | pending | multi-hop |
| 3.5 | Grade + corrective loop | pending | max 2 iterations |
| 3.6 | Generation + SSE | pending | structured citations |
| 3.7 | Citation verify + guard + fallback | pending | llama-guard3 |
| 4.1 | JWT auth | pending | Argon2, refresh rotation |
| 4.2 | RBAC/ABAC | pending | server-side claims |
| 4.3 | Audit log | pending | append-only |
| 4.4 | Admin ingest API/UI | pending | jobs, documents |
| 4.5 | Rate limits + security headers | pending | per user/IP |
| 4.6 | Security test suite | pending | ACL matrix, injection |
| 5.1 | Golden set | pending | ~110 cases |
| 5.2 | Retrieval metrics | pending | recall@k, MRR, nDCG |
| 5.3 | Generation metrics | pending | Ragas, citation validity |
| 5.4 | Ablation runner | pending | the interview table |
| 5.5 | Langfuse tracing | pending | per-request spans |
| 5.6 | Grafana + CI gates | pending | metrics, hard gates |
| 6.1 | MCP server (stdio) | pending | `search_docs` |
| 6.2 | MCP tools + resource | pending | section, versions |
| 6.3 | MCP HTTP + auth | pending | bearer token, audit |
| 6.4 | MCP client demo | pending | agent consumes tickets |
| 6.5 | MCP security tests | pending | ACL, no writes |
| 7.1 | Load test + failure injection | pending | k6, outages |
| 7.2 | Final HTML guide | pending | tabs, checklist, flashcards |
| 7.3 | ADRs + notes | pending | decisions complete |
| 7.4 | Demo script | pending | 10 minutes |
| 7.5 | Mock interview | pending | 20 questions |

---

## Handoff template (agent writes this every checkpoint)

```text
Checkpoint X.Y - Name

Goal:
Files:
Decision: why this, and why not the alternative
You test:
Expected:
Break it:
Interview angle:
Notes updated:
Checklist: X/Y items
Next:
```

The user replies `pass`, or pastes the error. Nothing moves forward without one
of those two replies.

---

## Commit convention

One checkpoint per commit. Run `make ci` first. Never commit `.env` or secrets.

| Prefix | Use |
|---|---|
| `feat(scope):` | new behavior |
| `fix(scope):` | bug fix |
| `test(scope):` | tests only |
| `docs(scope):` | notes and guides |
| `chore(scope):` | tooling, deps, config |

The body should explain **why**, not restate the diff.

---

## Release gates

These are hard gates for the finished project, not per-checkpoint gates.

| Area | Gate |
|---|---|
| Security | zero ACL leaks, zero successful prompt injections, JWT tests green |
| Retrieval | recall@10 >= 0.80 on the golden set |
| Generation | faithfulness >= 0.85, citation validity >= 0.95 |
| Abstention | correct refusal >= 0.90 |
| Performance | p95 end-to-end < 10s, first token < 2s |
| Cost | cost per query recorded and reported |
| Docs | HTML guide generated, ADRs complete, demo rehearsed |

---

## Rules that prevent drift

1. No checkpoint starts before the previous one is user-verified.
2. If a checkpoint grows, split it and add a sub-row (`1.4a`) instead of
   silently expanding scope.
3. Every new dependency gets a one-line justification in the note.
4. Every architectural choice gets an ADR with "revisit when...".
5. The Obsidian vault is the source of truth; the HTML guide is generated.
6. If the manual test cannot be described in one block, the checkpoint is too
   big.
