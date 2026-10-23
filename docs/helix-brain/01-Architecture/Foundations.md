---
type: concept
status: verified
day: 1
tags: [python, async, tooling, config, logging, interview]
related: ["[[2026-10-23]]", "[[System-Context]]"]
---

# Foundations: async, Make, environments, logging

Questions that came up during Checkpoint 0.1. Short answers first, then the
reasoning and the interview angle.

---

## 1. Why are we using async Python?

**Short answer:** because most of what this app does is *waiting* — waiting for
Postgres, Qdrant, an LLM API, or a slow client to read a stream. Async lets one
process serve many requests while those waits happen.

**The mental model**

- A **sync** server gives each request a thread and blocks that thread while it
  waits for I/O. Ten slow requests need ten threads.
- An **async** server runs an **event loop**. When a request hits a wait, the
  loop switches to another ready task. Ten slow requests can share one thread.

Analogy: a sync server is one waiter who stands in the kitchen until each dish
is ready. An async server is one waiter who takes the order, sends it to the
kitchen, and serves other tables while it cooks.

**Why it matters for Helix**

- The chat endpoint streams tokens over **SSE**. Streaming is naturally async.
- An agent makes several retrieval calls (multiple sub-queries) that can run in
  parallel with `asyncio.gather`.
- FastAPI/Starlette are async-native; using async clients avoids blocking the
  loop.

**The trap (say this in interviews)**

Async does **not** make CPU work faster. Embedding, reranking, parsing, and
tokenizing are CPU/GPU-bound; running them inside an async endpoint blocks the
event loop and freezes *every* request. Solutions:

1. Run them in a separate **worker process** (our ingestion worker), or
2. offload to a thread/process pool (`run_in_threadpool`), or
3. use a dedicated embedding/reranker service.

Rule of thumb: **async for I/O, processes for CPU.**

**Where we use it**

| Layer | Async? | Why |
|---|---|---|
| FastAPI endpoints | yes | concurrent requests, SSE streaming |
| Postgres driver (`asyncpg`) | yes | network waits |
| Qdrant client | yes | network waits |
| HTTP calls (`httpx`) | yes | LLM/provider waits |
| Embedding / reranking | no (worker/threadpool) | CPU/GPU-bound |

---

## 2. The `asynccontextmanager` deprecation

**What the warning means:** `@asynccontextmanager` wraps an **async
generator**. The old annotation was:

```python
async def lifespan(...) -> AsyncIterator[None]:
```

Typeshed now expects the more precise generator type:

```python
from collections.abc import AsyncGenerator

async def lifespan(...) -> AsyncGenerator[None, None]:
```

`AsyncGenerator[YieldType, SendType]` means: this generator yields `None` and
nothing is sent back into it. Behavior is unchanged; only the type annotation
is more accurate, so editors/type checkers stop warning.

**Interview angle:** an async generator is not the same as an async iterator.
A generator can also *receive* values via `asend()`, which is why the send type
exists.

---

## 3. What is a Makefile?

**Short answer:** a file of named tasks. `make test` runs the recipe under the
`test` target, so you don't memorize long commands.

```make
test:              # target
	uv run pytest  # recipe (must be indented with a TAB)
```

**Why it helps**

- **One interface** for you, CI, and future contributors: `make sync`, `make
  dev`, `make test`, `make lint`, `make ci`.
- **Self-documenting**: the workflow lives in the repo, not in someone's shell
  history.
- **Composable**: `ci: lint test` runs both; `make` stops if one fails.
- **Consistent**: CI runs the same command you run locally, so "works on my
  machine" shrinks.

**How `make` thinks**

- A target is usually a file. If the file is newer than its prerequisites,
  `make` skips it (incremental builds).
- Our targets are commands, not files, so we mark them `.PHONY` to stop `make`
  from looking for a file named `test`.
- Recipes run in a shell, one line per shell unless you join them.

**Alternatives:** `just`, `task`, npm scripts, plain shell scripts. We use
`make` because it is everywhere and the syntax is tiny.

**Gotcha:** recipes need a real tab, not spaces. That is the number-one Makefile
error.

---

## 4. `APP_ENV`: local, dev, test, staging, prod

**Short answer:** `APP_ENV` is just a **label**. It only changes behavior where
our code checks it. The names are conventions, not magic.

**Typical meanings**

| Value | Where | What usually changes |
|---|---|---|
| `local` | your laptop | readable logs, debug tracebacks, local services, relaxed CORS |
| `dev` | shared dev server | real integrations, debug allowed, test data |
| `test` | CI | deterministic, mocks, ephemeral DB, no paid API calls |
| `staging` | pre-prod | production-like config, real auth, load/security tests |
| `prod` | users | JSON logs, strict CORS, docs often off, secrets from a manager, alerts |

**"Can I put `dev` on my laptop?"** Yes. The label matters only because code
branches on it. What you must avoid is *typos* (`prod `, `production`, `Prod`),
because then the branch silently does the wrong thing. Helix now validates the
value at startup:

```python
AppEnv = Literal["local", "dev", "test", "staging", "prod"]
```

An invalid value fails immediately with a clear Pydantic error. **Fail fast at
boot, not at 3 a.m. in production.**

**What we actually branch on in 0.1**

- `local` / `dev` → human-readable console logs.
- `staging` / `prod` → JSON logs for log shippers.

Later we will use it for docs exposure, CORS, cookie security, and mock vs real
providers.

**Important:** `APP_ENV` is **not** a security control. Do not write
`if app_env == "prod": enable_auth`. Use explicit flags and secrets. Environment
names describe *where*, not *what is allowed*.

---

## 5. Log levels

Levels are severity filters. Setting a level shows that level **and above**.

| Level | Meaning | Example |
|---|---|---|
| `DEBUG` | fine-grained developer detail | prompt text, retrieval scores, timings |
| `INFO` | normal lifecycle | API started, request handled |
| `WARNING` | unexpected but handled | provider retry, fallback to Ollama |
| `ERROR` | an operation failed | request returned 500, Qdrant unreachable |
| `CRITICAL` | the service cannot function | config invalid, disk full |

- `HELIX_LOG_LEVEL=INFO` shows INFO, WARNING, ERROR, CRITICAL; hides DEBUG.
- Production default is usually `INFO`. Turn on `DEBUG` temporarily to debug,
  then turn it off.
- **Never log secrets, tokens, full documents, or PII.** Debug logs are the
  usual place this leaks.
- Logs ≠ traces ≠ metrics:
  - **logs** = discrete events,
  - **traces** = one request's timeline (we will use Langfuse),
  - **metrics** = aggregates over time (Prometheus/Grafana).

---

## 6. Config duplication: `.env` vs the Makefile

**Tfinal doubt 

in HELIX_API_PORT=8000
and in make file 
dev:final doubt 

in HELIX_API_PORT=8000
and in make file 
dev:
	uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000

but if we chnage in .env HELIX_API_PORT=8010
but still in our make file its hardcoded 8000 ? wont it cause issue?
	uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000

but if we chnage in .env HELIX_API_PORT=8010
but still in our make file its hardcoded 8000 ? wont it cause issue?he bug:** `make dev` used to hardcode `--host 127.0.0.1 --port 8000`. Changing
`HELIX_API_PORT=8010` in `.env` had no effect, because the command line is a
**second source of truth**.

**The fix:** `make dev` now runs `python -m apps.api.dev`. That module reads
`Settings` (which reads `.env` and environment variables) and passes the values
to Uvicorn:

```python
settings = get_settings()
uvicorn.run("apps.api.main:app", host=settings.api_host, port=settings.api_port)
```

**Precedence** (highest wins):

1. environment variables passed to the process,
2. `.env` file,
3. defaults in `Settings`.

So all three work:

```bash
make dev                              # .env or defaults
HELIX_API_PORT=8010 make dev          # shell override
HELIX_APP_ENV=staging make dev        # shell override
```

**Why `python -m apps.api.dev` and not `python apps/api/dev.py`?**

`-m` puts the **current working directory** on `sys.path`, so `apps` and
`helix` import normally. Running the file directly puts `apps/api/` on
`sys.path` instead, which caused `ModuleNotFoundError: No module named 'apps'`
during testing.

**Docker nuance:** the *bind port* and the *published port* are different.

- `HELIX_API_PORT` is the port Uvicorn binds **inside** the container.
- Compose maps `host_port:container_port`.
- For local dev they are the same; in Compose we will write
  `${HELIX_API_PORT:-8000}:${HELIX_API_PORT:-8000}` (or a separate
  `HELIX_HOST_PORT`) so changing one value stays consistent.

**Lesson:** every duplicated value is a future inconsistency. Let configuration
flow from one typed object.

---

## 7. Interview soundbites

- "Async is for I/O concurrency, not CPU speed. Embedding and reranking go to
  workers or a threadpool; otherwise they block the event loop."
- "Liveness asks whether to restart the process; readiness asks whether to send
  it traffic."
- "`APP_ENV` is a label that must be validated. Security decisions use explicit
  flags and secrets, never the environment name."
- "A Makefile is a tiny, shared command interface. CI runs the same targets I
  run locally."
- "I annotate context managers with `AsyncGenerator[Yield, Send]` because that
  is what the decorator actually wraps."
