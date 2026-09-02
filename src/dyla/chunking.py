"""Deterministic, citation-preserving document chunking."""

from __future__ import annotations

import hashlib
import re

from .domain import Document, EvidenceChunk


def chunk_document(
    document: Document,
    max_chars: int = 5000,
    overlap_chars: int = 500,
    *,
    entity_ids: list[str] | None = None,
) -> list[EvidenceChunk]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between zero and max_chars")
    lines = [re.sub(r"\s+", " ", line).strip() for line in document.text.splitlines()]
    blocks: list[tuple[str | None, str]] = []
    section: str | None = None
    for line in lines:
        if not line:
            continue
        if len(line) < 160 and not line.endswith((".", "?", "!", ":")):
            section = line
            continue
        blocks.append((section, line))
    if not blocks and document.text.strip():
        blocks = [(None, document.text.strip())]

    pieces: list[tuple[str | None, str]] = []
    current_section: str | None = None
    current = ""
    for block_section, paragraph in blocks:
        if current and (len(current) + 1 + len(paragraph) > max_chars or block_section != current_section):
            pieces.append((current_section, current))
            carry = current[-overlap_chars:] if overlap_chars else ""
            current = carry
        current_section = block_section
        while len(paragraph) > max_chars:
            pieces.append((current_section, paragraph[:max_chars]))
            paragraph = paragraph[max_chars - overlap_chars:] if overlap_chars else paragraph[max_chars:]
        current = f"{current} {paragraph}".strip()
    if current:
        pieces.append((current_section, current[:max_chars]))

    entities = list(entity_ids or [])
    result = []
    for position, (piece_section, text) in enumerate(pieces):
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_id = hashlib.sha256(f"{document.source_id}:{position}:{content_hash}".encode()).hexdigest()
        result.append(EvidenceChunk(
            chunk_id=chunk_id, source_id=document.source_id, url=document.url, title=document.title,
            section=piece_section, text=text, position=position, entity_ids=entities,
            content_hash=content_hash, published_at=document.published_at,
        ))
    return result
