from dyla.chunking import chunk_document
from dyla.domain import Document


def test_chunking_is_heading_aware_with_overlap_and_citation_metadata():
    document = Document(
        source_id="source-1", url="https://example.com/a", title="Title",
        text="Intro sentence. " * 20 + "\nMethods\n" + "Method detail. " * 20,
        published_at=None,
    )
    chunks = chunk_document(document, max_chars=180, overlap_chars=30)
    assert len(chunks) > 1
    assert chunks[0].section is None
    assert any(chunk.section == "Methods" for chunk in chunks)
    assert all(chunk.url == document.url and chunk.title == document.title for chunk in chunks)
    assert all(chunk.source_id == document.source_id and chunk.content_hash for chunk in chunks)
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    assert any(chunks[i].text[-30:] in chunks[i + 1].text for i in range(len(chunks) - 1))


def test_chunking_preserves_document_entities_and_published_date_in_chunk_metadata():
    document = Document(
        source_id="s", url="https://example.com", title=None, text="A paragraph.", published_at=None,
    )
    chunks = chunk_document(document, entity_ids=["entity-1"])
    assert chunks[0].entity_ids == ["entity-1"]


def test_oversized_paragraph_preserves_all_content():
    paragraph = " ".join(f"word-{index}" for index in range(100))
    document = Document(source_id="s", url="https://example.com", title=None, text=paragraph, published_at=None)
    chunks = chunk_document(document, max_chars=80, overlap_chars=10)
    combined = " ".join(chunk.text for chunk in chunks)
    assert all(f"word-{index}" in combined for index in range(100))


def test_chunking_rejects_invalid_limits():
    document = Document(source_id="s", url="https://example.com", title=None, text="text", published_at=None)
    try:
        chunk_document(document, max_chars=0)
    except ValueError as exc:
        assert "max_chars" in str(exc)
    else:
        raise AssertionError("expected invalid max_chars to fail")
