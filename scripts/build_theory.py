from __future__ import annotations

import argparse
from pathlib import Path

from helix.docs import THEORY_PATH, VAULT_ROOT, write_theory


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the self-contained study guide from the Obsidian vault."
    )
    parser.add_argument("--vault", type=Path, default=VAULT_ROOT)
    parser.add_argument("--output", type=Path, default=THEORY_PATH)
    parser.add_argument("--title", default="Helix Study Guide")
    args = parser.parse_args()

    count = write_theory(args.vault, args.output, args.title)
    print(f"Wrote {args.output} from {count} notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
