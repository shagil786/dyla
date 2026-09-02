import os

import uuid

import pytest

from dyla.config import load_settings
from dyla.domain import EvidenceChunk, SearchFilters
from dyla.search import SearchIndex

pytestmark = pytest.mark.skipif(
    os.getenv("DYLA_RUN_LIVE_TESTS") != "1",
    reason="set DYLA_RUN_LIVE_TESTS=1 to run Azure integration tests",
)


def test_live_azure_search_is_explicitly_opt_in():
    settings = load_settings()
    index_name = f"{settings.azure_search_index}-task5-{uuid.uuid4().hex[:12]}"
    index = SearchIndex(settings.azure_search_endpoint, settings.azure_search_api_key, index_name, vector_dimensions=settings.azure_search_vector_dimensions)
    chunk = EvidenceChunk(chunk_id="task5-smoke", source_id="task5-smoke-source", url="https://example.com/task5", title="Task 5 smoke", section="smoke", text="Dyla Azure hybrid retrieval smoke test", position=0, entity_ids=["task5-smoke-entity"], content_hash="task5-smoke-hash")
    vector = [0.0] * settings.azure_search_vector_dimensions
    try:
        index.ensure_index()
        index.upsert([chunk], vectors=[vector])
        results = index.hybrid_search("hybrid retrieval smoke", vector, SearchFilters(entity_ids=["task5-smoke-entity"], source_ids=["task5-smoke-source"]), 5)
        assert any(result.chunk_id == chunk.chunk_id for result in results)
    finally:
        index.delete_index()
        index.close()
