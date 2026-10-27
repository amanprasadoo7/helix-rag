"""Write the ACL sidecar index for the manifest-selected corpus.

The classifier never mutates parsed JSON. It reads the manifest, classifies each
``(source, path)`` pair with the reviewed path policy, and writes two
deterministic files:

- ``data/acl/index.json``: one decision per document, with audit fields;
- ``data/acl/summary.json``: counts by classification, rule, and source.

Duplicate ``(source, path)`` keys are rejected instead of merged. The summary
records the manifest SHA-256 and no wall-clock timestamp, so two runs over the
same manifest produce identical output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from helix.acl import DEFAULT_POLICY, POLICY_VERSION, AclDecision, AclPolicy

MANIFEST_PATH = Path("data/manifest.json")
OUTPUT_ROOT = Path("data/acl")


@dataclass(frozen=True)
class ManifestEntry:
    source: str
    path: str


def load_manifest(
    manifest_path: Path,
) -> tuple[dict[str, Any], list[ManifestEntry], str]:
    """Read the manifest and return it, its entries, and its SHA-256."""
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")

    entries: list[ManifestEntry] = []
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Manifest is missing a sources list")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Manifest source must be an object")
        name = source.get("name")
        files = source.get("files")
        if not isinstance(name, str) or not isinstance(files, list):
            raise ValueError("Manifest source must have a name and files list")
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("Manifest file must have a path")
            entries.append(ManifestEntry(source=name, path=item["path"]))

    return manifest, entries, hashlib.sha256(raw).hexdigest()


def select_evenly(entries: list[ManifestEntry], limit: int) -> list[ManifestEntry]:
    """Take at most ``limit`` entries, evenly spaced over sorted input."""
    ordered = sorted(entries, key=lambda entry: (entry.source, entry.path))
    if limit <= 0 or not ordered:
        return ordered
    if limit >= len(ordered):
        return ordered
    if limit == 1:
        return [ordered[0]]

    step = (len(ordered) - 1) / (limit - 1)
    return [ordered[round(index * step)] for index in range(limit)]


def classify_entries(
    entries: list[ManifestEntry],
    policy: AclPolicy = DEFAULT_POLICY,
) -> list[AclDecision]:
    """Classify entries in deterministic order and reject duplicate keys."""
    decisions: list[AclDecision] = []
    seen: set[tuple[str, str]] = set()
    for entry in sorted(entries, key=lambda item: (item.source, item.path)):
        key = (entry.source, entry.path)
        if key in seen:
            raise ValueError(f"Duplicate ACL entry: source={key[0]} path={key[1]}")
        seen.add(key)
        decisions.append(policy.classify(entry.source, entry.path))
    return decisions


def build_index(
    decisions: list[AclDecision],
    manifest_sha256: str,
    *,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    ordered = sorted(decisions, key=lambda decision: (decision.source, decision.path))
    return {
        "schema_version": 1,
        "policy_version": policy_version,
        "manifest_sha256": manifest_sha256,
        "entries": [decision.to_dict() for decision in ordered],
    }


def build_summary(
    decisions: list[AclDecision],
    manifest_sha256: str,
    *,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    ordered = sorted(decisions, key=lambda decision: (decision.source, decision.path))
    classifications = Counter(decision.classification for decision in ordered)
    rules = Counter(decision.rule_id for decision in ordered)
    sources = Counter(decision.source for decision in ordered)
    return {
        "schema_version": 1,
        "policy_version": policy_version,
        "manifest_sha256": manifest_sha256,
        "totals": {
            "documents": len(ordered),
            "unknown": classifications.get("restricted:unknown", 0),
        },
        "classifications": {
            key: classifications[key] for key in sorted(classifications)
        },
        "rules": {key: rules[key] for key in sorted(rules)},
        "sources": {key: sources[key] for key in sorted(sources)},
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify manifest-selected documents by source and path."
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--source", help="only classify one manifest source")
    parser.add_argument("--path", help="only classify paths containing this text")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="classify at most N entries, evenly spaced (0 means all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print one line per classified document",
    )
    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"Manifest not found: {args.manifest}. Run `make corpus` first.")
        return 1

    try:
        _, entries, manifest_sha256 = load_manifest(args.manifest)
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

    try:
        decisions = classify_entries(entries)
    except ValueError as exc:
        print(f"Classification failed: {exc}")
        return 1

    index = build_index(decisions, manifest_sha256)
    summary = build_summary(decisions, manifest_sha256)
    write_json(args.output / "index.json", index)
    write_json(args.output / "summary.json", summary)

    totals = summary["totals"]
    print(
        f"Classified {totals['documents']} documents with {POLICY_VERSION}: "
        f"{totals['unknown']} unknown"
    )
    for classification, count in summary["classifications"].items():
        print(f"  {classification}: {count}")
    print(f"Output: {args.output}")

    if args.verbose:
        for decision in decisions:
            roles = ",".join(decision.allowed_roles) or "none"
            print(
                f"{decision.source}/{decision.path}: {decision.classification} "
                f"roles={roles} rule={decision.rule_id}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
