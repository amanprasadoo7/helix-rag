# Helix

Permission-aware agentic RAG over the GitLab public handbook and product docs.

**Status:** Checkpoint 0.1 - walking skeleton (liveness endpoint only).

## Quickstart

```bash
make sync
make up           # Postgres, Redis, Qdrant, MinIO
make dev          # http://127.0.0.1:8000
make ready        # checks all four dependencies
make tools        # optional Adminer + RedisInsight
make test
make lint
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

`make up` waits for healthchecks. `make down` keeps data; `make reset` deletes
volumes.

MinIO's official public images are currently unavailable, so local dev uses a
pinned community mirror. Use the official MinIO distribution or managed S3 in
production.

## Layout

- `apps/api` - FastAPI backend
- `packages/helix` - shared library (config, retrieval, agents, eval)
- `tests` - unit, integration, security, eval
- `docs/helix-brain` - Obsidian vault (source of truth for notes)
- `docs/theory.html` - generated study guide (added in 0.4)
