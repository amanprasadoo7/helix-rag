# Helix

Permission-aware agentic RAG over the GitLab public handbook and product docs.

**Status:** Checkpoint 0.4 complete; 0.5 - CI baseline (next).

## Quickstart

```bash
make sync
make up           # Postgres, Redis, Qdrant, MinIO
make dev          # http://127.0.0.1:8000
make ready        # checks all four dependencies
make tools        # optional Adminer + RedisInsight
make test
make lint
make checklist    # current checkpoint status
make docs         # regenerate docs/theory.html from the vault
```

API docs: http://127.0.0.1:8000/docs

| Service | Host | Notes |
|---|---|---|
| API | http://127.0.0.1:8000 | `/docs`, `/health/live`, `/health/ready` |
| Postgres | `127.0.0.1:5432` | user/db `helix` (local defaults) |
| Adminer | http://127.0.0.1:8081 | Postgres GUI; server `postgres`, `helix` / local password |
| Redis | `127.0.0.1:6379` | append-only persistence |
| RedisInsight | http://127.0.0.1:5540 | Redis GUI; host `redis`, port `6379` |
| Qdrant | http://127.0.0.1:6333 | dashboard at `/dashboard`; gRPC on `6334` |
| MinIO API | http://127.0.0.1:9100 | S3-compatible |
| MinIO console | http://127.0.0.1:9101 | `helix` / local default |

At this checkpoint the stores are empty: the schema, collections, and buckets
are created during ingestion (M1).

## Corpus

```bash
make corpus       # pinned handbook + product docs -> data/corpus
make corpus-clean # keep only selected Markdown, remove .git and assets
```

`make corpus` performs a partial clone with sparse checkout, caps the snapshot
at 2,500 Markdown files, and writes `data/manifest.json` with per-path counts,
sizes, word counts, and estimated chunks. The corpus is gitignored. Licensing
and attribution are in `NOTICE`; the product docs under `doc/` are CC BY-SA 4.0
and the handbook repository is MIT.

Current snapshot: 2,500 files, 32.1 MB of content (41 MB allocated), ~3.98M
words, ~19.9k estimated child chunks. The initial checkout is about 1.8 GB;
`make corpus-clean` leaves only the selected Markdown and removes `.git`.
Re-fetch with `make corpus` when you need local Git-level tracing. See
[`Corpus.md`](docs/helix-brain/01-Architecture/Corpus.md) for the selection
strategy and trade-offs.

`make up` waits for healthchecks. `make down` keeps data; `make reset` deletes
volumes.

MinIO's official public images are currently unavailable, so local dev uses a
pinned community mirror. Use the official MinIO distribution or managed S3 in
production.

## Study guide

The Obsidian vault under `docs/helix-brain` is the source of truth. Build a
single self-contained HTML study guide with:

```bash
make docs
# then open docs/theory.html in a browser
```

The guide has sidebar navigation, per-note tables of contents, client-side
search (press `/`), light/dark themes, and print styles. Note templates live in
`docs/helix-brain/_templates`. See
[`Study-Guide.md`](docs/helix-brain/00-Project/Study-Guide.md) for the frontmatter
contract and supported Markdown subset.

## Evaluation

`evals/seed_questions.jsonl` contains seven manually verified seed cases from
the Zuora Collect page, including an unanswerable question for abstention. These
are seeds, not the final golden set. See
[`Evaluation-101.md`](docs/helix-brain/02-Evaluation/Evaluation-101.md) for the
metric families, security gates, and ablation plan.

## Process

The roadmap and per-checkpoint Definition of Done live in
[`docs/helix-brain/00-Project/Checklist.md`](docs/helix-brain/00-Project/Checklist.md).
`make checklist` prints the current checkpoint, remaining items, and roadmap
counts. A checkpoint moves to `done` only after manual user verification.

## Layout

- `apps/api` - FastAPI backend
- `packages/helix` - shared library (config, retrieval, agents, eval)
- `scripts` - reproducible data and maintenance scripts
- `tests` - unit, integration, security, eval
- `evals` - golden-set data, starting with the seed questions
- `docs/helix-brain` - Obsidian vault (source of truth for notes)
- `docs/theory.html` - generated self-contained study guide
- `NOTICE` - corpus attribution and licenses
