"""Chunk the parsed corpus into parent sections and child chunks.

Reads one parsed JSON document per manifest entry, writes a deterministic chunk
file under ``data/chunks`` and a ``summary.json`` with the size distribution.
The chunker never reads the raw Markdown; it consumes the parser output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from helix.chunking import ChunkedDocument, chunk_document
from helix.parsing import Document

MANIFEST_PATH = Path("data/manifest.json")
PARSED_ROOT = Path("data/parsed")
OUTPUT_ROOT = Path("data/chunks")


@dataclass(frozen=True)
class Entry:
    source: str
    path: str
    commit: str


def load_entries(manifest_path: Path) -> tuple[list[Entry], str]:
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")

    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Manifest is missing a sources list")

    entries: list[Entry] = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Manifest source must be an object")
        name = source.get("name")
        commit = source.get("commit", "")
        files = source.get("files")
        if not isinstance(name, str) or not isinstance(files, list):
            raise ValueError("Manifest source must have a name and files list")
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("Manifest file must have a path")
            entries.append(Entry(source=name, path=item["path"], commit=str(commit)))

    entries.sort(key=lambda entry: (entry.source, entry.path))
    return entries, hashlib.sha256(raw).hexdigest()


def select_evenly(entries: Sequence[Entry], limit: int) -> list[Entry]:
    ordered = list(entries)
    if limit <= 0 or not ordered:
        return ordered
    if limit >= len(ordered):
        return ordered
    if limit == 1:
        return [ordered[0]]
    step = (len(ordered) - 1) / (limit - 1)
    return [ordered[round(index * step)] for index in range(limit)]


def parsed_path(root: Path, entry: Entry) -> Path:
    relative = PurePosixPath(entry.path).with_suffix(".json")
    return root / entry.source / relative


def output_path(root: Path, entry: Entry) -> Path:
    return parsed_path(root, entry)


def percentile(values: list[int], fraction: float) -> int:
    """Nearest-rank percentile over an already sorted list."""
    if not values:
        return 0
    rank = max(0, math.ceil(fraction * len(values)) - 1)
    return values[min(rank, len(values) - 1)]


def _bucket(words: int) -> str:
    if words < 50:
        return "under_50"
    if words < 100:
        return "50_to_99"
    if words < 200:
        return "100_to_199"
    if words < 300:
        return "200_to_299"
    if words < 400:
        return "300_to_399"
    return "400_plus"


def build_summary(
    documents: list[ChunkedDocument],
    manifest_sha256: str,
    failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    ordered = sorted(documents, key=lambda document: (document.source, document.path))
    children = [child for document in ordered for child in document.children]
    sizes = sorted(child.words for child in children)

    sources: dict[str, dict[str, int]] = {}
    for document in ordered:
        entry = sources.setdefault(
            document.source,
            {"documents": 0, "children": 0, "words": 0},
        )
        entry["documents"] += 1
        entry["children"] += len(document.children)
        entry["words"] += document.stats.child_words

    buckets = Counter(_bucket(child.words) for child in children)
    totals = {
        "documents": len(ordered),
        "sections": sum(document.stats.sections for document in ordered),
        "parents": sum(document.stats.parents for document in ordered),
        "children": len(children),
        "source_words": sum(document.stats.source_words for document in ordered),
        "child_words": sum(child.words for child in children),
        "overlap_words": sum(child.overlap_words for child in children),
        "oversize_children": sum(1 for child in children if child.oversize),
        "under_100_words": sum(1 for child in children if child.words < 100),
        "empty_sections": sum(document.stats.empty_sections for document in ordered),
        "sections_without_children": sum(
            document.stats.sections_without_children for document in ordered
        ),
        "documents_without_chunks": sum(
            1 for document in ordered if not document.children
        ),
    }
    sizes_summary = {
        "min": sizes[0] if sizes else 0,
        "p50": percentile(sizes, 0.50),
        "p75": percentile(sizes, 0.75),
        "p90": percentile(sizes, 0.90),
        "p95": percentile(sizes, 0.95),
        "p99": percentile(sizes, 0.99),
        "max": sizes[-1] if sizes else 0,
    }
    return {
        "schema_version": 1,
        "manifest_sha256": manifest_sha256,
        "totals": totals,
        "sizes": sizes_summary,
        "buckets": {key: buckets.get(key, 0) for key in (
            "under_50",
            "50_to_99",
            "100_to_199",
            "200_to_299",
            "300_to_399",
            "400_plus",
        )},
        "sources": {key: sources[key] for key in sorted(sources)},
        "failures": failures or [],
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Chunk parsed manifest documents into parent/child chunks."
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--parsed-root", type=Path, default=PARSED_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--source", help="only chunk one manifest source")
    parser.add_argument("--path", help="only chunk paths containing this text")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="chunk at most N entries, evenly spaced (0 means all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print one line per chunked document",
    )
    args = parser.parse_args(argv)

    if not args.manifest.is_file():
        print(f"Manifest not found: {args.manifest}. Run `make corpus` first.")
        return 1
    if not args.parsed_root.is_dir():
        print(
            f"Parsed output not found: {args.parsed_root}. Run `make parse` first."
        )
        return 1

    try:
        entries, manifest_sha256 = load_entries(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"Could not read manifest: {type(exc).__name__}: {exc}")
        return 1

    if args.source:
        entries = [entry for entry in entries if entry.source == args.source]
    if args.path:
        entries = [entry for entry in entries if args.path in entry.path]
    entries = select_evenly(entries, args.limit)

    if not entries:
        print("No documents matched the filters.")
        return 1

    documents: list[ChunkedDocument] = []
    failures: list[dict[str, str]] = []

    for entry in entries:
        source_path = parsed_path(args.parsed_root, entry)
        try:
            document = Document.model_validate_json(
                source_path.read_text(encoding="utf-8")
            )
            chunked = chunk_document(document)
        except (OSError, ValueError) as exc:
            failures.append(
                {
                    "source": entry.source,
                    "path": entry.path,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        destination = output_path(args.output, entry)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(chunked.to_json(), encoding="utf-8")
        documents.append(chunked)

        if args.verbose:
            print(
                f"{entry.source}/{entry.path}: "
                f"sections={chunked.stats.sections} "
                f"children={chunked.stats.children} "
                f"words={chunked.stats.child_words} "
                f"oversize={chunked.stats.oversize_children}"
            )

    summary = build_summary(documents, manifest_sha256, failures)
    write_json(args.output / "summary.json", summary)

    totals = summary["totals"]
    sizes = summary["sizes"]
    print(
        "Chunked {documents} documents: {sections} sections, {parents} parents, "
        "{children} children, {child_words} child words".format(**totals)
    )
    print(
        "  sizes: p50={p50} p90={p90} p95={p95} p99={p99} max={max}".format(
            **sizes
        )
    )
    print(
        "  oversize={oversize_children} under_100={under_100_words} "
        "overlap_words={overlap_words}".format(**totals)
    )
    print(f"Output: {args.output}")
    if failures:
        print(f"Failures: {len(failures)} (see {args.output / 'summary.json'})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
