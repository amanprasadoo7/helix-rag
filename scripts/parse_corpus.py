from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from helix.parsing import Document, parse_markdown

CORPUS_ROOT = Path("data/corpus")
MANIFEST_PATH = Path("data/manifest.json")
OUTPUT_ROOT = Path("data/parsed")


@dataclass(frozen=True)
class Entry:
    source: str
    path: str
    commit: str
    file_path: Path


def select_evenly(entries: list[Entry], limit: int) -> list[Entry]:
    if limit <= 0 or limit >= len(entries):
        return entries
    if limit == 1:
        return [entries[0]]
    step = (len(entries) - 1) / (limit - 1)
    return [entries[round(index * step)] for index in range(limit)]


def load_entries(manifest_path: Path, corpus_root: Path) -> list[Entry]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries: list[Entry] = []
    for source in manifest["sources"]:
        name = source["name"]
        commit = source["commit"]
        for item in source["files"]:
            path = item["path"]
            entries.append(
                Entry(
                    source=name,
                    path=path,
                    commit=commit,
                    file_path=corpus_root / name / path,
                )
            )
    return sorted(entries, key=lambda entry: (entry.source, entry.path))


def output_path(output_root: Path, entry: Entry) -> Path:
    relative = PurePosixPath(entry.path).with_suffix(".json")
    return output_root / entry.source / relative


def aggregate(doc: Document) -> dict[str, int]:
    stats = doc.stats
    return {
        "sections": stats.sections,
        "blocks": stats.blocks,
        "words": stats.words,
        "chars": stats.chars,
        "code_blocks": stats.code_blocks,
        "tables": stats.tables,
        "shortcodes_removed": stats.shortcodes_removed,
        "warnings": len(doc.warnings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse manifest-selected Markdown into normalized JSON."
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--source", help="only parse one manifest source")
    parser.add_argument("--path", help="only parse paths containing this text")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="parse at most N entries, evenly spaced (0 means all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print one line per parsed document",
    )
    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"Manifest not found: {args.manifest}. Run `make corpus` first.")
        return 1
    if not args.corpus_root.is_dir():
        print(f"Corpus not found: {args.corpus_root}. Run `make corpus` first.")
        return 1

    entries = load_entries(args.manifest, args.corpus_root)
    if args.source:
        entries = [entry for entry in entries if entry.source == args.source]
    if args.path:
        entries = [entry for entry in entries if args.path in entry.path]
    entries = select_evenly(entries, args.limit)

    if not entries:
        print("No documents matched the filters.")
        return 1

    totals = {
        "documents": 0,
        "sections": 0,
        "blocks": 0,
        "words": 0,
        "chars": 0,
        "code_blocks": 0,
        "tables": 0,
        "shortcodes_removed": 0,
        "warnings": 0,
    }
    failures: list[dict[str, str]] = []
    warning_samples: list[dict[str, str]] = []

    for entry in entries:
        try:
            text = entry.file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(
                {
                    "source": entry.source,
                    "path": entry.path,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        doc = parse_markdown(
            text,
            source=entry.source,
            path=entry.path,
            commit=entry.commit,
        )
        destination = output_path(args.output, entry)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(doc.to_json(), encoding="utf-8")

        totals["documents"] += 1
        for key, value in aggregate(doc).items():
            totals[key] += value
        for warning in doc.warnings:
            if len(warning_samples) < 20:
                warning_samples.append({"path": entry.path, "warning": warning})

        if args.verbose:
            print(
                f"{entry.source}/{entry.path}: "
                f"sections={doc.stats.sections} blocks={doc.stats.blocks} "
                f"words={doc.stats.words} warnings={len(doc.warnings)}"
            )

    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest": args.manifest.as_posix(),
        "output": args.output.as_posix(),
        "totals": totals,
        "failures": failures,
        "warnings": warning_samples,
    }
    summary_path = args.output / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        "Parsed {documents} documents: {sections} sections, {blocks} blocks, "
        "{words} words, {code_blocks} code blocks, {tables} tables, "
        "{warnings} warnings".format(**totals)
    )
    print(f"Output: {args.output}")
    if failures:
        print(f"Failures: {len(failures)} (see {summary_path})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
