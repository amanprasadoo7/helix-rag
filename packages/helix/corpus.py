from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CORPUS_ROOT = Path("data/corpus")
MANIFEST_PATH = Path("data/manifest.json")
MAX_FILES = 2_500
WORDS_PER_CHUNK = 200


@dataclass(frozen=True)
class CorpusPath:
    path: str
    limit: int


@dataclass(frozen=True)
class CorpusSource:
    name: str
    repo: str
    commit: str
    license: str
    paths: tuple[CorpusPath, ...]


HANDBOOK = CorpusSource(
    name="handbook",
    repo="https://gitlab.com/gitlab-com/content-sites/handbook.git",
    commit="438cdf82c3002b933fba36ba0c3a969d49dc52fe",
    license="MIT (upstream LICENSE)",
    paths=(CorpusPath("content/handbook", 1_000),),
)

GITLAB_DOCS = CorpusSource(
    name="gitlab-docs",
    repo="https://gitlab.com/gitlab-org/gitlab.git",
    commit="62815568f76adcf6afd36543a8cb83eafd28d937",
    license="CC BY-SA 4.0 (doc/ per upstream LICENSE)",
    paths=(
        CorpusPath("doc/user", 650),
        CorpusPath("doc/administration", 300),
        CorpusPath("doc/api", 200),
        CorpusPath("doc/ci", 150),
        CorpusPath("doc/security", 32),
        CorpusPath("doc/topics", 48),
        CorpusPath("doc/auth", 10),
        CorpusPath("doc/install", 29),
        CorpusPath("doc/operations", 25),
        CorpusPath("doc/subscriptions", 18),
        CorpusPath("doc/tutorials", 38),
    ),
)

SOURCES = (HANDBOOK, GITLAB_DOCS)


def select_evenly(items: Sequence[Path], limit: int) -> list[Path]:
    """Take at most ``limit`` items, evenly spaced over the sorted input."""
    ordered = sorted(items, key=lambda item: item.as_posix())
    if limit <= 0 or not ordered:
        return []
    if limit >= len(ordered):
        return ordered
    if limit == 1:
        return [ordered[0]]

    step = (len(ordered) - 1) / (limit - 1)
    indices = [round(index * step) for index in range(limit)]
    return [ordered[index] for index in indices]


def discover_markdown(root: Path, relative_path: str) -> list[Path]:
    base = root / relative_path
    if not base.is_dir():
        raise FileNotFoundError(f"Corpus path not found: {base}")
    return sorted(
        (
            path
            for path in base.rglob("*")
            if path.is_file() and path.suffix.lower() == ".md"
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def text_stats(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    return len(raw), len(text.split())


def estimate_child_chunks(words: int, words_per_chunk: int = WORDS_PER_CHUNK) -> int:
    if words <= 0:
        return 0
    return max(1, math.ceil(words / words_per_chunk))


def build_source_manifest(root: Path, source: CorpusSource) -> dict[str, Any]:
    paths: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    total_bytes = 0
    total_words = 0

    for spec in source.paths:
        available = discover_markdown(root, spec.path)
        selected = select_evenly(available, spec.limit)
        path_bytes = 0
        path_words = 0

        for path in selected:
            file_bytes, file_words = text_stats(path)
            path_bytes += file_bytes
            path_words += file_words
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": file_bytes,
                    "words": file_words,
                }
            )

        paths.append(
            {
                "path": spec.path,
                "limit": spec.limit,
                "available_files": len(available),
                "selected_files": len(selected),
                "bytes": path_bytes,
                "words": path_words,
                "estimated_child_chunks": estimate_child_chunks(path_words),
            }
        )
        total_bytes += path_bytes
        total_words += path_words

    return {
        "name": source.name,
        "repo": source.repo,
        "commit": source.commit,
        "license": source.license,
        "paths": paths,
        "totals": {
            "files": len(files),
            "bytes": total_bytes,
            "words": total_words,
            "estimated_child_chunks": estimate_child_chunks(total_words),
        },
        "files": files,
    }


def build_manifest(
    root: Path, sources: Sequence[CorpusSource] = SOURCES
) -> dict[str, Any]:
    source_manifests = [
        build_source_manifest(root / source.name, source) for source in sources
    ]
    cap = sum(spec.limit for source in sources for spec in source.paths)
    if cap > MAX_FILES:
        raise ValueError(f"Corpus quota {cap} exceeds cap {MAX_FILES}")

    total_files = sum(source["totals"]["files"] for source in source_manifests)
    total_bytes = sum(source["totals"]["bytes"] for source in source_manifests)
    total_words = sum(source["totals"]["words"] for source in source_manifests)

    if total_files > MAX_FILES:
        raise ValueError(f"Selected {total_files} files, above cap {MAX_FILES}")

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_root": root.as_posix(),
        "cap": cap,
        "selection": "evenly spaced over sorted paths; includes first and last",
        "chunk_estimate": f"ceil(words / {WORDS_PER_CHUNK})",
        "license_notice": "See NOTICE in the repository root and data/corpus/NOTICE.",
        "sources": source_manifests,
        "totals": {
            "files": total_files,
            "bytes": total_bytes,
            "words": total_words,
            "estimated_child_chunks": estimate_child_chunks(total_words),
        },
    }


def write_manifest(manifest: dict[str, Any], path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
