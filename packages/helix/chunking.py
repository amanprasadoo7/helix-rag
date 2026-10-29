"""Structure-aware chunking for the parsed corpus.

The parser gives one section tree per document. This module turns each section's
own blocks into searchable child chunks and keeps the section as a parent for
later context expansion.

Rules:

- a child never crosses a section boundary;
- prose is packed up to a target word budget and split at sentence boundaries;
- lists split on item boundaries;
- code stays whole; tables split by rows with a repeated header when oversized;
- split sections repeat the tail of the previous child as overlap;
- ids are content-addressed, so unchanged text keeps the same id;
- output is deterministic: no timestamps or random values.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field

from helix.parsing import Block, Document, Section

SCHEMA_VERSION = 1
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://helix.local/chunk")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class ChunkerConfig:
    """Word budgets. One English word is roughly 1.3 tokens for BGE-M3."""

    target_words: int = 250
    max_words: int = 400
    overlap_words: int = 30

    def __post_init__(self) -> None:
        if self.target_words <= 0:
            raise ValueError("target_words must be positive")
        if self.max_words < self.target_words:
            raise ValueError("max_words must be at least target_words")
        if not 0 <= self.overlap_words < self.target_words:
            raise ValueError("overlap_words must be below target_words")


DEFAULT_CONFIG = ChunkerConfig()


class ChildChunk(BaseModel):
    id: str
    source: str
    path: str
    commit: str = ""
    parent_id: str
    section_id: str
    section_path: list[str]
    ordinal: int
    text: str
    embedding_text: str
    content_hash: str
    words: int
    chars: int
    block_types: list[str]
    overlap_words: int = 0
    oversize: bool = False


class ParentSection(BaseModel):
    id: str
    source: str
    path: str
    level: int
    title: str
    section_path: list[str]
    text: str
    words: int
    chars: int
    has_content: bool
    own_child_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)


class ChunkStats(BaseModel):
    sections: int = 0
    parents: int = 0
    children: int = 0
    source_words: int = 0
    child_words: int = 0
    overlap_words: int = 0
    oversize_children: int = 0
    under_100_words: int = 0
    largest_child_words: int = 0
    empty_sections: int = 0
    sections_without_children: int = 0


class ChunkedDocument(BaseModel):
    schema_version: int = SCHEMA_VERSION
    source: str
    path: str
    commit: str = ""
    title: str
    parents: list[ParentSection] = Field(default_factory=list)
    children: list[ChildChunk] = Field(default_factory=list)
    stats: ChunkStats = Field(default_factory=ChunkStats)
    warnings: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return (
            json.dumps(
                self.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )


@dataclass
class _Piece:
    text: str
    block_type: str
    separator: str
    atomic: bool = False
    oversize: bool = False
    overlap: bool = False

    @property
    def words(self) -> int:
        return count_words(self.text)


def count_words(text: str) -> int:
    return len(text.split())


def _parent_id(section: Section) -> str:
    if section.level == 0:
        return "root"
    return f"section:{section.id}"


def _section_text(section: Section) -> str:
    return "\n\n".join(block.text.strip() for block in section.blocks if block.text.strip())


def _split_text(text: str, max_words: int) -> list[str]:
    """Split prose at sentence boundaries, then force-split giant sentences."""
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    parts: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        if len(words) <= max_words:
            parts.append(sentence)
            continue
        for index in range(0, len(words), max_words):
            parts.append(" ".join(words[index : index + max_words]))
    return parts or [text.strip()]


def _list_pieces(block: Block, config: ChunkerConfig) -> list[_Piece]:
    items = block.meta.get("items")
    if not isinstance(items, list) or not items:
        return _prose_pieces(block, config)

    pieces: list[_Piece] = []
    first = True
    for item in items:
        if not isinstance(item, dict):
            continue
        item_text = str(item.get("text", "")).strip()
        if not item_text:
            continue
        parts = _split_text(item_text, config.max_words)
        for index, part in enumerate(parts):
            if first:
                separator = "\n\n"
                first = False
            elif index == 0:
                separator = "\n"
            else:
                separator = " "
            pieces.append(_Piece(text=part, block_type="list", separator=separator))
    return pieces or _prose_pieces(block, config)


def _prose_pieces(block: Block, config: ChunkerConfig) -> list[_Piece]:
    parts = _split_text(block.text, config.max_words)
    pieces: list[_Piece] = []
    for index, part in enumerate(parts):
        pieces.append(
            _Piece(
                text=part,
                block_type=block.type,
                separator="\n\n" if index == 0 else " ",
            )
        )
    return pieces


def _table_pieces(block: Block, config: ChunkerConfig) -> list[_Piece]:
    """Split a large table by rows, repeating the header in every piece."""
    headers = block.meta.get("headers")
    rows = block.meta.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list) or not rows:
        return _line_pieces(block.text, "table", config.max_words)

    header = " | ".join(str(cell) for cell in headers)
    header_words = count_words(header)
    if header_words > config.max_words:
        return [
            _Piece(
                text=block.text.strip(),
                block_type="table",
                separator="\n\n",
                atomic=True,
                oversize=True,
            )
        ]

    pieces: list[_Piece] = []
    current = [header]
    current_words = header_words

    def flush() -> None:
        nonlocal current, current_words
        if len(current) > 1:
            pieces.append(
                _Piece(
                    text="\n".join(current),
                    block_type="table",
                    separator="\n\n",
                    atomic=True,
                )
            )
        current = [header]
        current_words = header_words

    for row in rows:
        if not isinstance(row, list):
            continue
        row_text = " | ".join(str(cell) for cell in row)
        row_words = count_words(row_text)
        if header_words + row_words > config.max_words:
            flush()
            pieces.append(
                _Piece(
                    text="\n".join([header, row_text]) if header else row_text,
                    block_type="table",
                    separator="\n\n",
                    atomic=True,
                    oversize=True,
                )
            )
            continue
        if len(current) > 1 and current_words + row_words > config.max_words:
            flush()
        current.append(row_text)
        current_words += row_words

    flush()
    return pieces or _line_pieces(block.text, "table", config.max_words)


def _line_pieces(text: str, block_type: str, max_words: int) -> list[_Piece]:
    """Fallback for structured text without usable metadata."""
    pieces: list[_Piece] = []
    current: list[str] = []
    current_words = 0
    for line in (item.strip() for item in text.splitlines() if item.strip()):
        words = count_words(line)
        if current and current_words + words > max_words:
            pieces.append(
                _Piece(
                    text="\n".join(current),
                    block_type=block_type,
                    separator="\n\n",
                    atomic=True,
                    oversize=current_words > max_words,
                )
            )
            current = []
            current_words = 0
        current.append(line)
        current_words += words
    if current:
        pieces.append(
            _Piece(
                text="\n".join(current),
                block_type=block_type,
                separator="\n\n",
                atomic=True,
                oversize=current_words > max_words,
            )
        )
    return pieces


def _split_block(block: Block, config: ChunkerConfig) -> list[_Piece]:
    text = block.text.strip()
    if not text:
        return []

    words = count_words(text)
    if block.type == "code":
        return [
            _Piece(
                text=text,
                block_type="code",
                separator="\n\n",
                atomic=True,
                oversize=words > config.max_words,
            )
        ]
    if block.type == "table":
        if words <= config.max_words:
            return [
                _Piece(
                    text=text,
                    block_type="table",
                    separator="\n\n",
                    atomic=True,
                )
            ]
        return _table_pieces(block, config)
    if words <= config.max_words:
        return [_Piece(text=text, block_type=block.type, separator="\n\n")]
    if block.type == "list":
        return _list_pieces(block, config)
    return _prose_pieces(block, config)


def _join_pieces(pieces: list[_Piece]) -> str:
    if not pieces:
        return ""
    parts = [pieces[0].text]
    for piece in pieces[1:]:
        parts.append(piece.separator)
        parts.append(piece.text)
    return "".join(parts).strip()


def _overlap_piece(pieces: list[_Piece], budget: int) -> _Piece | None:
    if budget <= 0 or not pieces:
        return None
    tail = pieces[-1]
    if tail.atomic:
        return None

    if tail.block_type == "list":
        units = [line.strip() for line in tail.text.splitlines() if line.strip()]
        separator = "\n"
    else:
        units = [part.strip() for part in _SENTENCE_SPLIT.split(tail.text) if part.strip()]
        separator = " "

    selected: list[str] = []
    total = 0
    for unit in reversed(units):
        words = count_words(unit)
        if total + words > budget:
            break
        selected.insert(0, unit)
        total += words
    if not selected:
        return None
    return _Piece(
        text=separator.join(selected),
        block_type=tail.block_type,
        separator="\n\n",
        overlap=True,
    )


def _child_id(
    source: str,
    path: str,
    parent_id: str,
    content_hash: str,
    occurrence: int,
) -> str:
    key = f"helix:{source}:{path}:{parent_id}:{content_hash}:{occurrence}"
    return str(uuid.uuid5(_ID_NAMESPACE, key))


def _build_child(
    *,
    document: Document,
    section: Section,
    pieces: list[_Piece],
    ordinal: int,
    config: ChunkerConfig,
    occurrences: dict[str, int],
) -> ChildChunk:
    text = _join_pieces(pieces)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    occurrence = occurrences.get(content_hash, 0)
    occurrences[content_hash] = occurrence + 1
    parent_id = _parent_id(section)
    section_path = list(section.breadcrumb)
    embedding_text = f"{' > '.join(section_path)}\n\n{text}"
    words = count_words(text)
    block_types = sorted({piece.block_type for piece in pieces})
    return ChildChunk(
        id=_child_id(
            document.source,
            document.path,
            parent_id,
            content_hash,
            occurrence,
        ),
        source=document.source,
        path=document.path,
        commit=document.commit,
        parent_id=parent_id,
        section_id=section.id,
        section_path=section_path,
        ordinal=ordinal,
        text=text,
        embedding_text=embedding_text,
        content_hash=content_hash,
        words=words,
        chars=len(text),
        block_types=block_types,
        overlap_words=sum(piece.words for piece in pieces if piece.overlap),
        oversize=any(piece.oversize for piece in pieces) or words > config.max_words,
    )


def _pack_section(
    document: Document,
    section: Section,
    start_ordinal: int,
    config: ChunkerConfig,
) -> tuple[list[ChildChunk], int]:
    pieces: list[_Piece] = []
    for block in section.blocks:
        pieces.extend(_split_block(block, config))

    children: list[ChildChunk] = []
    occurrences: dict[str, int] = {}
    current: list[_Piece] = []
    current_words = 0
    ordinal = start_ordinal
    overlap: _Piece | None = None
    min_words = max(1, config.target_words // 2)

    def flush() -> None:
        nonlocal ordinal
        if not current:
            return
        children.append(
            _build_child(
                document=document,
                section=section,
                pieces=current,
                ordinal=ordinal,
                config=config,
                occurrences=occurrences,
            )
        )
        ordinal += 1

    for piece in pieces:
        words = piece.words
        if current and (
            (
                current_words + words > config.target_words
                and current_words >= min_words
            )
            or current_words + words > config.max_words
        ):
            flush()
            overlap = _overlap_piece(current, config.overlap_words)
            current = [overlap] if overlap is not None else []
            current_words = sum(item.words for item in current)

        if (
            current
            and len(current) == 1
            and current[0].overlap
            and current_words + words > config.max_words
        ):
            current = []
            current_words = 0

        current.append(piece)
        current_words += words

    flush()
    return children, ordinal


def chunk_document(
    document: Document,
    *,
    config: ChunkerConfig = DEFAULT_CONFIG,
) -> ChunkedDocument:
    """Chunk one parsed document into parents and children."""
    children_by_parent: dict[str, list[ChildChunk]] = {}
    all_children: list[ChildChunk] = []
    ordinal = 0

    sections = list(document.walk())
    for section in sections:
        parent_id = _parent_id(section)
        section_children, ordinal = _pack_section(document, section, ordinal, config)
        children_by_parent[parent_id] = section_children
        all_children.extend(section_children)

    parents: list[ParentSection] = []

    def visit(section: Section) -> list[str]:
        parent_id = _parent_id(section)
        own = children_by_parent.get(parent_id, [])
        text = _section_text(section)
        parent = ParentSection(
            id=parent_id,
            source=document.source,
            path=document.path,
            level=section.level,
            title=section.title,
            section_path=list(section.breadcrumb),
            text=text,
            words=count_words(text),
            chars=len(text),
            has_content=bool(text),
            own_child_ids=[child.id for child in own],
        )
        parents.append(parent)
        descendant_ids = [child.id for child in own]
        for child_section in section.children:
            descendant_ids.extend(visit(child_section))
        parent.child_ids = descendant_ids
        return descendant_ids

    visit(document.root)

    child_words = sum(child.words for child in all_children)
    source_words = sum(
        count_words(block.text)
        for section in sections
        for block in section.blocks
        if block.text.strip()
    )
    empty_sections = sum(1 for section in sections if not _section_text(section))
    stats = ChunkStats(
        sections=len(sections),
        parents=len(parents),
        children=len(all_children),
        source_words=source_words,
        child_words=child_words,
        overlap_words=sum(child.overlap_words for child in all_children),
        oversize_children=sum(1 for child in all_children if child.oversize),
        under_100_words=sum(1 for child in all_children if child.words < 100),
        largest_child_words=max((child.words for child in all_children), default=0),
        empty_sections=empty_sections,
        sections_without_children=sum(1 for parent in parents if not parent.child_ids),
    )

    warnings = list(document.warnings)
    if not all_children:
        warnings.append("document produced no chunks")

    return ChunkedDocument(
        source=document.source,
        path=document.path,
        commit=document.commit,
        title=document.title,
        parents=parents,
        children=all_children,
        stats=stats,
        warnings=warnings,
    )
