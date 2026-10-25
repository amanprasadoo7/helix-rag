#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast

from helix.parser_lab import DEFAULT_PARSERS, run_parser_lab


def _parsers(value: str) -> tuple[str, ...]:
    names = tuple(part.strip() for part in value.split(",") if part.strip())
    unknown = set(names) - set(DEFAULT_PARSERS)
    if unknown:
        choices = ", ".join(DEFAULT_PARSERS)
        raise argparse.ArgumentTypeError(
            f"unknown parser(s): {', '.join(sorted(unknown))}; choose from {choices}"
        )
    return names


def _print_report(summary: dict[str, Any]) -> None:
    print(f"file: {summary['file']}")
    print(f"out:  {summary['out_dir']}")
    print()
    header = f"{'parser':<13}{'status':<12}{'items':>7}{'tables':>8}{'chars':>10}{'sec':>8}  output"
    print(header)
    print("-" * len(header))
    parsers = cast(dict[str, dict[str, Any]], summary["parsers"])
    for name, result in parsers.items():
        stats = cast(dict[str, Any], result.get("summary") or {})
        status = str(result["status"])
        items = stats.get("items", "-")
        tables = stats.get("tables", "-")
        chars = stats.get("chars", "-")
        seconds = result.get("seconds", "-")
        output = result.get("output", "-")
        print(
            f"{name:<13}{status:<12}{str(items):>7}{str(tables):>8}"
            f"{str(chars):>10}{str(seconds):>8}  {output}"
        )

    failures = {name: result for name, result in parsers.items() if result.get("status") != "ok"}
    if failures:
        print()
        for name, result in failures.items():
            print(f"{name}: {result.get('error', 'unknown error')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare the native Markdown parser, Docling, and Unstructured on one file."
    )
    parser.add_argument("file", type=Path, help="file to parse")
    parser.add_argument(
        "--out",
        type=Path,
        help="output directory (default: data/parser-lab/<file stem>)",
    )
    parser.add_argument(
        "--parsers",
        type=_parsers,
        default=DEFAULT_PARSERS,
        help=f"comma-separated subset of: {', '.join(DEFAULT_PARSERS)}",
    )
    parser.add_argument("--source", default="lab", help="source label for the native document")
    parser.add_argument(
        "--unstructured-strategy",
        default="fast",
        choices=["auto", "fast", "hi_res", "ocr_only"],
        help="Unstructured partition strategy (default: fast)",
    )
    args = parser.parse_args(argv)

    out = args.out or Path("data/parser-lab") / args.file.stem
    summary = run_parser_lab(
        args.file,
        out,
        parsers=args.parsers,
        source=args.source,
        unstructured_strategy=args.unstructured_strategy,
    )
    _print_report(summary)
    print()
    print(f"summary: {(out / 'summary.json').as_posix()}")
    results = cast(dict[str, dict[str, Any]], summary["parsers"])
    return 0 if any(result.get("status") == "ok" for result in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
