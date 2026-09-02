"""Embedding ingestion orchestration."""

from typing import Protocol

from .chunking import chunk_document
from .domain import Document, EvidenceChunk


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChunkSink(Protocol):
    def upsert(self, chunks: list[EvidenceChunk], vectors: list[list[float]]) -> None: ...


def ingest_document(
    document: Document, embedder: Embedder, sink: ChunkSink, *, entity_ids: list[str] | None = None,
    max_chars: int = 5000, overlap_chars: int = 500,
) -> list[EvidenceChunk]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    effective_overlap = min(overlap_chars, max_chars - 1)
    chunks = chunk_document(document, max_chars, effective_overlap, entity_ids=entity_ids)
    vectors = embedder.embed([chunk.text for chunk in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("embedding count did not match chunk count")
    sink.upsert(chunks, vectors)
    return chunks
