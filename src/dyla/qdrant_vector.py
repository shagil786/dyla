"""Provider-neutral Qdrant Cloud vector-store adapter."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models

from .config import Settings
from .domain import Evidence, EvidenceChunk, SearchFilters


_QDRANT_POINT_NAMESPACE = UUID("b4f0d8f6-0d71-4ad0-bf3a-8dbf7e6f2b0e")


def qdrant_point_id(chunk_id: str) -> str:
    """Return the stable UUID used as Qdrant's point ID for a chunk."""
    return str(uuid5(_QDRANT_POINT_NAMESPACE, chunk_id))


class QdrantVectorStore:
    """Store and retrieve evidence chunks in a Qdrant collection."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: QdrantClient | Any | None = None,
        embedder: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not settings.qdrant_url:
            raise ValueError("QDRANT_URL is required when DYLA_VECTOR_STORE=qdrant")
        if not settings.qdrant_api_key:
            raise ValueError("QDRANT_API_KEY is required when DYLA_VECTOR_STORE=qdrant")
        if not settings.qdrant_collection:
            raise ValueError("QDRANT_COLLECTION is required when DYLA_VECTOR_STORE=qdrant")
        if settings.qdrant_vector_dimensions < 1:
            raise ValueError("QDRANT_VECTOR_DIMENSIONS must be positive")
        self.url = settings.qdrant_url.rstrip("/")
        self.api_key = settings.qdrant_api_key
        self.collection_name = settings.qdrant_collection
        self.vector_dimensions = settings.qdrant_vector_dimensions
        self.upsert_batch_size = settings.qdrant_upsert_batch_size
        self.upsert_batch_bytes = settings.qdrant_upsert_batch_bytes
        self.embedder = embedder
        self.client = client or QdrantClient(url=self.url, api_key=self.api_key, timeout=timeout)
        self.ensure_collection()

    def ensure_collection(self) -> None:
        try:
            info = self.client.get_collection(collection_name=self.collection_name)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise self._safe_error("checking Qdrant collection", exc) from exc
            try:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(size=self.vector_dimensions, distance=models.Distance.COSINE),
                )
            except Exception as exc:
                raise self._safe_error("creating Qdrant collection", exc) from exc
            self._create_published_at_index()
            return
        if "published_at" not in (getattr(info, "payload_schema", None) or {}):
            self._create_published_at_index()

    def _create_published_at_index(self) -> None:
        try:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="published_at",
                field_schema=models.PayloadSchemaType.DATETIME,
            )
        except Exception as exc:
            raise self._safe_error("creating Qdrant payload index", exc) from exc

    def upsert(self, chunks: list[EvidenceChunk], vectors: list[list[float]] | None = None) -> None:
        if vectors is None:
            if self.embedder is None:
                raise ValueError("vectors or an embedder must be provided")
            vectors = self.embedder.embed([chunk.text for chunk in chunks])
        assert vectors is not None
        if len(vectors) != len(chunks):
            raise ValueError("vector count did not match chunk count")
        points = []
        for chunk, vector in zip(chunks, vectors):
            if len(vector) != self.vector_dimensions:
                raise ValueError("vector dimension does not match index configuration")
            payload = chunk.model_dump()
            payload["published_at"] = _serialize_date(chunk.published_at)
            points.append(models.PointStruct(id=qdrant_point_id(chunk.chunk_id), vector=vector, payload=payload))
        if not points:
            self._upsert_points(points)
            return
        batch: list[models.PointStruct] = []
        batch_bytes = 0
        for point in points:
            point_bytes = _estimate_point_bytes(point)
            if batch and (len(batch) >= self.upsert_batch_size or batch_bytes + point_bytes > self.upsert_batch_bytes):
                self._upsert_points(batch)
                batch = []
                batch_bytes = 0
            batch.append(point)
            batch_bytes += point_bytes
        self._upsert_points(batch)

    def _upsert_points(self, points: list[models.PointStruct]) -> None:
        try:
            self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        except Exception as exc:
            raise self._safe_error("upserting Qdrant points", exc) from exc

    def hybrid_search(self, query: str, vector: list[float], filters: SearchFilters, limit: int) -> list[Evidence]:
        if len(vector) != self.vector_dimensions:
            raise ValueError("vector dimension does not match index configuration")
        if limit < 1:
            raise ValueError("limit must be positive")
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=_build_filter(filters),
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            raise self._safe_error("querying Qdrant points", exc) from exc
        return [_to_evidence(point) for point in response.points]

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            close()

    def _safe_error(self, operation: str, exc: Exception) -> RuntimeError:
        detail = str(exc).replace(self.api_key, "[REDACTED]")
        return RuntimeError(f"{operation} failed: {detail}")


def _estimate_point_bytes(point: models.PointStruct) -> int:
    serialized = json.dumps(
        {"id": point.id, "vector": point.vector, "payload": point.payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(serialized.encode("utf-8"))


def _serialize_date(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _build_filter(filters: SearchFilters) -> models.Filter | None:
    must: list[models.FieldCondition] = []
    if filters.entity_ids:
        must.append(models.FieldCondition(key="entity_ids", match=models.MatchAny(any=filters.entity_ids)))
    if filters.source_ids:
        must.append(models.FieldCondition(key="source_id", match=models.MatchAny(any=filters.source_ids)))
    if filters.published_after:
        must.append(models.FieldCondition(key="published_at", range=models.DatetimeRange(gte=filters.published_after)))
    if filters.published_before:
        must.append(models.FieldCondition(key="published_at", range=models.DatetimeRange(lte=filters.published_before)))
    return models.Filter(must=must) if must else None


def _to_evidence(point: Any) -> Evidence:
    payload = point.payload or {}
    return Evidence(
        chunk_id=payload.get("chunk_id", str(point.id)),
        source_id=payload["source_id"], url=payload["url"], title=payload.get("title"),
        text=payload["text"], score=float(point.score), entity_ids=payload.get("entity_ids", []),
    )
