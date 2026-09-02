"""Provider-neutral application ports."""

from typing import Protocol, runtime_checkable

from .domain import Document, SearchHit


@runtime_checkable
class SearchProvider(Protocol):
    """Search and page retrieval contract used by the research core."""

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        ...

    def fetch(self, url: str) -> Document:
        ...
