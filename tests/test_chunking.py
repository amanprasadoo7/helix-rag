from __future__ import annotations

from pathlib import Path

import pytest
from scripts.chunk_corpus import build_summary, percentile

from helix.chunking import (
    DEFAULT_CONFIG,
    ChunkerConfig,
    chunk_document,
)
from helix.parsing import Block, Document, Section, parse_markdown


def make_section(
    section_id: str,
    title: str,
    *,
    level: int = 2,
    breadcrumb: list[str] | None = None,
    blocks: list[Block] | None = None,
    children: list[Section] | None = None,
) -> Section:
    return Section(
        id=section_id,
        level=level,
        title=title,
        heading=title,
        breadcrumb=breadcrumb or ["Guide", title],
        blocks=blocks or [],
        children=children or [],
    )


def make_document(root: Section, *, path: str = "content/handbook/test.md") -> Document:
    return Document(
        source="handbook",
        path=path,
        commit="abc123",
        title="Guide",
        root=root,
    )


def paragraph(text: str) -> Block:
    return Block(type="paragraph", text=text)


def test_short_section_becomes_one_child_with_breadcrumb() -> None:
    document = parse_markdown(
        "# Guide\n\n## Install\n\nRun the installer from the terminal.",
        source="handbook",
        path="content/handbook/test.md",
        commit="abc123",
    )

    chunked = chunk_document(document)

    assert chunked.stats.children == 1
    child = chunked.children[0]
    assert child.text == "Run the installer from the terminal."
    assert child.section_path == ["Guide", "Install"]
    assert child.embedding_text.startswith("Guide > Install\n\n")
    assert child.parent_id == "section:install"
    assert child.commit == "abc123"

    parent = next(item for item in chunked.parents if item.id == "section:install")
    assert parent.text == child.text
    assert parent.own_child_ids == [child.id]
    assert parent.child_ids == [child.id]


def test_children_never_cross_a_heading() -> None:
    document = parse_markdown(
        "# Guide\n\n## Alpha\n\nAlpha body.\n\n## Beta\n\nBeta body.",
        source="handbook",
        path="content/handbook/test.md",
    )

    chunked = chunk_document(document)
    texts = [child.text for child in chunked.children]

    assert texts == ["Alpha body.", "Beta body."]
    assert len({child.parent_id for child in chunked.children}) == 2


def test_long_section_splits_and_overlaps_at_sentences() -> None:
    sentences = [
        f"Sentence number {index} carries a few useful words for the test."
        for index in range(60)
    ]
    section = make_section(
        "long",
        "Long section",
        blocks=[paragraph(" ".join(sentences))],
    )
    document = make_document(
        make_section("empty", "Guide", level=0, children=[section])
    )
    chunked = chunk_document(
        document,
        config=ChunkerConfig(target_words=60, max_words=90, overlap_words=20),
    )

    assert chunked.stats.children >= 2
    first, second = chunked.children[0], chunked.children[1]
    assert second.overlap_words > 0
    last_sentence = first.text.split(". ")[-1]
    assert last_sentence in second.text
    assert all(child.words <= 90 for child in chunked.children)


def test_lists_split_on_item_boundaries() -> None:
    items = [
        {"text": f"Step {index} explains one complete operation.", "level": 0}
        for index in range(12)
    ]
    section = make_section(
        "steps",
        "Steps",
        blocks=[
            Block(
                type="list",
                text="\n".join(item["text"] for item in items),
                meta={"ordered": True, "items": items},
            )
        ],
    )
    document = make_document(make_section("root", "Guide", level=0, children=[section]))

    chunked = chunk_document(
        document,
        config=ChunkerConfig(target_words=20, max_words=30, overlap_words=5),
    )

    assert chunked.stats.children > 1
    known = {item["text"] for item in items}
    for child in chunked.children:
        assert child.text.splitlines()
        assert set(child.text.splitlines()) <= known


def test_oversized_table_splits_by_rows_and_repeats_header() -> None:
    rows = [["row", str(index), "value with several words in it"] for index in range(80)]
    table_text = "\n".join(" | ".join(row) for row in rows)
    section = make_section(
        "table",
        "Big table",
        blocks=[
            Block(
                type="table",
                text=table_text,
                meta={"headers": ["kind", "index", "value"], "rows": rows},
            )
        ],
    )
    document = make_document(make_section("root", "Guide", level=0, children=[section]))

    chunked = chunk_document(document)

    assert chunked.stats.children > 1
    assert all("kind | index | value" in child.text for child in chunked.children)
    assert all(child.words <= DEFAULT_CONFIG.max_words for child in chunked.children)
    assert chunked.stats.oversize_children == 0
    joined = "\n".join(child.text for child in chunked.children)
    for row in rows:
        assert " | ".join(row) in joined


def test_code_is_kept_whole() -> None:
    code = "\n".join(f"kubectl describe pod pod-{index}" for index in range(120))
    section = make_section(
        "code",
        "Commands",
        blocks=[Block(type="code", text=code, meta={"language": "bash"})],
    )
    document = make_document(make_section("root", "Guide", level=0, children=[section]))

    chunked = chunk_document(
        document,
        config=ChunkerConfig(target_words=20, max_words=30, overlap_words=0),
    )

    assert chunked.stats.children == 1
    assert chunked.children[0].text == code
    assert chunked.children[0].oversize


def test_ids_are_deterministic_and_stable_when_neighbours_change() -> None:
    stable = make_section("stable", "Stable", blocks=[paragraph("This text does not change.")])
    first = make_document(
        make_section(
            "root",
            "Guide",
            level=0,
            children=[
                make_section("other", "Other", blocks=[paragraph("A different section.")]),
                stable,
            ],
        )
    )
    second = make_document(
        make_section(
            "root",
            "Guide",
            level=0,
            children=[
                make_section("new", "New", blocks=[paragraph("A new section appears.")]),
                make_section("other", "Other", blocks=[paragraph("A different section.")]),
                stable,
            ],
        )
    )

    first_chunked = chunk_document(first)
    second_chunked = chunk_document(second)
    first_stable = next(
        child
        for child in first_chunked.children
        if child.parent_id == "section:stable"
    )
    second_stable = next(
        child
        for child in second_chunked.children
        if child.parent_id == "section:stable"
    )

    assert first_stable.ordinal != second_stable.ordinal
    assert first_stable.id == second_stable.id
    assert first_chunked.to_json() == chunk_document(first).to_json()


def test_identical_text_in_one_section_gets_unique_ids() -> None:
    section = make_section(
        "dupes",
        "Duplicates",
        blocks=[paragraph("Same short text here."), paragraph("Same short text here.")],
    )
    document = make_document(make_section("root", "Guide", level=0, children=[section]))

    chunked = chunk_document(
        document,
        config=ChunkerConfig(target_words=5, max_words=10, overlap_words=0),
    )

    assert len(chunked.children) == 2
    assert chunked.children[0].text == chunked.children[1].text
    assert chunked.children[0].id != chunked.children[1].id


def test_empty_section_keeps_parent_but_produces_no_child() -> None:
    empty = make_section("empty", "Empty")
    document = make_document(make_section("root", "Guide", level=0, children=[empty]))

    chunked = chunk_document(document)

    assert chunked.children == []
    parent = next(item for item in chunked.parents if item.id == "section:empty")
    assert parent.text == ""
    assert parent.has_content is False
    assert parent.child_ids == []
    assert "document produced no chunks" in chunked.warnings


def test_parent_child_ids_include_descendants() -> None:
    leaf = make_section("leaf", "Leaf", blocks=[paragraph("Leaf text.")])
    branch = make_section("branch", "Branch", children=[leaf])
    document = make_document(make_section("root", "Guide", level=0, children=[branch]))

    chunked = chunk_document(document)
    child = chunked.children[0]
    branch_parent = next(item for item in chunked.parents if item.id == "section:branch")
    root_parent = chunked.parents[0]

    assert branch_parent.own_child_ids == []
    assert branch_parent.child_ids == [child.id]
    assert root_parent.child_ids == [child.id]


def test_root_preamble_is_chunked() -> None:
    root = make_section(
        "root",
        "Guide",
        level=0,
        breadcrumb=["Guide"],
        blocks=[paragraph("This is the document preamble.")],
    )
    document = make_document(root)

    chunked = chunk_document(document)

    assert len(chunked.children) == 1
    assert chunked.children[0].parent_id == "root"
    assert chunked.children[0].section_path == ["Guide"]


def test_config_rejects_invalid_budgets() -> None:
    with pytest.raises(ValueError, match="target_words"):
        ChunkerConfig(target_words=0)
    with pytest.raises(ValueError, match="max_words"):
        ChunkerConfig(target_words=100, max_words=50)
    with pytest.raises(ValueError, match="overlap_words"):
        ChunkerConfig(target_words=100, max_words=200, overlap_words=100)


def test_percentile_and_summary_are_deterministic() -> None:
    section = make_section("one", "One", blocks=[paragraph("One two three four five.")])
    document = make_document(make_section("root", "Guide", level=0, children=[section]))
    chunked = chunk_document(document)

    assert percentile([10, 20, 30, 40], 0.50) == 20
    assert percentile([10, 20, 30, 40], 0.95) == 40
    assert percentile([], 0.95) == 0

    summary = build_summary([chunked], "manifest-sha")
    assert summary["totals"]["documents"] == 1
    assert summary["totals"]["children"] == 1
    assert summary["sizes"]["p50"] == chunked.children[0].words
    assert summary["buckets"]["under_50"] == 1
    assert "generated_at" not in summary


REAL_DOCUMENT = Path(
    "data/parsed/handbook/content/handbook/business-technology/"
    "enterprise-applications/guides/zuora-collect.json"
)


@pytest.mark.skipif(not REAL_DOCUMENT.is_file(), reason="parsed corpus not present")
def test_real_zuora_document_splits_accounts_section() -> None:
    document = Document.model_validate_json(REAL_DOCUMENT.read_text(encoding="utf-8"))
    chunked = chunk_document(document)

    accounts = [child for child in chunked.children if child.section_path[-1] == "Accounts"]

    assert len(accounts) == 2
    assert [child.words for child in accounts] == [156, 210]
    assert accounts[1].overlap_words == 10
    assert any(
        "Comments cannot be edited or deleted by design." in child.text
        for child in chunked.children
    )
