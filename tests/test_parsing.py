from __future__ import annotations

import json
from pathlib import Path

from helix.parsing import parse_file, parse_markdown


def parse(text: str, path: str = "guide.md") -> dict:
    return parse_markdown(text, source="handbook", path=path, commit="abc123").model_dump()


def test_frontmatter_is_metadata_and_not_content() -> None:
    document = parse(
        """---
title: Collect
stage: Growth
date: 2024-01-02
tags: [billing, finance]
---

Body text.
"""
    )

    assert document["title"] == "Collect"
    assert document["frontmatter"] == {
        "title": "Collect",
        "stage": "Growth",
        "date": "2024-01-02",
        "tags": ["billing", "finance"],
    }
    assert document["root"]["blocks"][0]["text"] == "Body text."
    json.dumps(document)


def test_title_falls_back_to_first_h1_then_path() -> None:
    with_h1 = parse("# Command palette\n\nBody.\n")
    assert with_h1["title"] == "Command palette"

    no_h1 = parse("Body only.\n", path="doc/user/group/_index.md")
    assert no_h1["title"] == "Group"


def test_heading_tree_breadcrumbs_and_duplicate_slugs() -> None:
    document = parse(
        """# Guide

Intro.

## Install

### Linux

## Usage

## Install
"""
    )

    root = document["root"]
    assert root["title"] == "Guide"
    assert root["blocks"][0]["text"] == "Intro."

    install, usage, duplicate = root["children"]
    assert (install["id"], install["level"], install["title"]) == ("install", 2, "Install")
    assert install["breadcrumb"] == ["Guide", "Install"]
    assert install["children"][0]["id"] == "linux"
    assert install["children"][0]["breadcrumb"] == ["Guide", "Install", "Linux"]
    assert usage["id"] == "usage"
    assert duplicate["id"] == "install-1"
    assert duplicate["breadcrumb"] == ["Guide", "Install"]


def test_heading_closing_hashes_do_not_eat_a_trailing_hash_in_the_title() -> None:
    document = parse("## C#\n\n## Usage ###\n")

    assert [section["title"] for section in document["root"]["children"]] == [
        "C#",
        "Usage",
    ]


def test_code_fences_keep_markdown_and_report_unclosed_fence() -> None:
    document = parse("```python\n# not a heading\nprint('x')\n```\n\nAfter.\n")
    code = document["root"]["blocks"][0]

    assert code["type"] == "code"
    assert code["meta"] == {"language": "python"}
    assert code["text"] == "# not a heading\nprint('x')"
    assert document["stats"]["code_blocks"] == 1

    unclosed = parse("```\nno end\n")
    assert unclosed["warnings"] == ["code fence at line 1: missing closing fence"]
    assert unclosed["root"]["blocks"][0]["text"] == "no end"


def test_fenced_code_inside_a_list_stays_code() -> None:
    document = parse(
        """1. Configure:

   ```yaml
   key: value
   ```

2. Save.
"""
    )

    blocks = document["root"]["blocks"]
    assert [block["type"] for block in blocks] == ["list", "code", "list"]
    assert blocks[1]["text"] == "key: value"
    assert blocks[1]["meta"] == {"language": "yaml"}
    assert document["warnings"] == []


def test_shortcodes_are_removed_but_wrapped_content_is_kept() -> None:
    document = parse(
        """{{< details >}}
- Tier: Free
{{< /details >}}

{{< history >}}
{{< yes >}} Supported
{{< /history >}}

{{< tab title="GitLab.com" >}}
Tab body.
{{< /tab >}}
"""
    )

    texts = [block["text"] for block in document["root"]["blocks"]]
    assert "Tier: Free" in texts
    assert "Yes Supported" in texts
    assert any("GitLab.com" in text and "Tab body." in text for text in texts)
    assert all("{{<" not in text for text in texts)
    assert document["stats"]["shortcodes_removed"] == 7


def test_tables_lists_quotes_and_callouts() -> None:
    document = parse(
        """| Name | Value |
| --- | --- |
| a | b \\| c |
| supported | {{< yes >}} |
| tab | {{< tab title="A | B" >}} |

1. one
2. two
   - nested
   - nested two
3. three

> [!warning] Be careful
> Quoted text.
"""
    )

    table = document["root"]["blocks"][0]
    assert table["type"] == "table"
    assert table["meta"] == {
        "headers": ["Name", "Value"],
        "rows": [["a", "b | c"], ["supported", "Yes"], ["tab", "A | B"]],
    }

    items = document["root"]["blocks"][1]
    assert items["type"] == "list"
    assert items["meta"]["ordered"] is True
    assert items["meta"]["items"] == [
        {"text": "one", "level": 0},
        {"text": "two", "level": 0},
        {"text": "nested", "level": 1},
        {"text": "nested two", "level": 1},
        {"text": "three", "level": 0},
    ]

    callout = document["root"]["blocks"][2]
    assert callout["type"] == "callout"
    assert callout["meta"] == {"callout": "warning"}
    assert callout["text"] == "Warning Be careful Quoted text."


def test_inline_markup_and_html_become_plain_text() -> None:
    document = parse(
        "See [docs](https://example.com), ![logo](logo.png), `foo_bar`, "
        "**bold**, <kbd>Ctrl</kbd> &amp; <div>block</div>.\n"
    )
    text = document["root"]["blocks"][0]["text"]

    assert text == "See docs, logo, foo_bar, bold, Ctrl & block."


def test_html_block_is_marked_and_flattened() -> None:
    document = parse(
        """<details>
<summary>More</summary>
Some <strong>text</strong>.
</details>
"""
    )
    block = document["root"]["blocks"][0]

    assert block["type"] == "html"
    assert block["text"] == "More Some text."


def test_parse_is_deterministic_and_handles_crlf() -> None:
    text = "---\ntitle: T\n---\n\n## A\n\nBody.\n"
    first = parse(text.replace("\n", "\r\n"))
    second = parse(text)

    assert first == second
    assert parse_markdown(text, source="handbook", path="guide.md").to_json() == (
        parse_markdown(text, source="handbook", path="guide.md").to_json()
    )


def test_empty_document_and_bad_frontmatter_are_warnings() -> None:
    empty = parse("")
    assert empty["stats"]["blocks"] == 0
    assert empty["warnings"] == ["document has no content blocks"]

    broken = parse("---\ntitle: never closed\nBody.\n")
    assert "frontmatter: missing closing delimiter" in broken["warnings"]


def test_parse_file_reads_utf8_and_uses_relative_path(tmp_path: Path) -> None:
    file_path = tmp_path / "note.md"
    file_path.write_text("---\ntitle: Café\n---\n\nBody.\n", encoding="utf-8")

    document = parse_file(
        file_path.as_posix(),
        source="handbook",
        path="content/handbook/note.md",
        commit="abc123",
    )

    assert document.title == "Café"
    assert document.path == "content/handbook/note.md"
    assert document.commit == "abc123"
