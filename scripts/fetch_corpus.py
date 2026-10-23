from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Any

from helix.corpus import (
    CORPUS_ROOT,
    MANIFEST_PATH,
    SOURCES,
    CorpusSource,
    build_manifest,
    write_manifest,
)


def run_git(repo: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required but was not found on PATH")

    result = subprocess.run(  # noqa: S603
        [git, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        command = " ".join(("git", *args))
        raise RuntimeError(f"{command} failed in {repo}:\n{result.stderr.strip()}")
    return result.stdout


def ensure_checkout(source: CorpusSource, root: Path, *, force: bool) -> Path:
    target = root / source.name
    if target.exists() and (force or not target.is_dir()):
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    if target.is_dir() and not (target / ".git").exists():
        shutil.rmtree(target)

    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        run_git(target, "init", "-q")

    remotes = run_git(target, "remote").split()
    if "origin" in remotes:
        run_git(target, "remote", "set-url", "origin", source.repo)
    else:
        run_git(target, "remote", "add", "origin", source.repo)

    print(f"fetching {source.name} at {source.commit[:12]}...")
    run_git(
        target,
        "fetch",
        "--depth",
        "1",
        "--filter=blob:none",
        "origin",
        source.commit,
    )
    run_git(target, "sparse-checkout", "init", "--cone")
    run_git(target, "sparse-checkout", "set", *(spec.path for spec in source.paths))
    run_git(target, "checkout", "--force", source.commit)
    run_git(target, "clean", "-ffd")
    return target


def print_summary(manifest: dict[str, Any], manifest_path: Path) -> None:
    print()
    print(
        f"{'source':<14} {'path':<28} {'avail':>7} "
        f"{'sel':>6} {'MB':>7} {'chunks':>7}"
    )
    for source in manifest["sources"]:
        for path in source["paths"]:
            print(
                f"{source['name']:<14} {path['path']:<28} "
                f"{path['available_files']:>7} {path['selected_files']:>6} "
                f"{path['bytes'] / 1_000_000:>7.1f} "
                f"{path['estimated_child_chunks']:>7}"
            )

    totals = manifest["totals"]
    print()
    print(
        f"Total: {totals['files']} files, {totals['bytes'] / 1_000_000:.1f} MB, "
        f"{totals['words']:,} words, ~{totals['estimated_child_chunks']:,} child chunks"
    )
    print(f"Cap: {manifest['cap']} files")
    print(f"Corpus root: {manifest['corpus_root']}")
    print(f"Manifest: {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the pinned Helix corpus and write a manifest."
    )
    parser.add_argument("--root", type=Path, default=CORPUS_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument(
        "--force",
        action="store_true",
        help="delete existing checkouts and fetch them again",
    )
    args = parser.parse_args()

    root: Path = args.root
    root.mkdir(parents=True, exist_ok=True)

    for source in SOURCES:
        ensure_checkout(source, root, force=args.force)

    manifest = build_manifest(root)
    write_manifest(manifest, args.manifest)

    notice = Path("NOTICE")
    if notice.exists():
        shutil.copy2(notice, root / "NOTICE")

    print_summary(manifest, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
