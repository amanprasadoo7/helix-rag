from __future__ import annotations

import re
from pathlib import Path

CHECKLIST = Path("docs/helix-brain/00-Project/Checklist.md")
STATUSES = ("pending", "in progress", "done", "blocked")


def parse_current(text: str) -> tuple[str, list[tuple[bool, str]]]:
    block = text.split("## Current checkpoint", 1)[1].split("## Roadmap", 1)[0]
    title_match = re.search(r"^### (.+)$", block, re.MULTILINE)
    title = title_match.group(1) if title_match else "unknown"
    items = [
        (mark == "x", label.strip())
        for mark, label in re.findall(r"^- \[( |x)\] (.+)$", block, re.MULTILINE)
    ]
    return title, items


def parse_roadmap(text: str) -> list[tuple[str, str, str]]:
    block = text.split("## Roadmap", 1)[1].split("## Handoff template", 1)[0]
    return [
        (number, name.strip(), status)
        for number, name, status in re.findall(
            r"^\|\s*(\d+\.\d+[a-z]?)\s*\|\s*([^|]+?)\s*\|\s*"
            r"(pending|in progress|done|blocked)\s*\|",
            block,
            re.MULTILINE,
        )
    ]


def main() -> int:
    text = CHECKLIST.read_text(encoding="utf-8")
    title, items = parse_current(text)
    roadmap = parse_roadmap(text)

    done = sum(1 for checked, _ in items if checked)
    total = len(items)
    print("Helix checkpoint status")
    print(f"Current: {title} - {done}/{total} complete")
    print()

    remaining = [label for checked, label in items if not checked]
    if remaining:
        print("Remaining:")
        for label in remaining:
            print(f"  - {label}")
    else:
        print("All current-checkpoint items are checked; ready for user verification.")
    print()

    counts = {status: 0 for status in STATUSES}
    for _, _, status in roadmap:
        counts[status] += 1
    summary = ", ".join(f"{counts[status]} {status}" for status in STATUSES)
    print(f"Roadmap: {summary}")

    active = next((row for row in roadmap if row[2] == "in progress"), None)
    if active is None:
        active = next((row for row in roadmap if row[2] == "pending"), None)
    if active:
        print(f"Next: {active[0]} - {active[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
