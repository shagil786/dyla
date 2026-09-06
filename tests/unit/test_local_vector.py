"""LocalVectorStore behaviour.

Split out of the old test_search.py, which was really an Azure AI Search test
file with one local test hiding at the bottom.
"""

from dyla.domain import EvidenceChunk, SearchFilters
from dyla.local_vector import LocalVectorStore


def test_reingesting_a_page_for_a_second_entity_keeps_the_first_attribution():
    """chunk_id is a content hash and carries no entity information.

    Without merging, researching entity B over a page already indexed for entity
    A silently un-tags it from A, so a later entity-filtered query misses it.
    That is how memory reuse quietly stopped engaging for Q5-Q7 of the suite.
    """
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


def test_hybrid_search_rejects_a_query_vector_of_the_wrong_dimension():
    """upsert validates vector dimensions; search must too.

    zip would silently truncate to the shorter side and return a
    plausible-looking garbage score instead of an error.
    """
    def chunk():
        return EvidenceChunk(
            chunk_id="c1", source_id="s1", url="https://example.com/a",
            title="A", section=None, text="shared page", position=0,
            entity_ids=[], content_hash="h", published_at=None,
        )

    store = LocalVectorStore(vector_dimensions=3)
    store._items["c1"] = (chunk(), [0.1, 0.2, 0.3])
    try:
        store.hybrid_search("shared", [1.0, 2.0], SearchFilters(), 5)
    except ValueError as exc:
        assert "dimension" in str(exc)
    else:
        raise AssertionError("a mismatched query vector was silently scored")


def test_the_lexical_channel_rescues_a_useless_embedding():
    """Pure dense scoring with the offline hash embedder is noise; the lexical
    channel must be able to put the on-topic chunk ahead of an off-topic one."""
    def chunk(chunk_id, text):
        return EvidenceChunk(
            chunk_id=chunk_id, source_id="s1", url=f"https://example.com/{chunk_id}",
            title=chunk_id, section=None, text=text, position=0,
            entity_ids=[], content_hash="h", published_at=None,
        )

    store = LocalVectorStore()
    on_topic = chunk("on", "Infosys reported consolidated revenue growth for the financial year")
    off_topic = chunk("off", "The monsoon arrived early across the coastal belt this week")
    # Dense scores alone rank the off-topic chunk first (1.0 vs 0.9992); only
    # the lexical channel puts the on-topic chunk on top.
    store.upsert([on_topic, off_topic], [[0.999, 0.04], [1.0, 0.0]])

    query = "Infosys revenue growth financial year"
    found = store.hybrid_search(query, [1.0, 0.0], SearchFilters(), 2)
    assert found[0].chunk_id == "on", "the off-topic chunk outranked the on-topic one"
