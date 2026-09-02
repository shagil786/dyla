"""Dependency-free local vector-store adapter."""
from __future__ import annotations
import math
from .domain import Evidence, EvidenceChunk, SearchFilters

class LocalVectorStore:
    def __init__(self, *, vector_dimensions=None, embedder=None):
        self.vector_dimensions = vector_dimensions
        self.embedder = embedder
        self._items = {}

    def upsert(self, chunks, vectors=None):
        vectors = vectors if vectors is not None else self.embedder.embed([item.text for item in chunks])
        if len(chunks) != len(vectors):
            raise ValueError("vector count did not match chunk count")
        for chunk, vector in zip(chunks, vectors):
            if self.vector_dimensions is None:
                self.vector_dimensions = len(vector)
            if len(vector) != self.vector_dimensions:
                raise ValueError("vector dimension does not match index configuration")
            self._items[chunk.chunk_id] = (chunk, vector)

    def hybrid_search(self, query: str, vector, filters: SearchFilters, limit: int):
        if limit < 1:
            raise ValueError("limit must be positive")
        candidates = []
        for chunk, stored in self._items.values():
            if filters.entity_ids and not set(filters.entity_ids) & set(chunk.entity_ids):
                continue
            if filters.source_ids and chunk.source_id not in filters.source_ids:
                continue
            if filters.published_after and (chunk.published_at is None or chunk.published_at < filters.published_after):
                continue
            if filters.published_before and (chunk.published_at is None or chunk.published_at > filters.published_before):
                continue
            dot = sum(a * b for a, b in zip(vector, stored))
            norm = math.sqrt(sum(x * x for x in vector) * sum(x * x for x in stored))
            score = dot / norm if norm else (1.0 if query.casefold() in chunk.text.casefold() else 0.0)
            candidates.append(Evidence(chunk_id=chunk.chunk_id, source_id=chunk.source_id, url=chunk.url, title=chunk.title, text=chunk.text, score=score, entity_ids=chunk.entity_ids))
        return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]

    def ensure_index(self):
        return None

    def close(self):
        return None
