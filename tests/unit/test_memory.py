from datetime import datetime, timezone

from dyla.domain import AuditVerdict, Claim, Citation
from dyla.memory import MemoryStore


def test_initialize_creates_application_memory_schema(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    store.initialize()

    tables = {
        row[0]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "entities",
        "aliases",
        "claims",
        "audit_verdicts",
        "sources",
        "research_warnings",
        "memory_records",
    } <= tables


def test_upsert_entity_reuses_id_and_alias_search_is_exact(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()

    first_id = store.upsert_entity("Acme Corporation", "organization")
    second_id = store.upsert_entity(" acme   corporation ", "organization")
    store.add_alias(first_id, "Acme", 1.0)
    store.add_alias(first_id, "ACME Corp", 0.9)

    assert first_id == second_id
    assert [record["canonical_name"] for record in store.find_entities(" acme ")] == [
        "Acme Corporation"
    ]


def test_search_memory_returns_matching_records_in_stable_order(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    entity_id = store.upsert_entity("Acme Corporation", "organization")
    store.add_memory(
        "Acme announced a new product.",
        kind="note",
        entity_ids=[entity_id],
        source_ids=["source-1"],
    )
    store.add_memory(
        "Acme product sales increased.",
        kind="note",
        entity_ids=[entity_id],
        source_ids=["source-2"],
    )

    records = store.search_memory("product", limit=10)

    assert [record.text for record in records] == [
        "Acme announced a new product.",
        "Acme product sales increased.",
    ]
    assert records[0].verified is False


def test_save_claim_persists_claim_verdict_sources_and_memory_record(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    claim = Claim(
        id="claim-1",
        text="Acme launched in 2020.",
        confidence="high",
        citations=[
            Citation(
                url="https://example.com/acme",
                title="Acme history",
                source_id="source-1",
                chunk_id="chunk-1",
            )
        ],
    )
    verdict = AuditVerdict(
        claim_id=claim.id,
        status="supported",
        explanation="The source supports the claim.",
        citations_checked=claim.citations,
    )

    store.save_claim(claim, verdict)

    record = store.search_memory("launched", limit=1)[0]
    assert record.id == claim.id
    assert record.kind == "claim"
    assert record.source_ids == ["source-1"]
    assert record.verified is True
    assert store.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM audit_verdicts").fetchone()[0] == 1


def test_research_warnings_can_be_saved_and_read_in_newest_first_order(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()

    first_id = store.save_research_warning("First warning")
    second_id = store.save_research_warning("Second warning")

    assert second_id > first_id
    assert store.read_research_warnings() == ["Second warning", "First warning"]
    assert store.read_research_warnings(limit=1) == ["Second warning"]


def test_research_warning_rejects_empty_text(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()

    try:
        store.save_research_warning("  ")
    except ValueError:
        pass
    else:
        raise AssertionError("empty research warning was accepted")


def test_initialize_is_safe_to_call_more_than_once(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    store.initialize()
    store.initialize()

    assert store.connection.execute("SELECT 1").fetchone()[0] == 1
