from dyla.entities import EntityResolver
from dyla.memory import MemoryStore


def make_resolver(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    return store, EntityResolver(store)


def test_resolve_prefers_exact_normalized_alias(tmp_path):
    store, resolver = make_resolver(tmp_path)
    entity_id = store.upsert_entity("Acme Corporation", "organization")
    store.add_alias(entity_id, "ACME Corp.", 0.95)

    result = resolver.resolve("  acme corp ", "company context")

    assert result.entity_id == entity_id
    assert result.canonical_name == "Acme Corporation"
    assert result.confidence == 1.0
    assert result.status == "resolved"
    assert result.candidates == ["Acme Corporation"]


def test_resolve_uses_deterministic_fuzzy_match(tmp_path):
    store, resolver = make_resolver(tmp_path)
    entity_id = store.upsert_entity("OpenAI", "organization")
    store.add_alias(entity_id, "Open AI", 0.9)
    store.upsert_entity("Open Access Initiative", "organization")

    result = resolver.resolve("OpenAI's", "an AI company")

    assert result.entity_id == entity_id
    assert result.canonical_name == "OpenAI"
    assert result.status == "resolved"
    assert result.confidence > 0.5


def test_resolve_reports_ambiguous_close_candidates(tmp_path):
    store, resolver = make_resolver(tmp_path)
    first_id = store.upsert_entity("Acme Labs", "organization")
    second_id = store.upsert_entity("Acme Labs Group", "organization")
    store.add_alias(first_id, "Acme", 0.8)
    store.add_alias(second_id, "Acme", 0.8)

    result = resolver.resolve("Acme", "the organization")

    assert result.entity_id is None
    assert result.canonical_name is None
    assert result.status == "ambiguous"
    assert result.candidates == ["Acme Labs", "Acme Labs Group"]


def test_resolve_returns_unknown_when_no_candidate_reaches_threshold(tmp_path):
    _, resolver = make_resolver(tmp_path)

    result = resolver.resolve("Nonexistent", "context")

    assert result.entity_id is None
    assert result.canonical_name is None
    assert result.status == "unknown"
    assert result.candidates == []
