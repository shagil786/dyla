from dyla.domain import Document
from dyla.ingest import ingest_document


def test_ingest_embeds_each_chunk_and_upserts_with_matching_vectors():
    calls = {}

    class Embedder:
        def embed(self, texts):
            calls["texts"] = texts
            return [[float(index)] for index, _ in enumerate(texts)]

    class Sink:
        def upsert(self, chunks, vectors):
            calls["chunks"] = chunks
            calls["vectors"] = vectors

    chunks = ingest_document(
        Document(source_id="s", url="https://example.com", title="T", text="one paragraph", published_at=None),
        Embedder(), Sink(), max_chars=100,
    )
    assert len(chunks) == 1
    assert calls["texts"] == ["one paragraph"]
    assert calls["vectors"] == [[0.0]]
    assert calls["chunks"] == chunks
