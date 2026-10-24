from scripts.checklist import parse_roadmap

COMPACT_TABLE = """## Roadmap

| # | Checkpoint | Status | Notes |
|---|---|---|---|
| 0.1 | Walking skeleton | done | [[Foundations]] |
| 0.5 | CI baseline | in progress | [[CI-Baseline]] |

## Handoff template
"""

ALIGNED_TABLE = """## Roadmap

| #    | Checkpoint       | Status      | Notes            |
| ---- | ---------------- | ----------- | ---------------- |
| 0.1  | Walking skeleton | done        | [[Foundations]]  |
| 0.5  | CI baseline      | in progress | [[CI-Baseline]]  |

## Handoff template
"""


def test_parse_roadmap_accepts_compact_rows() -> None:
    assert parse_roadmap(COMPACT_TABLE) == [
        ("0.1", "Walking skeleton", "done"),
        ("0.5", "CI baseline", "in progress"),
    ]


def test_parse_roadmap_accepts_aligned_rows() -> None:
    assert parse_roadmap(ALIGNED_TABLE) == [
        ("0.1", "Walking skeleton", "done"),
        ("0.5", "CI baseline", "in progress"),
    ]
