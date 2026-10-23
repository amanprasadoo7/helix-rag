---
type: architecture
status: implemented
day: 1
tags: [corpus, ingestion, reproducibility, licensing]
related: ["[[Checklist]]", "[[2026-10-23]]", "[[Storage-Layers]]"]
---

# Corpus: pinned GitLab handbook and docs

## What we built

`make corpus` downloads a reproducible snapshot of two public GitLab sources
into `data/corpus` and writes `data/manifest.json`:

| Source | Commit | Files | Words | Estimated child chunks |
|---|---|---:|---:|---:|
| GitLab Handbook (`content/handbook`) | `438cdf82c3002b933fba36ba0c3a969d49dc52fe` | 1,000 | 1,409,472 | 7,048 |
| GitLab product docs (`doc/*`) | `62815568f76adcf6afd36543a8cb83eafd28d937` | 1,500 | 2,575,510 | 12,878 |
| **Total** | | **2,500** | **3,984,982** | **19,925** |

The snapshot is about 32 MB of Markdown and about 188 MB on disk including the
partial Git checkouts. The corpus is gitignored; only the fetcher, manifest
schema, tests, and `NOTICE` are committed.

## Why pin commits

A corpus is training data for retrieval. If the source moves, yesterday's
evaluation is no longer comparable to today's. Pinning a commit gives:

- **Reproducibility:** the same manifest points to the same text.
- **Citation stability:** a citation can include the commit and file path.
- **A safe refresh ritual:** change the SHA, re-run, re-baseline the eval, and
  update `NOTICE`. Drift is visible instead of silent.

The trade-off is staleness. That is deliberate: production would run a scheduled
ingest that updates the pin, re-embeds changed documents, and tombstones removed
ones.

## Partial clone and sparse checkout

The GitLab monorepo is far too large to check out wholesale. We use three Git
features together:

1. `git fetch --depth 1 <commit>` - one commit, no history.
2. `--filter=blob:none` - commit and tree objects first; blobs are downloaded
   only when a checked-out file needs them.
3. `git sparse-checkout set <dirs>` - only the selected directories appear in
   the working tree.

Plain language: Git normally downloads every version of every file. Here it
downloads the map of the repository, then only the files under the directories
we asked for, at exactly one commit.

## Selection: quotas plus even spacing

The handbook has 4,186 Markdown files and the selected product-doc directories
have 1,981. The cap is 2,500, so we cannot take everything. Each path has a
quota:

| Path | Available | Selected |
|---|---:|---:|
| `content/handbook` | 4,186 | 1,000 |
| `doc/user` | 946 | 650 |
| `doc/administration` | 387 | 300 |
| `doc/api` | 256 | 200 |
| `doc/ci` | 176 | 150 |
| `doc/security` | 32 | 32 |
| `doc/topics` | 48 | 48 |
| `doc/auth` | 10 | 10 |
| `doc/install` | 29 | 29 |
| `doc/operations` | 25 | 25 |
| `doc/subscriptions` | 18 | 18 |
| `doc/tutorials` | 54 | 38 |

Within a path, files are sorted and sampled at even intervals, including the
first and last. Taking the first N would bias the corpus toward alphabetically
early subdirectories. Even spacing is deterministic, covers the whole path, and
keeps the manifest stable across runs.

Quotas are a product decision, not a law. They live in
`packages/helix/corpus.py`; changing one changes the manifest and should trigger
a fresh eval baseline.

## Manifest

`data/manifest.json` is the contract between fetching and ingestion. It records:

- the two repositories and full commit SHAs,
- every selected file with its bytes and word count,
- per-path availability and selection counts,
- per-source and total estimates,
- the selection strategy and license pointer.

The estimated chunk count is `ceil(words / 200)`. That assumes roughly 200 words
per child chunk (about 250 tokens) and ignores overlap. It is a capacity-planning
number, not the chunker's final output.

## Licensing and attribution

- **GitLab Handbook:** upstream `LICENSE` is MIT. Copyright GitLab B.V. Some
  embedded third-party material may carry separate terms.
- **GitLab product documentation:** all content under `doc/` is CC BY-SA 4.0
  according to the upstream root `LICENSE`. Copyright GitLab Inc.

`NOTICE` is committed and copied into `data/corpus/NOTICE`. If the corpus or
derived text is redistributed, the notice and attribution stay with it. This is
also why the corpus itself is not committed: the repository carries the recipe,
not a second copy of the data.

## Commands

```bash
make corpus
python3 -m json.tool data/manifest.json | less
```

Useful checks:

```bash
python3 -c 'import json; m=json.load(open("data/manifest.json")); print(m["totals"])'
python3 -c 'import json; m=json.load(open("data/manifest.json")); print([(s["name"], s["commit"][:12], s["totals"]["files"]) for s in m["sources"]])'
```

Re-fetch from scratch:

```bash
uv run python scripts/fetch_corpus.py --force
```

A normal re-run reuses the existing checkout, re-checks out the pinned commit,
and rewrites the manifest. The selection is deterministic, so the counts should
not change unless a quota or the pin changes.

## What can break

- **Network or upstream removal:** the pinned commit may disappear. Keep the
  full SHA and a manifest; a mirror is the long-term fix.
- **Partial clone without the server filter:** GitLab supports
  `--filter=blob:none`; another host may not. The fallback is a full clone.
- **Quota changes:** the corpus changes, so retrieval quality changes. Re-run
  the golden set before comparing.
- **Word-count estimate:** frontmatter, tables, and code fences inflate it. The
  real numbers come from the chunker.

## Alternatives considered

| Option | Why not |
|---|---|
| Clone both repositories fully | Too slow and large for a local exercise; most files are irrelevant. |
| GitLab API per file | Many requests, rate limits, and no atomic snapshot. |
| GitLab's generated docs site | HTML navigation and boilerplate add noise; source Markdown is cleaner. |
| Hugging Face dataset | Not authoritative for this snapshot and harder to pin to a Git commit. |
| Take the first N files | Alphabetical bias; even spacing is more representative. |

## Interview angle

- "The corpus is a versioned artifact. I pin the commit, record the manifest,
  and re-baseline the eval when the pin moves."
- "A 2,500-file cap is a product constraint. I allocate quotas per area and
  sample evenly, rather than letting one huge directory dominate."
- "I use partial clone and sparse checkout because the GitLab monorepo is much
  larger than the retrieval corpus."
- "Licensing is part of data engineering: the docs are CC BY-SA 4.0, the
  handbook repository is MIT, and the NOTICE travels with derived text."
- "The manifest is the interface between ingestion and evaluation. If the
  manifest changes, the eval baseline must change too."
