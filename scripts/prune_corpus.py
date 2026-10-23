from __future__ import annotations

import argparse
import json
from pathlib import Path

from helix.corpus import MANIFEST_PATH, prune_corpus, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Keep only the selected corpus files and remove Git checkouts."
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    root = Path(manifest["corpus_root"])
    prune_corpus(manifest, root)
    write_manifest(manifest, args.manifest)

    files = [path for path in root.rglob("*") if path.is_file()]
    size = sum(path.stat().st_size for path in files)
    print(f"Pruned corpus: {manifest['totals']['files']} selected files remain")
    print(
        f"Removed: {manifest['prune']['removed_files']} unselected files "
        "(.git removed if present)"
    )
    print(f"Disk: {size / 1_000_000:.1f} MB")
    print(f"Corpus root: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
