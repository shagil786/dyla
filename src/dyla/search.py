"""Azure AI Search index and hybrid retrieval adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from .config import Settings
from .domain import Evidence, EvidenceChunk, SearchFilters


class SearchIndex:
    def __init__(
        self, endpoint_or_settings: str | Settings, api_key: str | None = None, index_name: str | None = None,
        *, vector_dimensions: int | None = None, transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0, batch_size: int = 100, embedder: Any | None = None,
    ) -> None:
        if isinstance(endpoint_or_settings, Settings):
            settings = endpoint_or_settings
            endpoint, api_key, index_name = settings.azure_search_endpoint, settings.azure_search_api_key, settings.azure_search_index
            vector_dimensions = vector_dimensions or settings.azure_search_vector_dimensions
        else:
            endpoint = endpoint_or_settings
        if not api_key or not index_name or not vector_dimensions or vector_dimensions < 1:
            raise ValueError("search endpoint, API key, index name, and positive vector dimensions are required")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.index_name = index_name
        self.vector_dimensions = vector_dimensions
        self.batch_size = batch_size
        self.embedder = embedder
        self.client = httpx.Client(transport=transport, timeout=timeout, headers={"api-key": api_key, "Content-Type": "application/json"})
        self.api_version = "2024-07-01"

    def _url(self, suffix: str) -> str:
        return f"{self.endpoint}{suffix}?api-version={self.api_version}"

    def ensure_index(self) -> None:
        schema = {
            "name": self.index_name,
            "fields": [
                {"name": "chunk_id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "source_id", "type": "Edm.String", "filterable": True},
                {"name": "url", "type": "Edm.String"}, {"name": "title", "type": "Edm.String", "searchable": True},
                {"name": "section", "type": "Edm.String", "searchable": True}, {"name": "text", "type": "Edm.String", "searchable": True},
                {"name": "position", "type": "Edm.Int32", "filterable": True}, {"name": "entity_ids", "type": "Collection(Edm.String)", "filterable": True},
                {"name": "published_at", "type": "Edm.DateTimeOffset", "filterable": True}, {"name": "content_hash", "type": "Edm.String", "filterable": True},
                {"name": "content_vector", "type": "Collection(Edm.Single)", "searchable": True, "dimensions": self.vector_dimensions, "vectorSearchProfile": "dyla-vector-profile"},
            ],
            "vectorSearch": {"algorithms": [{"name": "dyla-hnsw", "kind": "hnsw"}], "profiles": [{"name": "dyla-vector-profile", "algorithm": "dyla-hnsw"}]},
        }
        response = self.client.put(self._url(f"/indexes/{self.index_name}"), json=schema)
        response.raise_for_status()

    def upsert(self, chunks: list[EvidenceChunk], vectors: list[list[float]] | None = None) -> None:
        if vectors is None:
            if self.embedder is None:
                raise ValueError("vectors or an embedder must be provided")
            vectors = self.embedder.embed([chunk.text for chunk in chunks])
        assert vectors is not None
        if len(vectors) != len(chunks):
            raise ValueError("vector count did not match chunk count")
        for vector in vectors:
            if len(vector) != self.vector_dimensions:
                raise ValueError("vector dimension does not match index configuration")
        for start in range(0, len(chunks), self.batch_size):
            documents = []
            for chunk, vector in zip(chunks[start:start + self.batch_size], vectors[start:start + self.batch_size]):
                documents.append({"@search.action": "mergeOrUpload", **chunk.model_dump(), "content_vector": vector,
                                  "published_at": chunk.published_at.isoformat() if chunk.published_at else None})
            response = self.client.post(self._url(f"/indexes/{self.index_name}/docs/index"), json={"value": documents})
            response.raise_for_status()

    def hybrid_search(self, query: str, vector: list[float], filters: SearchFilters, limit: int) -> list[Evidence]:
        if len(vector) != self.vector_dimensions:
            raise ValueError("vector dimension does not match index configuration")
        if limit < 1:
            raise ValueError("limit must be positive")
        payload: dict[str, Any] = {"search_text": query, "top": limit, "vectorQueries": [{"kind": "vector", "vector": vector, "fields": "content_vector", "k": limit}]}
        clauses = []
        if filters.entity_ids:
            clauses.append(" or ".join(f"entity_ids/any(x: x eq '{_odata(value)}')" for value in filters.entity_ids))
        if filters.source_ids:
            clauses.append(" or ".join(f"source_id eq '{_odata(value)}'" for value in filters.source_ids))
        if filters.published_after:
            clauses.append(f"published_at ge {_date(filters.published_after)}")
        if filters.published_before:
            clauses.append(f"published_at le {_date(filters.published_before)}")
        if clauses:
            payload["filter"] = " and ".join(f"({clause})" for clause in clauses)
        response = self.client.post(self._url(f"/indexes/{self.index_name}/docs/search"), json=payload)
        response.raise_for_status()
        result = []
        for item in response.json().get("value", []):
            result.append(Evidence(chunk_id=item["chunk_id"], source_id=item["source_id"], url=item["url"], title=item.get("title"), text=item["text"], score=float(item.get("@search.score", item.get("score", 0.0))), entity_ids=item.get("entity_ids", [])))
        return result

    def close(self) -> None:
        self.client.close()


def _odata(value: str) -> str:
    return value.replace("'", "''")


def _date(value: datetime) -> str:
    return value.isoformat()
