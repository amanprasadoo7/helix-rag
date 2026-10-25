from __future__ import annotations

import json

import pytest

from helix.parser_lab import run_parser_lab


def test_native_lab_writes_document_and_summary(tmp_path):
    source = tmp_path / "sample.md"
    source.write_text(
        "---\ntitle: Sample Document\n---\n\n"
        "A short paragraph.\n\n"
        "| Name | Value |\n|---|---|\n| one | 1 |\n\n"
        "## Details\n\n- first\n- second\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"

    summary = run_parser_lab(source, out, parsers=("native",))

    result = summary["parsers"]["native"]
    assert result["status"] == "ok"
    assert result["output"] == "native.json"
    assert result["summary"]["sections"] == 2
    assert result["summary"]["tables"] == 1

    document = json.loads((out / "native.json").read_text(encoding="utf-8"))
    assert document["title"] == "Sample Document"
    assert document["root"]["children"][0]["title"] == "Details"
    assert (out / "summary.json").is_file()


def test_native_lab_reports_unsupported_format(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.7\n")

    summary = run_parser_lab(source, tmp_path / "out", parsers=("native",))

    result = summary["parsers"]["native"]
    assert result["status"] == "unsupported"
    assert "Markdown/text only" in result["error"]


def test_lab_rejects_unknown_parser(tmp_path):
    source = tmp_path / "sample.md"
    source.write_text("# Title\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown parser"):
        run_parser_lab(source, tmp_path / "out", parsers=("bogus",))
