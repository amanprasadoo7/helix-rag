from __future__ import annotations

import re
from pathlib import Path

from helix.docs import (
    VAULT_ROOT,
    build_index,
    collect_notes,
    extract_title,
    parse_frontmatter,
    render_html,
    render_markdown,
    replace_wikilinks,
    rewrite_internal_anchors,
    slugify,
    write_theory,
)


def test_parse_frontmatter_reads_scalars_and_inline_lists() -> None:
    text = """---
type: concept
day: 2
tags: [python, "async"]
related: ["[[One]]", "[[Two]]"]
---
# Title

Body
"""

    meta, body = parse_frontmatter(text)

    assert meta == {
        "type": "concept",
        "day": "2",
        "tags": ["python", "async"],
        "related": ["[[One]]", "[[Two]]"],
    }
    assert body == "# Title\n\nBody\n"


def test_extract_title_removes_the_first_h1() -> None:
    title, body = extract_title("# Hello **world**\n\nText\n", "Fallback")

    assert title == "Hello world"
    assert body == "Text\n"


def test_collect_notes_skips_hidden_templates_and_nested_vault(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    (vault / "01-Architecture").mkdir(parents=True)
    (vault / "_templates").mkdir()
    (vault / ".obsidian").mkdir()
    (vault / "Helix").mkdir()
    (vault / "03-Journal").mkdir()

    (vault / "01-Architecture" / "Alpha.md").write_text(
        "---\ntype: concept\ntags: [a]\n---\n# Alpha\n\nBody\n",
        encoding="utf-8",
    )
    (vault / "03-Journal" / "2026-10-24.md").write_text(
        "# Day 2\n\nJournal\n",
        encoding="utf-8",
    )
    (vault / "_templates" / "Concept.md").write_text("# Template\n", encoding="utf-8")
    (vault / ".obsidian" / "note.md").write_text("# Hidden\n", encoding="utf-8")
    (vault / "Helix" / "Welcome.md").write_text("# Welcome\n", encoding="utf-8")

    notes = collect_notes(vault)

    assert [note.title for note in notes] == ["Alpha", "Day 2"]
    assert [note.section for note in notes] == ["Architecture", "Journal"]
    assert notes[0].slug == "01-architecture-alpha"


def test_wikilinks_resolve_to_notes_and_headings(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (vault / "Beta.md").write_text("# Beta\n\n## Setup\n", encoding="utf-8")
    notes = collect_notes(vault)
    index = build_index(notes)

    rendered = replace_wikilinks(
        "[[Alpha]] [[Beta#Setup|the setup]] [[Missing]]",
        index,
        "page",
    )

    assert '<a href="#alpha">Alpha</a>' in rendered
    assert '<a href="#beta--setup">the setup</a>' in rendered
    assert '<span class="missing-link"' in rendered


def test_wikilinks_inside_code_are_left_alone(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Alpha.md").write_text("# Alpha\n", encoding="utf-8")
    index = build_index(collect_notes(vault))

    rendered = replace_wikilinks(
        "Use `[[Alpha]]` literally.\n\n```text\n[[Alpha]]\n```\n",
        index,
        "page",
    )

    assert "`[[Alpha]]`" in rendered
    assert "```text\n[[Alpha]]\n```" in rendered
    assert '<a href="#alpha">' not in rendered


def test_slugify_and_internal_anchors() -> None:
    assert slugify("0.4 - Vault, notes & docs") == "0-4-vault-notes-docs"
    assert (
        rewrite_internal_anchors("See [After cleanup](#after-cleanup).", "page")
        == "See [After cleanup](#page--after-cleanup)."
    )


def test_render_markdown_handles_tables_code_and_callouts() -> None:
    body, toc = render_markdown(
        """## Setup

| A | B |
|---|---|
| 1 | 2 |

```python
print(1)
```

> [!warning] No `.git`
> Run `make corpus`.
""",
        "page",
    )

    assert 'id="page--setup"' in body
    assert "<table>" in body
    assert 'class="language-python"' in body
    assert '<div class="callout warning">' in body
    assert "<code>.git</code>" in body
    assert "<code>make corpus</code>" in body
    assert toc[0]["id"] == "page--setup"


def test_render_html_contains_navigation_search_and_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "01-Architecture").mkdir(parents=True)
    (vault / "01-Architecture" / "Alpha.md").write_text(
        "---\ntype: concept\ntags: [rag]\n---\n# Alpha\n\nSee [[Beta]].\n",
        encoding="utf-8",
    )
    (vault / "02-Evaluation" / "Beta.md").parent.mkdir(parents=True)
    (vault / "02-Evaluation" / "Beta.md").write_text("# Beta\n", encoding="utf-8")

    html = render_html(collect_notes(vault), title="Test Guide")

    assert "<title>Test Guide</title>" in html
    assert 'id="search"' in html
    assert 'href="#01-architecture-alpha"' in html
    assert '<article class="note" id="01-architecture-alpha"' in html
    assert '<a href="#02-evaluation-beta">Beta</a>' in html


def test_write_theory_writes_a_self_contained_file(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Alpha.md").write_text("# Alpha\n\nBody\n", encoding="utf-8")
    output = tmp_path / "theory.html"

    count = write_theory(vault, output)

    assert count == 1
    assert output.is_file()
    assert "<!doctype html>" in output.read_text(encoding="utf-8")


def test_actual_vault_has_no_missing_links_or_anchors() -> None:
    html = render_html(collect_notes(VAULT_ROOT))

    ids = set(re.findall(r'\bid="([^"]+)"', html))
    hrefs = set(re.findall(r'href="#([^"]+)"', html))

    assert '<span class="missing-link"' not in html
    assert hrefs <= ids
