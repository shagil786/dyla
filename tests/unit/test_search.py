import json

import httpx

from dyla.domain import EvidenceChunk, SearchFilters
from dyla.search import SearchIndex


def chunk():
    return EvidenceChunk(
        chunk_id="chunk-1", source_id="source-1", url="https://example.com", title="Title",
        section="Methods", text="evidence text", position=0, entity_ids=["entity-1"], content_hash="hash",
    )


def test_search_index_creates_schema_upserts_in_batches_and_hybrid_searches():
    requests = []

    def handler(request: httpx.Request):
        requests.append((request.method, request.url.path, request.content))
        if request.method == "POST":
            return httpx.Response(200, json={"value": [{"chunk_id": "chunk-1", "source_id": "source-1", "url": "https://example.com", "title": "Title", "text": "evidence text", "score": 1.2, "entity_ids": ["entity-1"]}]})
        return httpx.Response(200, json={})

    index = SearchIndex(
        "https://search.example", "key", "evidence", vector_dimensions=3,
        transport=httpx.MockTransport(handler), batch_size=1,
    )
    index.ensure_index()
    index.upsert([chunk()], vectors=[[0.1, 0.2, 0.3]])
    evidence = index.hybrid_search("evidence", [0.1, 0.2, 0.3], SearchFilters(entity_ids=["entity-1"]), 5)

    assert evidence[0].chunk_id == "chunk-1"
    assert requests[0][0] == "PUT"
    upsert_payload = json.loads(requests[1][2])
    assert upsert_payload["value"][0]["@search.action"] == "mergeOrUpload"
    search_payload = json.loads(requests[2][2])
    assert search_payload["search"] == "evidence"
    assert "vectorQueries" in search_payload
    assert "entity_ids/any" in search_payload["filter"]


def test_search_index_rejects_malformed_search_date():
    def handler(request):
        return httpx.Response(200, json={"value": [{"chunk_id": "c", "source_id": "s", "url": "https://example.com", "text": "t", "score": 1, "entity_ids": [], "published_at": "not-a-date"}]})

    index = SearchIndex("https://search.example", "key", "evidence", vector_dimensions=3, transport=httpx.MockTransport(handler))
    assert index.hybrid_search("q", [0.1, 0.2, 0.3], SearchFilters(), 1)[0].chunk_id == "c"


def test_search_index_can_embed_chunks_when_vectors_are_not_supplied():
    class Embedder:
        def embed(self, texts):
            assert texts == ["evidence text"]
            return [[0.1, 0.2, 0.3]]

    requests = []
    transport = httpx.MockTransport(lambda request: (requests.append(request), httpx.Response(200, json={}))[1])
    index = SearchIndex("https://search.example", "key", "evidence", vector_dimensions=3, transport=transport, embedder=Embedder())
    index.upsert([chunk()])
    assert requests[0].url.path.endswith("/docs/index")


def test_search_index_rejects_vector_dimension_mismatch():
    index = SearchIndex("https://search.example", "key", "evidence", vector_dimensions=3, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    try:
        index.upsert([chunk()], vectors=[[1.0]])
    except ValueError as exc:
        assert "dimension" in str(exc)
    else:
        raise AssertionError("expected dimension mismatch")


def test_reingesting_a_page_for_a_second_entity_keeps_the_first_attribution():
    """chunk_id is a content hash and carries no entity information.

    Without merging, researching entity B over a page already indexed for entity
    A silently un-tags it from A, so a later entity-filtered query misses it.
    That is how memory reuse quietly stopped engaging for Q5-Q7 of the suite.
    """
    from dyla.domain import EvidenceChunk, SearchFilters
    from dyla.local_vector import LocalVectorStore

    def chunk(entity_ids):
        return EvidenceChunk(
            chunk_id="same-chunk", source_id="s1", url="https://example.com/a",
            title="A", section=None, text="shared page", position=0,
            entity_ids=entity_ids, content_hash="h", published_at=None,
        )

    store = LocalVectorStore()
    store.upsert([chunk(["entity-a"])], [[1.0, 0.0]])
    store.upsert([chunk(["entity-b"])], [[1.0, 0.0]])

    for entity in ("entity-a", "entity-b"):
        found = store.hybrid_search("shared", [1.0, 0.0], SearchFilters(entity_ids=[entity]), 5)
        assert len(found) == 1, f"{entity} lost its attribution"
    assert set(store.hybrid_search("shared", [1.0, 0.0], SearchFilters(), 5)[0].entity_ids) == {
        "entity-a", "entity-b"
    }
