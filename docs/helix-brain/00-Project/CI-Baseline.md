---
type: process
status: active
day: 3
tags: [ci, github-actions, quality, process]
related: ["[[Checklist]]", "[[Project-Map]]", "[[2026-10-25]]"]
---

# CI baseline: one gate, local and remote

**Short answer:** GitHub Actions runs the same command we run locally, `make ci`.
That command checks formatting/lint with Ruff, types with mypy, and unit tests
with pytest. CI does not duplicate those commands in YAML, and it does not run
the integration tests that need Docker Compose.

The goal is not "a green badge." The goal is to make the merge decision
repeatable: if `make ci` passes locally and the same command passes in CI, the
change has cleared the baseline checks we agreed on.

## What runs

`.github/workflows/ci.yml` runs on:

- pushes to `master`,
- pull requests,
- manual `workflow_dispatch`.

The job is deliberately small:

| Step | Command | Why |
|---|---|---|
| Check out | `actions/checkout` | Get the exact commit under test |
| Set up tools | `astral-sh/setup-uv` | Install uv and Python 3.12; cache by `uv.lock` |
| Install | `uv sync --locked` | Install the locked environment, or fail if the lock is stale |
| Gate | `make ci` | Run Ruff, mypy, and pytest through the local command |

The job also has:

- `permissions: contents: read` because it only reads the repository,
- a concurrency group so a new push cancels an older run on the same ref,
- a 10-minute timeout so a hung test does not hold a runner forever.

## Why one command instead of three YAML steps

It would be easy to write this:

```yaml
- run: ruff check .
- run: mypy packages/helix apps
- run: pytest -m "not integration"
```

That creates a second source of truth. The next time the local gate changes,
someone has to remember to change both places. Instead, CI calls `make ci`, and
the Makefile remains the only definition of the gate.

This is the same principle as the config work in [[Foundations]]: one typed
source of truth, not a copy that can drift.

## Why `uv sync --locked`

`uv.lock` is part of the build. It records the exact dependency versions that
were tested. `uv sync --locked` has two jobs:

1. install that environment, and
2. fail if `pyproject.toml` and `uv.lock` disagree.

Without `--locked`, CI could silently resolve newer packages and pass on a
different environment from the one committed. If the lock is stale, the correct
fix is to run `uv lock` locally, review the diff, and commit `uv.lock` with the
change.

The setup action caches uv's downloads using `uv.lock` as the key. A dependency
change invalidates the cache; an unrelated code change reuses it.

## Why integration tests are not in this job

`make test-integration` needs Postgres, Redis, Qdrant, and MinIO. The baseline
job is meant to be fast and independent of Docker services, so it runs only
`make ci`, which uses `pytest -m "not integration"`.

That is a deliberate gap, not a claim that integration tests do not matter.
They still run locally with `make up` and `make test-integration`. A later
checkpoint can add a separate integration job with service containers or a
Compose startup step.

## Why Python 3.12 only

The project declares `requires-python = ">=3.12,<3.13"` and pins `.python-version`
to `3.12`. A version matrix would add runtime without testing a supported
configuration. When the project supports another Python version, add a matrix
then, not before.

## Manual test

Run the local gate first:

```bash
make ci
```

Expected: Ruff and mypy pass, then pytest reports `37 passed, 1 deselected`.

Then verify the remote path:

1. Push a branch and open a pull request.
2. Open the **Actions** tab.
3. Confirm the `CI / lint and test` check is green.
4. Confirm the job used Python 3.12 and ran `uv sync --locked` and `make ci`.

To prove the gate can fail, introduce a deliberate lint error on a scratch
branch, for example an unused import, push it, and confirm Ruff fails the check.
Remove the error before merging.

## What this baseline does not cover

| Not covered | Why | Where it belongs |
|---|---|---|
| Integration tests | Need the four local services | Later CI job or release gate |
| Security scans | No dependency/image scanning yet | M4/M5 |
| Coverage threshold | No agreed number yet | M5 evaluation work |
| Deployment | This is a quality gate, not a release pipeline | Later infrastructure work |
| Dependency updates | No automated update bot yet | After the baseline is stable |

## Common doubts

### Isn't `make ci` just a wrapper?

Yes, and that is the point. A wrapper with one definition is better than three
copies that drift. It also means the local and remote gates cannot disagree
about which checks are required.

### Why pin action versions?

Actions are code that runs with repository access. Pinning a release tag makes
the run reproducible and makes upgrades deliberate. A stricter setup would pin
full commit SHAs and add a dependency updater; that can come later.

### Why not run on every branch push?

Pull requests already trigger the workflow. Running on every branch push as well
would duplicate work for branches that are not under review. `master` is checked
because it is the merge target.

### What do I do when CI fails but local `make ci` passes?

Check the Python version and lockfile first. CI uses Python 3.12 and
`uv sync --locked`; a local environment with a different Python or an outdated
lock can hide the difference. Then check for untracked files or environment
variables that the test accidentally depends on.

## Interview angle

- "CI calls the same `make ci` target I run locally, so the gate has one
  definition and no YAML drift."
- "I use `uv sync --locked` so CI fails on a stale lock instead of silently
  testing a different dependency graph."
- "The baseline job is fast and unit-only; integration tests are a separate
  concern because they need stateful services."
- "Least privilege, concurrency cancellation, and a timeout are part of the
  workflow, not afterthoughts."
