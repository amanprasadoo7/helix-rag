---
type: concept
status: active
day: 1
tags: [postgres, redis, qdrant, minio, gui, storage, interview]
related: ["[[Compose-Stack]]", "[[Foundations]]", "[[ACL-Classification]]", "[[Ingestion-M1]]", "[[Roadmap-Review]]", "[[2026-10-23]]", "[[2026-10-27]]"]
---

# Why four stores? Postgres, Redis, Qdrant, MinIO

Short answer: each one is optimized for a different **access pattern**. Using
one store for everything is possible, but you pay in performance, backups, or
operational complexity. This pattern is called **polyglot persistence**.

| Store | What it holds | Access pattern | Durable? | If we lose it |
|---|---|---|---|---|
| **Postgres** | users, roles, documents, chunks map, jobs, conversations, audit | transactions, joins, constraints | yes | data loss, must restore |
| **Redis** | queue, cache, rate-limit counters, locks | sub-millisecond ephemeral ops, TTL | optional | safe if designed well; rebuild |
| **Qdrant** | embeddings + payload for retrieval | nearest-neighbor search with filters | yes | rebuild by re-embedding |
| **MinIO** | raw files, parsed artifacts, snapshots | large blob PUT/GET/stream | yes | re-fetch sources |

---

## 1. Postgres — the source of truth

**What it is:** a relational database with transactions (ACID), joins, unique
constraints, and foreign keys.

**What Helix stores here**

- users, roles, user attributes (department, clearance)
- document metadata + ACLs
- chunk metadata (which chunk belongs to which document)
- ingestion jobs and their status
- conversations, messages, citations, feedback
- append-only audit log
- evaluation runs and results

**Why not put everything here?**

- Vectors: `pgvector` works, but Qdrant gives better filtered hybrid search and
  built-in quantization at scale.
- Blobs: large files bloat backups and are slow to stream from a relational DB.
- Ephemeral counters/queues: possible, but Redis is faster and keeps load off
  the primary database.

**See it visually**

```bash
make tools
```

Open `http://127.0.0.1:8081` (Adminer), then log in with:

| Field | Value |
|---|---|
| System | PostgreSQL |
| Server | `postgres` (inside the Compose network) |
| Username | `helix` |
| Password | `helix_dev_password` (local default) |
| Database | `helix` |

CLI alternative:

```bash
docker exec -it helix-postgres psql -U helix -d helix
```

**At checkpoint 0.2 the database is empty** — no tables yet. The schema and
Alembic migrations arrive with 1.5, together with the document/chunk map and
uniqueness constraints. An empty GUI is expected before then.

**GUI options:** Adminer (web, included, lightweight), DBeaver (desktop, best
for exploring), pgAdmin (heavier), TablePlus (paid), `psql` (CLI).

---

## 2. Redis — the fast, disposable layer

**Quick refresh:** Redis is an **in-memory key-value store**. Data lives in RAM,
so operations are extremely fast (often under a millisecond). Persistence is
optional; we enable append-only file (AOF) so a restart does not lose the queue.

It is more than a cache. Useful data structures:

| Structure | Use |
|---|---|
| string + `INCR`/`EXPIRE` | rate limiting, counters |
| list / stream | job queue |
| set | deduplication, tags |
| sorted set | ranking, scheduling |
| hash | small objects |
| `SET NX` | distributed lock / "only one worker" |

**What Redis solves in Helix**

1. **Background job queue (ARQ).** Parsing and embedding are slow. The API
   enqueues a job; a worker processes it. The user is not blocked.
2. **Cache.** Query embeddings, retrieval results, and provider responses.
   Repeated questions become cheaper and faster.
3. **Rate limiting.** Atomic `INCR` + `EXPIRE` per user/IP, to protect the API
   and your Groq quota.
4. **Locks / idempotency.** Prevent two workers from ingesting the same
   document at the same time.
5. **Short-lived state.** Refresh-token revocation lists and similar TTL data.

**Why not Postgres?**

Postgres *can* queue jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, and it can
cache in unlogged tables. But Redis is simpler for high-frequency ephemeral
operations and keeps that load off the primary database. The tradeoff is
durability: Redis is **not** the source of truth.

Design rule: if Redis dies, nothing permanent is lost. Jobs are recorded in
Postgres and can be re-enqueued; cache misses simply fall back to the source.

**Why not Qdrant?** Qdrant is a vector index, not a general key-value store.

**At 0.2 Redis is empty.** It becomes active in M1 (queue) and later (cache,
rate limits).

**See it visually**

```bash
make tools
```

Open `http://127.0.0.1:5540` (RedisInsight) → *Add Redis Database*:

| Field | Value |
|---|---|
| Host | `redis` |
| Port | `6379` |
| Username/password | none (local dev) |

CLI: `docker exec -it helix-redis redis-cli`

**GUI options:** RedisInsight (web, included), Another Redis Desktop Manager,
`redis-cli`.

---

## 3. Qdrant — the semantic index

**What it is:** a vector database. It stores embeddings (lists of numbers) plus
a JSON **payload** (metadata), and finds nearest neighbors with an approximate
index (HNSW).

**Why we need it**

- Dense vectors capture *meaning* (paraphrases, synonyms).
- Sparse vectors capture *exact terms* (IDs, error codes, versions).
- Payload filters enforce ACLs **before** ranking.
- Quantization and snapshots keep memory and recovery manageable.

**It is not a general database:** no joins, no multi-row transactions. Payload
is for filtering and display, not for being the source of truth.

**Where the ACLs come from:** checkpoint 1.2 writes a deterministic sidecar at
`data/acl/index.json`, mapping each `(source, path)` to a classification and
allowed roles. It is not stored in Qdrant yet; 1.5 copies those fields into each
chunk's payload, and 2.2 turns them into a filter applied before vector search.
Keeping the ACL in a sidecar means a policy change reclassifies without
re-parsing or re-embedding.

**Why the root URL looked empty**

`http://127.0.0.1:6333/` is the API metadata endpoint. It returns JSON like:

```json
{"title":"qdrant - vector search engine","version":"1.20.0"}
```

The actual UI is at:

**http://127.0.0.1:6333/dashboard**

At 0.2 there are no collections yet, so the dashboard is empty. The first
collection is created at 1.5, named with the embedding model version so vectors
from different models never mix.

**GUI options:** the built-in dashboard (official), the REST API, the Python
client. There is no separate official desktop app.

---

## 4. MinIO — object storage for blobs

**What it is:** an S3-compatible object store. Think "buckets" containing
"objects" (a key → bytes + metadata). It speaks the same API as AWS S3.

**Why we need it**

- Raw documents (HTML, Markdown, PDFs) and parsed artifacts are **large blobs**.
- Storing them in Postgres bloats backups and is slow to stream.
- Storing them in Qdrant is wrong: it indexes vectors, not files.
- Keeping originals lets us **re-index** with a new chunker or embedding model
  without re-crawling the source.
- The S3 API means the same code can use AWS S3, Cloudflare R2, or MinIO in
  production with only configuration changes.

**Why not the local filesystem?** It works locally, but does not give you
presigned URLs, multipart uploads, versioning, or a clean path to cloud
storage. MinIO gives the realistic interface without cloud cost.

**See it visually:** `http://127.0.0.1:9101` (MinIO Console), user `helix`,
password `helix_minio_dev_password`.

**Checkpoint 1.5b creates the first bucket.** Before then, MinIO is running but
empty, which is expected. The archive is deliberately after 1.5 because it is not
required to make retrieval work.

**Bucket layout**

| Key | What it holds |
|---|---|
| `raw/<source>/<commit>/<path>` | exact raw Markdown bytes |
| `manifests/<source>/<commit>.json` | the manifest for that snapshot |
| `parsed/<source>/<commit>/<parser_version>/<path>.json` | optional parsed JSON for debugging |

The commit is part of the key, so a snapshot is immutable. A second upload of
the same key with the same SHA-256 is a no-op. A different payload under the same
immutable key is an error, not an overwrite. Object metadata records `sha256`,
`source`, `commit`, and `path`.

Parsed output is optional because it can be regenerated from raw bytes and the
parser version. Raw bytes and the manifest are the recovery-critical pair.

**Versioning and retention:** the commit prefix already makes snapshots
immutable, so local bucket versioning is off at first. Production can enable
versioning or lifecycle rules; the local demo keeps one snapshot per pinned
commit and documents cleanup rather than deleting silently.

**Caveat:** MinIO's official public images are currently unavailable, so local
dev uses a pinned community mirror (`pgsty/minio`). Production would use the
official MinIO distribution/operator or managed S3.

**Alternatives:** AWS S3, Cloudflare R2, Garage, SeaweedFS, or local disk for a
throwaway prototype.

---

## 5. Could we use fewer stores?

Yes, at small scale:

| Replace | With | Tradeoff |
|---|---|---|
| Qdrant | `pgvector` in Postgres | simpler ops; weaker filtered/hybrid search at scale |
| Redis | Postgres `SKIP LOCKED` queue | fewer services; slower ephemeral ops, more DB load |
| MinIO | local filesystem | simplest; no S3 API, no presigned URLs |

We chose the production-shaped stack because the goal is to learn and defend
the architecture. In an interview, say *why* each store exists and *when* you
would collapse them.

---

## 6. All GUIs at a glance

```bash
make tools        # Adminer + RedisInsight (optional profile)
```

| UI | URL | Credentials |
|---|---|---|
| Adminer (Postgres) | http://127.0.0.1:8081 | server `postgres`, `helix` / `helix_dev_password` |
| RedisInsight | http://127.0.0.1:5540 | add host `redis`, port `6379`, no password |
| Qdrant dashboard | http://127.0.0.1:6333/dashboard | none (local) |
| MinIO Console | http://127.0.0.1:9101 | `helix` / `helix_minio_dev_password` |

All bind to `127.0.0.1`. Never expose these tools on a shared network.

Stop the GUIs without stopping the data services:

```bash
make tools-down
```

---

## 7. Interview soundbites

- "Polyglot persistence: each store matches an access pattern. Postgres for
  truth, Redis for ephemeral speed, Qdrant for ANN search, object storage for
  blobs."
- "Redis is not the source of truth. If it dies, we re-enqueue jobs from
  Postgres and accept cache misses."
- "Qdrant's root URL is the API; the UI is `/dashboard`."
- "We store originals in S3-compatible storage so we can re-index without
  re-crawling, and the same code works against AWS S3."
- "The MinIO key includes the source commit. Re-uploading the same key and
  checksum is a no-op; a different payload under that key is a corruption."
- "At small scale I could use pgvector + a Postgres queue + local disk; I would
  collapse the stack until the access pattern justifies the extra component."
