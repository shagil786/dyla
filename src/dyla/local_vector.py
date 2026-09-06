"""Dependency-free local vector-store adapter."""
from __future__ import annotations
import math
import re
from .domain import Evidence, EvidenceChunk, SearchFilters
from .policies import DEFAULT_POLICIES

# The dense cosine score is blended with a lexical token-overlap score at a
# fixed weight. Dense similarity stays dominant; the lexical channel breaks
# ties and carries retrieval when the embedding is uninformative — which, for
# the default offline hash embedder, is always. Pure dense scoring mislabels
# itself as "hybrid" while having no keyword channel at all. The weight is
# owned by Policies (ADR-0001); this alias keeps the module-local name.
_LEXICAL_WEIGHT = DEFAULT_POLICIES.lexical_weight

_TOKEN = re.compile(r"[\w']+")


def _lexical_score(query: str, text: str) -> float:
    """Share of the query's content tokens that appear in the chunk text."""
    query_tokens = {token for token in _TOKEN.findall(query.casefold()) if len(token) >= 2}
    if not query_tokens:
        return 0.0
    text_tokens = set(_TOKEN.findall(text.casefold()))
    return len(query_tokens & text_tokens) / len(query_tokens)


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
            existing = self._items.get(chunk.chunk_id)
            if existing is not None:
                # chunk_id is sha256(source_id:position:content_hash) and carries
                # no entity information, so the same page ingested while
                # researching a second entity would otherwise overwrite the
                # first entity's attribution and silently un-tag it. Entity
                # attribution accumulates; it is never replaced.
                merged = list(dict.fromkeys([*existing[0].entity_ids, *chunk.entity_ids]))
                if merged != list(chunk.entity_ids):
                    chunk = chunk.model_copy(update={"entity_ids": merged})
            self._items[chunk.chunk_id] = (chunk, vector)

    def hybrid_search(self, query: str, vector, filters: SearchFilters, limit: int):
        if limit < 1:
            raise ValueError("limit must be positive")
        if self.vector_dimensions is not None and len(vector) != self.vector_dimensions:
            # upsert validates every stored vector against the configured
            # dimensions; search must too. zip would silently truncate to the
            # shorter side and return a plausible-looking garbage score.
            raise ValueError("vector dimension does not match index configuration")
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
            lexical = _lexical_score(query, chunk.text)
            dot = sum(a * b for a, b in zip(vector, stored))
            norm = math.sqrt(sum(x * x for x in vector) * sum(x * x for x in stored))
            if norm:
                score = (1 - _LEXICAL_WEIGHT) * (dot / norm) + _LEXICAL_WEIGHT * lexical
            else:
                # With no usable vector the lexical score is the only signal.
                score = lexical
            candidates.append(Evidence(chunk_id=chunk.chunk_id, source_id=chunk.source_id, url=chunk.url, title=chunk.title, text=chunk.text, score=score, entity_ids=chunk.entity_ids))
        return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]

    def ensure_index(self):
        return None

    def close(self):
        return None
