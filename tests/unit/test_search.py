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
    assert search_payload["search_text"] == "evidence"
    assert "vectorQueries" in search_payload
    assert "entity_ids/any" in search_payload["filter"]


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
