import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from dyla.domain import AuditVerdict, Claim, Citation
from dyla.memory import MemoryStore


def _seed_text(store, text, *, claim_id, source_ids=()):
    """Seed a memory record the way production does: through save_claim.

    save_claim is the store's only writer (add_memory was removed as dead
    API), so tests seed through it too. search_memory does not filter by
    kind, and verdict=None stores the record unverified.
    """
    citations = [
        Citation(
            url=f"https://example.com/{source_id}",
            title="Source",
            source_id=source_id,
            chunk_id=f"{source_id}-chunk",
        )
        for source_id in source_ids
    ]
    store.save_claim(
        Claim(id=claim_id, text=text, citations=citations, confidence="high"),
        None,
    )


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
    _seed_text(
        store,
        "Acme announced a new product.",
        claim_id="c1",
        source_ids=["source-1"],
    )
    _seed_text(
        store,
        "Acme product sales increased.",
        claim_id="c2",
        source_ids=["source-2"],
    )

    records = store.search_memory("product", limit=10)

    assert [record.text for record in records] == [
        "Acme announced a new product.",
        "Acme product sales increased.",
    ]
    assert records[0].verified is False
    assert records[0].source_ids == ["source-1"]


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


def test_memory_operations_are_safe_from_worker_threads_and_concurrent_access(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    _seed_text(store, "seed record", claim_id="seed")

    async def search_from_worker():
        return await asyncio.to_thread(store.search_memory, "seed", 10)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                _seed_text,
                store,
                f"concurrent record {index}",
                claim_id=f"concurrent-{index}",
            )
            for index in range(20)
        ]
        futures.extend(
            executor.submit(store.search_memory, "record", 50)
            for _ in range(20)
        )
        worker_search = asyncio.run(search_from_worker())
        for future in futures:
            future.result()

    assert [record.text for record in worker_search] == ["seed record"]
    assert len(store.search_memory("concurrent", limit=50)) == 20


def test_search_memory_strips_punctuation_from_each_query_term(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    _seed_text(
        store,
        "Zerodha was founded in 2010 by Nithin Kamath.",
        claim_id="c1",
    )

    records = store.search_memory("Zerodha, founded", limit=10)

    assert [record.text for record in records] == [
        "Zerodha was founded in 2010 by Nithin Kamath."
    ]


def test_search_memory_finds_relevant_record_for_multi_word_question(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    _seed_text(
        store,
        "He joined Zerodha in 2013 to start its technology team.",
        claim_id="c1",
    )
    _seed_text(
        store, "Acme announced a quarterly filing.", claim_id="c2"
    )

    records = store.search_memory(
        "Who is the chief technology officer of Zerodha and what did he do before?",
        limit=10,
    )

    assert [record.text for record in records] == [
        "He joined Zerodha in 2013 to start its technology team."
    ]


def test_search_memory_orders_records_by_number_of_overlapping_terms(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    _seed_text(
        store, "Zerodha is an Indian stockbroker.", claim_id="c1"
    )
    _seed_text(
        store,
        "Nithin Kamath is the chief executive officer of Zerodha.",
        claim_id="c2",
    )

    records = store.search_memory(
        "Who is the chief executive officer of Zerodha?", limit=10
    )

    assert [record.text for record in records] == [
        "Nithin Kamath is the chief executive officer of Zerodha.",
        "Zerodha is an Indian stockbroker.",
    ]


def test_search_memory_ignores_stopword_only_and_punctuation_only_queries(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    _seed_text(
        store, "Zerodha is an Indian stockbroker.", claim_id="c1"
    )

    assert store.search_memory("The of and who is?", limit=10) == []
    assert store.search_memory("?! ..., ;", limit=10) == []


def test_search_memory_returns_nothing_for_unrelated_queries(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    _seed_text(
        store,
        "He joined Zerodha in 2013 to start its technology team.",
        claim_id="c1",
    )
    _seed_text(
        store,
        "Zerodha was founded in 2010 by Nithin Kamath.",
        claim_id="c2",
    )

    records = store.search_memory("What is the capital of France?", limit=10)

    assert records == []


def test_search_memory_limit_applies_to_ranked_results(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    _seed_text(
        store, "Zerodha is an Indian stockbroker.", claim_id="c1"
    )
    _seed_text(
        store,
        "Zerodha built its ranking technology in house.",
        claim_id="c2",
    )
    _seed_text(
        store, "Zerodha publishes a ranking of brokers.", claim_id="c3"
    )

    records = store.search_memory("Zerodha ranking", limit=2)

    assert [record.text for record in records] == [
        "Zerodha built its ranking technology in house.",
        "Zerodha publishes a ranking of brokers.",
    ]
    assert store.search_memory("Zerodha ranking", limit=1) == [records[0]]


def test_initialize_is_safe_to_call_more_than_once(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    store.initialize()
    store.initialize()

    assert store.connection.execute("SELECT 1").fetchone()[0] == 1


def test_memory_records_carry_no_free_text_index(tmp_path):
    """The schema must not index text no query can use.

    search_memory normalizes and scores every row in Python, so a B-tree index
    on the text column serves nothing — it only taxes every write. The linear
    scan is deliberate (documented on search_memory); this test pins the
    absence of the dead index, including for databases created before it was
    removed.
    """
    path = tmp_path / "memory.db"

    store = MemoryStore(path)
    store.initialize()

    names = {
        row[0]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert "memory_records_text" not in names
    _seed_text(
        store, "Zerodha is an Indian stockbroker.", claim_id="c1"
    )
    assert store.search_memory("stockbroker")  # the scan still works

    # Simulate a database created by an older version, then re-initialize:
    # the migration must drop the leftover index.
    store.connection.execute(
        "CREATE INDEX IF NOT EXISTS memory_records_text ON memory_records(text)"
    )
    store.connection.commit()
    reopened = MemoryStore(path)
    reopened.initialize()
    names = {
        row[0]
        for row in reopened.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert "memory_records_text" not in names
    assert reopened.search_memory("stockbroker")
