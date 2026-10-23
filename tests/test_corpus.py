from __future__ import annotations

import json
from pathlib import Path

import pytest

from helix.corpus import (
    CorpusPath,
    CorpusSource,
    build_manifest,
    discover_markdown,
    estimate_child_chunks,
    prune_corpus,
    prune_source,
    select_evenly,
    text_stats,
    write_manifest,
)


def test_select_evenly_returns_all_when_under_limit() -> None:
    items = [Path("a.md"), Path("b.md"), Path("c.md")]
    assert select_evenly(items, 5) == items


def test_select_evenly_caps_and_keeps_endpoints() -> None:
    items = [Path(f"{index:02d}.md") for index in range(10)]
    selected = select_evenly(items, 5)

    assert len(selected) == 5
    assert selected[0] == items[0]
    assert selected[-1] == items[-1]
    assert selected == sorted(selected)
    assert len(set(selected)) == 5


def test_select_evenly_handles_zero_and_one() -> None:
    items = [Path("a.md"), Path("b.md")]
    assert select_evenly(items, 0) == []
    assert select_evenly(items, 1) == [Path("a.md")]
    assert select_evenly([], 5) == []


def test_select_evenly_is_deterministic() -> None:
    items = [Path(f"{index:02d}.md") for index in range(23)]
    assert select_evenly(items, 7) == select_evenly(items, 7)


def test_discover_markdown_filters_and_sorts(tmp_path: Path) -> None:
    content = tmp_path / "content"
    content.mkdir()
    (content / "b.MD").write_text("b", encoding="utf-8")
    (content / "a.md").write_text("a", encoding="utf-8")
    (content / "ignore.txt").write_text("x", encoding="utf-8")
    nested = content / "nested"
    nested.mkdir()
    (nested / "c.md").write_text("c", encoding="utf-8")

    found = discover_markdown(tmp_path, "content")

    assert [path.relative_to(tmp_path).as_posix() for path in found] == [
        "content/a.md",
        "content/b.MD",
        "content/nested/c.md",
    ]


def test_discover_markdown_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Corpus path not found"):
        discover_markdown(tmp_path, "missing")


def test_text_stats_counts_bytes_and_words(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("hello world\n", encoding="utf-8")

    assert text_stats(path) == (12, 2)


def test_estimate_child_chunks() -> None:
    assert estimate_child_chunks(0) == 0
    assert estimate_child_chunks(1) == 1
    assert estimate_child_chunks(200) == 1
    assert estimate_child_chunks(201) == 2


def test_build_manifest_counts_and_selection(tmp_path: Path) -> None:
    source_root = tmp_path / "demo"
    docs = source_root / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("alpha " * 100, encoding="utf-8")
    (docs / "b.md").write_text("beta " * 100, encoding="utf-8")
    (docs / "c.md").write_text("gamma " * 100, encoding="utf-8")

    source = CorpusSource(
        name="demo",
        repo="https://example.com/demo.git",
        commit="a" * 40,
        license="MIT",
        paths=(CorpusPath("docs", 2),),
    )

    manifest = build_manifest(tmp_path, [source])

    assert manifest["cap"] == 2
    assert manifest["totals"]["files"] == 2
    assert manifest["totals"]["words"] == 200
    assert manifest["totals"]["estimated_child_chunks"] == 1

    path = manifest["sources"][0]["paths"][0]
    assert path["available_files"] == 3
    assert path["selected_files"] == 2
    assert [file["path"] for file in manifest["sources"][0]["files"]] == [
        "docs/a.md",
        "docs/c.md",
    ]


def test_write_manifest_round_trips(tmp_path: Path) -> None:
    manifest = {"schema_version": 1, "totals": {"files": 1}}
    path = tmp_path / "nested" / "manifest.json"

    write_manifest(manifest, path)

    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_prune_source_keeps_selected_and_removes_rest(tmp_path: Path) -> None:
    root = tmp_path / "source"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("git config", encoding="utf-8")
    selected = root / "docs" / "a.md"
    selected.parent.mkdir()
    selected.write_text("a", encoding="utf-8")
    (root / "docs" / "b.md").write_text("b", encoding="utf-8")
    images = root / "images"
    images.mkdir()
    (images / "x.png").write_bytes(b"x")
    (root / "empty").mkdir()

    kept, removed = prune_source(root, ["docs/a.md"])

    assert kept == 1
    assert removed == 2
    assert selected.exists()
    assert not (root / ".git").exists()
    assert not (root / "docs" / "b.md").exists()
    assert not images.exists()
    assert not (root / "empty").exists()


def test_prune_source_refuses_to_start_when_selected_file_is_missing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    (root / ".git").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="Selected file missing"):
        prune_source(root, ["docs/missing.md"])

    assert (root / ".git").exists()


def test_prune_corpus_updates_manifest(tmp_path: Path) -> None:
    source_root = tmp_path / "demo"
    selected = source_root / "docs" / "a.md"
    selected.parent.mkdir(parents=True)
    selected.write_text("a", encoding="utf-8")
    (source_root / "docs" / "b.md").write_text("b", encoding="utf-8")

    manifest = {
        "corpus_root": str(tmp_path),
        "sources": [{"name": "demo", "files": [{"path": "docs/a.md"}]}],
    }

    prune_corpus(manifest, tmp_path)

    assert manifest["pruned"] is True
    assert manifest["prune"] == {"kept_files": 1, "removed_files": 1}
    assert selected.exists()
    assert not (source_root / "docs" / "b.md").exists()
