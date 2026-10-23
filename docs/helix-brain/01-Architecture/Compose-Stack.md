---
type: concept
status: verified
day: 1
tags: [docker, compose, postgres, redis, qdrant, minio, health, interview]
related: ["[[Foundations]]", "[[2026-10-23]]"]
---

# Local stack and readiness

Checkpoint 0.2. Four services, one command, and a readiness endpoint that tells
the truth when one of them dies.

---

## What Docker Compose is

- An **image** is a packaged filesystem + command (e.g., `postgres:16-alpine`).
- A **container** is a running image with its own network and filesystem.
- A **volume** keeps data after the container is recreated.
- **Compose** reads one YAML file and starts a group of containers on a shared
  network.

Compose is a **local development tool**, not a production orchestrator. In
production you would use Kubernetes, ECS, Nomad, or managed services. The value
here is reproducibility: every dependency starts with the same version and
config on any machine.

---

## Services

| Service | Image | Host port(s) | Purpose | Volume |
|---|---|---|---|---|
| Postgres | `postgres:16-alpine` | `5432` | users, documents, jobs, conversations, audit | `pgdata` |
| Redis | `redis:7-alpine` | `6379` | queue, cache, rate limits | `redisdata` |
| Qdrant | `qdrant/qdrant:v1.20.0` | `6333` HTTP, `6334` gRPC | vector + sparse index | `qdrantdata` |
| MinIO | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z` | `9100` API, `9101` console | raw documents, S3-compatible | `miniodata` |

All ports bind to `127.0.0.1`, not `0.0.0.0`. That means the services are
reachable from your machine but **not from your LAN**. Defaults are for local
development only; shared environments need auth and TLS.

**Why 9100/9101 for MinIO?** Portainer already owns `9000/9001` on this
machine. Mapping the host side avoids the conflict without changing MinIO's
internal ports.

---

## Healthchecks

A container being "Up" does not mean it is ready. Postgres may still be
initializing; Qdrant may not have opened its port. Each service has a
healthcheck:

| Service  | Check                                                               |
| -------- | ------------------------------------------------------------------- |
| Postgres | `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`                      |
| Redis    | `redis-cli ping`                                                    |
| Qdrant   | open a TCP connection to `127.0.0.1:6333` (the image has no `curl`) |
| MinIO    | `curl -f http://localhost:9000/minio/health/live`                   |

`make up` runs `docker compose up -d --wait`, which blocks until every service
is **healthy** (or fails after the timeout). `start_period` gives slow services
time to boot before failures count.

---

## Liveness vs readiness in Helix

- `GET /health/live` — is the API process serving? No dependencies. If this
  fails, restart the process.
- `GET /health/ready` — can the API actually answer? It checks Postgres, Redis,
  Qdrant, and MinIO **concurrently**, each with a short timeout.

Response when all is well:

```json
{"status":"ok","service":"helix-api","checks":{"postgres":"ok","redis":"ok","qdrant":"ok","minio":"ok"}}
```

Response when Qdrant is stopped:

```json
{"status":"degraded","service":"helix-api","checks":{"postgres":"ok","redis":"ok","qdrant":"down","minio":"ok"}}
```

HTTP status is `200` when healthy and `503` when degraded. The body names the
failed dependency, which makes debugging fast.

**Rules we followed**

1. Readiness must never raise; it returns a status.
2. Every check has a timeout, so one hung service cannot hang the probe.
3. Checks run concurrently (`asyncio.gather`), so total time is the slowest
   check, not the sum.
4. We connect per check for now. At higher traffic we will reuse pooled clients
   and cache the result briefly.
5. Never log the DSN or password; only the exception *type*.

---

## Developer GUIs (optional)

The data services have no UI in the base stack except Qdrant and MinIO, which
ship their own. Two extra containers are available under the `tools` profile:

```bash
make tools
```

| UI | URL | Connects to |
|---|---|---|
| Adminer | http://127.0.0.1:8081 | Postgres (`postgres:5432`, `helix` / local password) |
| RedisInsight | http://127.0.0.1:5540 | Redis (`redis:6379`, no password) |
| Qdrant dashboard | http://127.0.0.1:6333/dashboard | built into the Qdrant image |
| MinIO Console | http://127.0.0.1:9101 | built into the MinIO image |

`make up` does **not** start Adminer or RedisInsight; they are opt-in so the
default stack stays small. Stop them with `make tools-down`.

At checkpoint 0.2 all four are empty: no tables, keys, collections, or buckets
until ingestion starts. Details and alternatives: [[Storage-Layers]].

---

## One source of configuration

Compose and the app read the same `HELIX_*` values:

- Compose substitutes `${HELIX_POSTGRES_PORT:-5432}` for the host mapping.
- `Settings` reads the same `HELIX_POSTGRES_PORT` to build the DSN.

`make up` passes `--env-file .env` when the file exists. If you run
`docker compose -f infra/docker-compose.yml` directly, Compose looks for `.env`
next to the compose file, not at the repo root — use `make up`.

Passwords are `SecretStr` in `Settings`, so `repr(settings)` masks them. The
DSN is built from parts and never logged.

---

## MinIO image caveat (supply chain)

MinIO's official public images became unavailable during this build:
Docker Hub returns 404 and Quay returns 401. We use `pgsty/minio`, a pinned
community mirror, **for local development only**.

What a production setup would do instead:

- use MinIO's official binary/operator, or
- use a managed S3-compatible service, and
- pin images by digest, scan them (Trivy), and keep an SBOM.

This is a real tradeoff, and worth saying in an interview: "pinned mirror
locally, official distribution in production."

---

## Commands

```bash
make up              # start and wait until healthy
make ps              # status and ports
make logs            # follow logs
make ready           # call /health/ready (API must be running)
make tools           # optional Adminer + RedisInsight
make tools-down
make test-integration
make down            # stop containers, keep data
make reset           # stop and DELETE volumes (destructive)
```

The integration test is marked `integration` and excluded from `make test`
because it needs the live stack. Run it with `make test-integration`.

---

## Interview angles

- **Compose vs Kubernetes:** Compose is for one machine and local development;
  Kubernetes adds scheduling, scaling, rolling updates, and self-healing.
- **Healthcheck vs readiness probe:** a Compose healthcheck marks container
  health locally; a Kubernetes readiness probe controls traffic. Same idea,
  different layer.
- **Why bind to localhost:** least exposure. A dev database on `0.0.0.0` is a
  common and unnecessary risk.
- **Why readiness has timeouts:** without them, one dead dependency turns the
  probe into a hang, and the orchestrator cannot distinguish slow from dead.
- **Stateful services:** volumes survive `down`; `down -v` deletes data. Know
  which command you are running.
