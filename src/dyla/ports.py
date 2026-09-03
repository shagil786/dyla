"""Provider-neutral application ports."""

from typing import Protocol, runtime_checkable

from .domain import Document, Evidence, EvidenceChunk, SearchFilters, SearchHit


@runtime_checkable
class VectorStore(Protocol):
    """Provider-neutral vector storage and retrieval contract."""

    def ensure_collection(self) -> None:
        ...

    def upsert(self, chunks: list[EvidenceChunk], vectors: list[list[float]] | None = None) -> None:
        ...

    def hybrid_search(self, query: str, vector: list[float], filters: SearchFilters, limit: int) -> list[Evidence]:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class SearchProvider(Protocol):
    """Search and page retrieval contract used by the research core."""

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        ...

    def fetch(self, url: str) -> Document:
        ...
