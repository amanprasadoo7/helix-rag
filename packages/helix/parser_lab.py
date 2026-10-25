from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from helix.parsing import Document, parse_markdown

LAB_SCHEMA_VERSION = 1
NATIVE_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd", ".txt"}
DEFAULT_PARSERS = ("native", "docling", "unstructured")
PREVIEW_LIMIT = 8


class ParserUnavailable(RuntimeError):
    """The optional parser dependency is not installed."""


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _preview(text: str, limit: int = 240) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _native_document(path: Path, source: str) -> Document:
    suffix = path.suffix.lower()
    if suffix not in NATIVE_SUFFIXES:
        raise ValueError(
            "native parser supports Markdown/text only "
            f"(got {suffix or 'no extension'}); use docling or unstructured for this file"
        )
    return parse_markdown(
        path.read_text(encoding="utf-8"),
        source=source,
        path=path.as_posix(),
    )


def _run_native(path: Path, out: Path, source: str) -> dict[str, Any]:
    document = _native_document(path, source)
    (out / "native.json").write_text(document.to_json(), encoding="utf-8")
    blocks = list(document.blocks())
    summary = {
        "items": document.stats.blocks,
        "sections": document.stats.sections,
        "blocks": document.stats.blocks,
        "words": document.stats.words,
        "chars": document.stats.chars,
        "tables": document.stats.tables,
        "code_blocks": document.stats.code_blocks,
        "warnings": document.warnings,
    }
    preview = [{"type": block.type, "text": _preview(block.text)} for block in blocks[:8]]
    return {"output": "native.json", "summary": summary, "preview": preview}


def _run_docling(path: Path, out: Path) -> dict[str, Any]:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise ParserUnavailable("docling is not installed; run `uv sync --extra parsers`") from exc

    result = DocumentConverter().convert(str(path))
    document = result.document
    data = document.export_to_dict()
    _write_json(out / "docling.json", data)
    markdown = document.export_to_markdown()
    (out / "docling.md").write_text(markdown, encoding="utf-8")

    texts = list(getattr(document, "texts", []))
    tables = list(getattr(document, "tables", []))
    pictures = list(getattr(document, "pictures", []))
    summary = {
        "items": len(texts) + len(tables) + len(pictures),
        "texts": len(texts),
        "tables": len(tables),
        "pictures": len(pictures),
        "pages": len(getattr(document, "pages", {})),
        "words": len(markdown.split()),
        "chars": len(markdown),
    }
    preview = [
        {
            "type": str(getattr(item, "label", "text")),
            "text": _preview(getattr(item, "text", "")),
        }
        for item in texts[:PREVIEW_LIMIT]
    ]
    return {"output": "docling.json", "summary": summary, "preview": preview}


def _install_unstructured_spacy_fallback() -> str | None:
    """Use a blank spaCy pipeline when the downloaded model cannot be loaded."""
    try:
        import spacy

        spacy.load("en_core_web_sm")
        return None
    except Exception:
        import spacy
        import unstructured.nlp.tokenize as tokenize

        nlp = spacy.blank("en")
        if "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")
        setattr(tokenize, "_get_nlp", lambda: nlp)  # noqa: B010
        return (
            "en_core_web_sm could not be loaded; Unstructured used a blank English "
            "spaCy pipeline with a sentencizer. Element categories may differ slightly."
        )


def _run_unstructured(path: Path, out: Path, strategy: str) -> dict[str, Any]:
    try:
        os.environ.setdefault("UNSTRUCTURED_DISABLE_NOTICE", "1")
        from unstructured.partition.auto import partition
    except ImportError as exc:
        raise ParserUnavailable(
            "unstructured is not installed; run `uv sync --extra parsers`"
        ) from exc

    warning = _install_unstructured_spacy_fallback()
    elements = partition(filename=str(path), strategy=strategy)
    data = [element.to_dict() for element in elements]
    _write_json(out / "unstructured.json", data)

    categories = Counter(str(element.category) for element in elements)
    summary = {
        "items": len(elements),
        "categories": dict(sorted(categories.items())),
        "tables": categories.get("Table", 0),
        "words": sum(len(str(element.text).split()) for element in elements),
        "chars": sum(len(str(element.text)) for element in elements),
    }
    if warning:
        summary["warning"] = warning
    preview = [
        {"type": str(element.category), "text": _preview(element.text)}
        for element in elements[:PREVIEW_LIMIT]
    ]
    return {"output": "unstructured.json", "summary": summary, "preview": preview}


def run_parser_lab(
    file_path: str | Path,
    out_dir: str | Path,
    *,
    parsers: tuple[str, ...] = DEFAULT_PARSERS,
    source: str = "lab",
    unstructured_strategy: str = "fast",
) -> dict[str, Any]:
    """Parse one file with several parsers and write a side-by-side lab report."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")

    unknown = set(parsers) - set(DEFAULT_PARSERS)
    if unknown:
        raise ValueError(f"unknown parser(s): {', '.join(sorted(unknown))}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}

    for name in parsers:
        started = time.perf_counter()
        try:
            if name == "native":
                body = _run_native(path, out, source)
            elif name == "docling":
                body = _run_docling(path, out)
            else:
                body = _run_unstructured(path, out, unstructured_strategy)
            results[name] = {
                "status": "ok",
                "seconds": round(time.perf_counter() - started, 3),
                **body,
            }
        except ParserUnavailable as exc:
            results[name] = {
                "status": "unavailable",
                "seconds": round(time.perf_counter() - started, 3),
                "error": str(exc),
            }
        except ValueError as exc:
            results[name] = {
                "status": "unsupported",
                "seconds": round(time.perf_counter() - started, 3),
                "error": str(exc),
            }
        except Exception as exc:
            results[name] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "seconds": round(time.perf_counter() - started, 3),
                "error": str(exc),
            }

    summary = {
        "schema_version": LAB_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "file": path.as_posix(),
        "file_type": path.suffix.lower() or "none",
        "size_bytes": path.stat().st_size,
        "source": source,
        "out_dir": out.as_posix(),
        "parsers": results,
    }
    _write_json(out / "summary.json", summary)
    return summary
