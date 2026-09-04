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
