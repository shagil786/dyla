from datetime import UTC, datetime
from uuid import UUID

import pytest

from dyla.config import Settings
from dyla.domain import EvidenceChunk, SearchFilters
from dyla.provider_factory import build_vector_store
from dyla.qdrant_vector import QdrantVectorStore, qdrant_point_id


class NotFoundError(Exception):
    status_code = 404


class FakeClient:
    def __init__(self, *, collection_exists=False):
        self.collection_exists = collection_exists
        self.created = []
        self.upserts = []
        self.queries = []

    def get_collection(self, collection_name):
        if not self.collection_exists:
            raise NotFoundError("missing collection")
        return object()

    def create_collection(self, **kwargs):
        self.created.append(kwargs)
        self.collection_exists = True
        return True

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        return True

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return type("Result", (), {"points": [
            type("Point", (), {"id": qdrant_point_id("chunk-1"), "score": 0.91, "payload": {
                "chunk_id": "chunk-1", "source_id": "source-1", "url": "https://example.com",
                "title": "Title", "text": "evidence", "entity_ids": ["entity-1"],
            }})(),
        ]})()


def settings(**updates):
    values = dict(
        dyla_vector_store="qdrant",
        qdrant_url="https://qdrant.example",
        qdrant_api_key="fake-qdrant-key",
        qdrant_collection="evidence",
        qdrant_vector_dimensions=3,
    )
    values.update(updates)
    return Settings(**values)


def chunk():
    return EvidenceChunk(
        chunk_id="chunk-1", source_id="source-1", url="https://example.com", title="Title",
        section="Methods", text="evidence", position=2, entity_ids=["entity-1"], content_hash="hash",
        published_at=datetime(2024, 1, 2, tzinfo=UTC),
    )


def test_ensure_collection_creates_missing_collection_with_configured_dimensions():
    client = FakeClient()

    QdrantVectorStore(settings(), client=client)

    assert client.created[0]["collection_name"] == "evidence"
    vector_config = client.created[0]["vectors_config"]
    assert vector_config.size == 3


def test_qdrant_point_id_is_a_deterministic_uuid():
    first = qdrant_point_id("chunk-1")

    assert first == qdrant_point_id("chunk-1")
    assert first != qdrant_point_id("chunk-2")
    assert UUID(first).version == 5


def test_upsert_writes_vector_and_evidence_metadata():
    client = FakeClient(collection_exists=True)
    store = QdrantVectorStore(settings(), client=client)

    store.upsert([chunk()], vectors=[[0.1, 0.2, 0.3]])

    point = client.upserts[0]["points"][0]
    assert point.id == qdrant_point_id("chunk-1")
    assert point.vector == [0.1, 0.2, 0.3]
    assert point.payload == {
        "chunk_id": "chunk-1", "source_id": "source-1", "url": "https://example.com",
        "title": "Title", "section": "Methods", "text": "evidence", "position": 2,
        "entity_ids": ["entity-1"], "content_hash": "hash", "published_at": "2024-01-02T00:00:00Z",
    }


def test_upsert_batches_points_by_configured_maximum_without_data_loss():
    client = FakeClient(collection_exists=True)
    store = QdrantVectorStore(settings(qdrant_upsert_batch_size=2), client=client)
    chunks = [chunk().model_copy(update={"chunk_id": f"chunk-{index}", "position": index}) for index in range(5)]
    vectors = [[index + 0.1, 0.2, 0.3] for index in range(5)]

    store.upsert(chunks, vectors=vectors)

    assert [len(upsert["points"]) for upsert in client.upserts] == [2, 2, 1]
    points = [point for upsert in client.upserts for point in upsert["points"]]
    assert [point.id for point in points] == [qdrant_point_id(chunk.chunk_id) for chunk in chunks]
    assert [point.vector for point in points] == vectors
    assert [point.payload["position"] for point in points] == list(range(5))


def test_upsert_batches_points_by_estimated_payload_bytes():
    client = FakeClient(collection_exists=True)
    store = QdrantVectorStore(settings(qdrant_upsert_batch_size=100, qdrant_upsert_batch_bytes=1_000), client=client)
    chunks = [chunk().model_copy(update={"chunk_id": f"chunk-{index}", "text": "evidence " * 100}) for index in range(3)]

    store.upsert(chunks, vectors=[[0.1, 0.2, 0.3] for _ in chunks])

    assert len(client.upserts) == 3
    assert [point.payload["chunk_id"] for upsert in client.upserts for point in upsert["points"]] == [chunk.chunk_id for chunk in chunks]


def test_upsert_batch_limits_must_be_positive():
    with pytest.raises(ValueError, match="QDRANT_UPSERT_BATCH_SIZE"):
        QdrantVectorStore(settings(qdrant_upsert_batch_size=0), client=FakeClient(collection_exists=True))

    with pytest.raises(ValueError, match="QDRANT_UPSERT_BATCH_BYTES"):
        QdrantVectorStore(settings(qdrant_upsert_batch_bytes=0), client=FakeClient(collection_exists=True))


def test_vector_search_applies_metadata_filters_and_normalizes_evidence():
    client = FakeClient(collection_exists=True)
    store = QdrantVectorStore(settings(), client=client)
    filters = SearchFilters(
        entity_ids=["entity-1"], source_ids=["source-1"],
        published_after=datetime(2023, 1, 1, tzinfo=UTC),
        published_before=datetime(2025, 1, 1, tzinfo=UTC),
    )

    results = store.hybrid_search("evidence", [0.1, 0.2, 0.3], filters, 5)

    assert results[0].chunk_id == "chunk-1"
    assert results[0].score == 0.91
    query_filter = client.queries[0]["query_filter"]
    dumped = query_filter.model_dump(exclude_none=True)
    assert dumped["must"]
    assert client.queries[0]["limit"] == 5


def test_factory_builds_qdrant_and_rejects_missing_configuration():
    client = FakeClient(collection_exists=True)
    store = build_vector_store(settings(), qdrant_client=client)
    assert isinstance(store, QdrantVectorStore)

    with pytest.raises(ValueError, match="QDRANT_URL"):
        build_vector_store(settings(qdrant_url=None), qdrant_client=client)


def test_qdrant_errors_redact_api_key():
    class FailingClient(FakeClient):
        def upsert(self, **kwargs):
            raise RuntimeError("request failed with fake-qdrant-key")

    store = QdrantVectorStore(settings(), client=FailingClient(collection_exists=True))
    with pytest.raises(RuntimeError) as error:
        store.upsert([chunk()], vectors=[[0.1, 0.2, 0.3]])

    assert "fake-qdrant-key" not in str(error.value)
    assert "[REDACTED]" in str(error.value)
