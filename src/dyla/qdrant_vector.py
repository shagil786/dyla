"""Provider-neutral Qdrant Cloud vector-store adapter."""

from __future__ import annotations

import hashlib
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
        self._assert_dimensions_match(info)
        if "published_at" not in (getattr(info, "payload_schema", None) or {}):
            self._create_published_at_index()

    def _assert_dimensions_match(self, info: Any) -> None:
        """Refuse to reuse a collection built for a different embedding model.

        ``create_collection`` sizes the collection from
        ``QDRANT_VECTOR_DIMENSIONS``, but that only runs on the 404 path. When
        the collection already exists its configured size was never checked
        against the current setting, so switching embedding models against a
        live Qdrant Cloud collection was accepted silently at startup.

        The failure that follows is not a clean one. Writes raise "vector
        dimension does not match index configuration" from ``upsert``, which
        reads as a bug in this code rather than a configuration mismatch. Worse
        is the case where dimensions *happen* to agree: two different embedding
        models produce vectors of the same width in incomparable spaces, so
        cosine similarity against the older vectors is meaningless and memory
        reuse serves confidently-scored nonsense. Nothing downstream can detect
        that, because a number comes back and it looks like a distance.

        Checked once at startup where it is cheap and the message can name both
        numbers. A dimension the client does not report is left alone rather
        than guessed at.
        """
        self._assert_embedder_matches(info)
        configured = self.vector_dimensions
        vectors = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
        if vectors is None:
            return
        # Qdrant reports either a single unnamed vector config or a mapping of
        # named ones; only the unnamed form is used here.
        existing = getattr(vectors, "size", None)
        if not isinstance(existing, int) or existing == configured:
            return
        raise ValueError(
            f"Qdrant collection {self.collection_name!r} stores "
            f"{existing}-dimensional vectors but QDRANT_VECTOR_DIMENSIONS is "
            f"{configured}. This usually means the embedding model changed "
            f"(DYLA_EMBEDDING_MODEL) without the collection being migrated. "
            f"Point QDRANT_COLLECTION at a new collection, or delete and "
            f"re-ingest this one; vectors from different embedding models are "
            f"not comparable even when their dimensions agree."
        )

    def _create_published_at_index(self) -> None:
        try:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="published_at",
                field_schema=models.PayloadSchemaType.DATETIME,
            )
        except Exception as exc:
            raise self._safe_error("creating Qdrant payload index", exc) from exc

    def _embedder_fingerprint(self) -> str | None:
        """Identity of the embedding model, when the embedder reports one.

        Dimension equality is necessary but not sufficient: two models can both
        emit 1536-dimensional vectors into completely different spaces, and
        cosine similarity across them returns a plausible number with no
        meaning. ``CompatibleEmbeddingProvider`` already namespaces its own
        *cache* on endpoint+model for exactly this reason; the vector store had
        no equivalent, so the same swap that invalidates the cache silently
        poisoned the index instead.
        """
        model = getattr(self.embedder, "model", None)
        if not model:
            return None
        client = getattr(self.embedder, "_client", None)
        endpoint = getattr(client, "base_url", "") or ""
        return hashlib.sha256(
            json.dumps({"endpoint": endpoint, "model": model}, sort_keys=True).encode()
        ).hexdigest()

    def _assert_embedder_matches(self, info: Any) -> None:
        """Compare the collection's recorded embedder against the current one.

        The fingerprint is stored on first write (``_stamp_embedder``) rather
        than at creation, so pre-existing collections carry no stamp and are
        left alone: refusing to start against every collection built before
        this check existed would be a worse failure than the one it prevents.
        Once stamped, a mismatch is fatal.
        """
        current = self._embedder_fingerprint()
        if current is None:
            return
        recorded = self._recorded_embedder(info)
        if recorded is None or recorded == current:
            return
        raise ValueError(
            f"Qdrant collection {self.collection_name!r} was built with a "
            f"different embedding model (recorded fingerprint {recorded[:12]}, "
            f"current {current[:12]}). Vectors from different embedding models "
            f"are not comparable even at identical dimensions, so similarity "
            f"search would return confident nonsense. Point QDRANT_COLLECTION "
            f"at a new collection, or delete and re-ingest this one."
        )

    def _recorded_embedder(self, _info: Any) -> str | None:
        """Read the fingerprint from the sentinel point, if one was written.

        Qdrant has no collection-level metadata field, so the stamp lives in a
        reserved point whose ID is derived from the collection name. It is
        excluded from search by ``_SENTINEL_FILTER``.
        """
        try:
            found = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[self._sentinel_id()],
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            # A metadata read must never be the thing that takes the run down.
            return None
        for point in found or []:
            recorded = (getattr(point, "payload", None) or {}).get("embedder_fingerprint")
            if recorded:
                return str(recorded)
        return None

    def _sentinel_id(self) -> str:
        return str(uuid5(_QDRANT_POINT_NAMESPACE, f"__dyla_meta__:{self.collection_name}"))

    def _stamp_embedder(self) -> None:
        """Record the current embedder on first write, if not already recorded."""
        fingerprint = self._embedder_fingerprint()
        if fingerprint is None or self._recorded_embedder(None) is not None:
            return
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(
                    id=self._sentinel_id(),
                    vector=[0.0] * self.vector_dimensions,
                    payload={"embedder_fingerprint": fingerprint, "dyla_meta": True},
                )],
            )
        except Exception:
            return

    def upsert(self, chunks: list[EvidenceChunk], vectors: list[list[float]] | None = None) -> None:
        if vectors is None:
            if self.embedder is None:
                raise ValueError("vectors or an embedder must be provided")
            vectors = self.embedder.embed([chunk.text for chunk in chunks])
        assert vectors is not None
        if len(vectors) != len(chunks):
            raise ValueError("vector count did not match chunk count")
        # Entity attribution has to survive re-ingestion.
        #
        # chunk_id is sha256(source_id:position:content_hash) -- a pure content
        # hash carrying no entity information -- and Qdrant's upsert replaces a
        # point's payload wholesale. So re-fetching a page while researching a
        # *different* entity used to overwrite entity_ids with whatever the
        # current question happened to name, silently erasing the attribution
        # that made the page reusable. No error, no failing test: memory reuse
        # just quietly stopped engaging for that entity.
        #
        # The same bug was fixed in LocalVectorStore by merging on write. Here
        # the merge needs a read first, because the authority lives server-side.
        existing = self._existing_entity_ids([qdrant_point_id(chunk.chunk_id) for chunk in chunks])
        points = []
        for chunk, vector in zip(chunks, vectors):
            if len(vector) != self.vector_dimensions:
                raise ValueError("vector dimension does not match index configuration")
            payload = chunk.model_dump()
            payload["published_at"] = _serialize_date(chunk.published_at)
            point_id = qdrant_point_id(chunk.chunk_id)
            prior = existing.get(point_id)
            if prior:
                payload["entity_ids"] = list(
                    dict.fromkeys([*prior, *(payload.get("entity_ids") or [])])
                )
            points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))
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

    def _existing_entity_ids(self, point_ids: list[str]) -> dict[str, list[str]]:
        """Read the entity_ids already stored for these points, if any.

        Failure here is deliberately non-fatal. A read-before-write that raises
        would turn a transient Qdrant blip into a failed ingestion, which is a
        worse outcome than the attribution loss it prevents: the page can be
        re-tagged on a later run, but a dropped ingestion loses the evidence
        entirely. A degraded merge is logged by its absence, not by an
        exception.
        """
        if not point_ids:
            return {}
        retrieve = getattr(self.client, "retrieve", None)
        if retrieve is None:
            return {}
        try:
            records = retrieve(
                collection_name=self.collection_name,
                ids=point_ids,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            return {}
        found: dict[str, list[str]] = {}
        for record in records or []:
            payload = getattr(record, "payload", None) or {}
            entity_ids = payload.get("entity_ids") or []
            if isinstance(entity_ids, (list, tuple)):
                found[str(getattr(record, "id", ""))] = [str(value) for value in entity_ids]
        return found

    def _upsert_points(self, points: list[models.PointStruct]) -> None:
        self._stamp_embedder()
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
        # The metadata sentinel is a real point in the collection, so it can be
        # returned by a query like any other. It carries no evidence payload and
        # must never surface as a result.
        return [
            _to_evidence(point) for point in response.points
            if not (getattr(point, "payload", None) or {}).get("dyla_meta")
        ]

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
    must: list[models.FieldCondition | models.Filter] = []
    if filters.entity_ids:
        must.append(models.FieldCondition(key="entity_ids", match=models.MatchAny(any=filters.entity_ids)))
    if filters.source_ids:
        must.append(models.FieldCondition(key="source_id", match=models.MatchAny(any=filters.source_ids)))
    if filters.published_after or filters.published_before:
        # Undated sources are "not provably outside the range": admit records whose
        # published_at is null alongside records inside the requested date range.
        date_conditions: list[models.FieldCondition | models.IsNullCondition] = []
        if filters.published_after:
            date_conditions.append(models.FieldCondition(key="published_at", range=models.DatetimeRange(gte=filters.published_after)))
        if filters.published_before:
            date_conditions.append(models.FieldCondition(key="published_at", range=models.DatetimeRange(lte=filters.published_before)))
        null_condition = models.IsNullCondition(is_null=models.PayloadField(key="published_at"))
        must.append(models.Filter(
            should=[*date_conditions, null_condition],
            min_should=models.MinShould(conditions=[*date_conditions, null_condition], min_count=1),
        ))
    return models.Filter(must=must) if must else None


def _to_evidence(point: Any) -> Evidence:
    payload = point.payload or {}
    return Evidence(
        chunk_id=payload.get("chunk_id", str(point.id)),
        source_id=payload["source_id"], url=payload["url"], title=payload.get("title"),
        text=payload["text"], score=float(point.score), entity_ids=payload.get("entity_ids", []),
    )
