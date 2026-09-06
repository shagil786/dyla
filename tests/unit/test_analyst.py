import asyncio
from types import SimpleNamespace
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dyla.analyst import AnalystAgent
from dyla.domain import AnalystAnswer, Citation, Claim, Evidence, MemoryRecord, ResearchPlan, SearchHit
from dyla.tracing import TraceWriter


class FakeResolver:
    def resolve(self, mention, context):
        return type("Resolved", (), {"entity_id": "e1", "canonical_name": "Acme", "status": "resolved"})()


class FakeMemory:
    def search_memory(self, query, limit=10):
        return [MemoryRecord(id="m1", kind="fact", text="Acme fact", entity_ids=["e1"], source_ids=[], verified=True)]


class FakeSearcher:
    def __init__(self):
        self.started = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def search(self, query, limit=5):
        with self.lock:
            self.started += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            number = self.started
        time.sleep(0.03)
        with self.lock:
            self.active -= 1
        return [SearchHit(url=f"https://example.com/{number}", title="Source", snippet=query, published_at=None)]


class FakeFetcher:
    def fetch(self, url):
        return type("Document", (), {"source_id": url, "url": url, "title": "Source", "text": "evidence", "published_at": None})()


class FakeIndex:
    def __init__(self, evidence=None):
        self.evidence = evidence if evidence is not None else [Evidence(chunk_id="c1", source_id="s1", url="https://example.com/1", title="Source", text="evidence", score=0.9, entity_ids=["e1"])]
        self.filters = []
        self.upserted = []

    def upsert(self, chunks, vectors):
        self.upserted.extend(chunks)

    def hybrid_search(self, query, vector, filters, limit):
        self.filters.append(filters)
        return self.evidence


class FakeEmbedder:
    def embed(self, texts):
        return [[0.0] for _ in texts]


class FakeModel:
    def complete(self, request):
        return type("Response", (), {"parsed": AnalystAnswer(answer="Answer", claims=[Claim(id="c1", text="evidence", citations=[Citation(url="https://example.com/1", title="Source", source_id="s1", chunk_id="c1")], confidence="high")], limitations=[])})()


def test_analyst_runs_independent_searches_concurrently_and_returns_structured_answer():
    searcher = FakeSearcher()
    agent = AnalystAgent(
        model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=searcher,
        fetcher=FakeFetcher(), index=FakeIndex(), embedder=FakeEmbedder(), max_subqueries=2,
    )
    result = asyncio.run(agent.run("What happened to Acme in 2025?", "run-1"))
    assert isinstance(result, AnalystAnswer)
    assert result.answer == "Answer"
    assert searcher.started == 2
    assert searcher.max_active == 2


def controlled_planner(plan):
    class Planner:
        def expand(self, question, memory):
            return plan
    return Planner()


def make_agent(model, plan, index=None):
    return AnalystAgent(model=model, resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                        fetcher=FakeFetcher(), index=index or FakeIndex(), embedder=FakeEmbedder(), planner=controlled_planner(plan))


def test_analyst_returns_insufficient_evidence_without_calling_model():
    class Model:
        def complete(self, request):
            raise AssertionError("empty evidence must not synthesize")
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[])
    agent = make_agent(Model(), plan, FakeIndex(evidence=[]))
    answer = asyncio.run(agent.run("Q", "run-empty"))
    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    assert answer.limitations == ["No retrieved evidence was available."]


def test_analyst_synthesis_retains_citation_matching_supplied_metadata():
    evidence = Evidence(
        chunk_id="chunk-17", source_id="source-42", url="https://example.com/report",
        title="Annual Report", text="Revenue increased.", score=0.9, entity_ids=[],
    )

    class Model:
        def __init__(self):
            self.request = None

        def complete(self, request):
            self.request = request
            return type("R", (), {"parsed": AnalystAnswer(
                answer="Revenue increased.",
                claims=[Claim(
                    id="c1", text="Revenue increased.",
                    citations=[Citation(
                        url="https://example.com/report", title="Annual Report",
                        source_id="source-42", chunk_id="chunk-17",
                    )], confidence="high",
                )], limitations=[],
            )})()

    model = Model()
    answer = make_agent(model, ResearchPlan(
        original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[],
    ))._synthesize("Q", [], [evidence], [])

    assert model.request is not None
    prompt = model.request.messages[1]["content"]
    assert "source_id: source-42" in prompt
    assert "chunk_id: chunk-17" in prompt
    assert "url: https://example.com/report" in prompt
    assert "title: Annual Report" in prompt
    assert "text: Revenue increased." in prompt
    assert answer.claims[0].citations[0] == Citation(
        url="https://example.com/report", title="Annual Report",
        source_id="source-42", chunk_id="chunk-17",
    )


def test_analyst_synthesis_rejects_citation_with_mismatched_supplied_metadata():
    evidence = Evidence(
        chunk_id="chunk-17", source_id="source-42", url="https://example.com/report",
        title="Annual Report", text="Revenue increased.", score=0.9, entity_ids=[],
    )
    citation = Citation(
        url="https://example.com/report", title="Annual Report",
        source_id="invented-source", chunk_id="invented-chunk",
    )

    class Model:
        def complete(self, request):
            return type("R", (), {"parsed": AnalystAnswer(
                answer="Fabricated.",
                claims=[Claim(id="c1", text="Fabricated.", citations=[citation], confidence="high")],
                limitations=[],
            )})()

    answer = make_agent(Model(), ResearchPlan(
        original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[],
    ))._synthesize("Q", [], [evidence], [])

    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    assert any("citation" in item.lower() for item in answer.limitations)


def test_analyst_rejects_claims_with_unmapped_citations():
    citation = Citation(url="https://other", title="Other", source_id="other", chunk_id="x")
    model = type("Model", (), {"complete": lambda self, request: type("R", (), {"parsed": AnalystAnswer(answer="fabricated", claims=[Claim(id="c", text="bad", citations=[citation], confidence="high")], limitations=[])})()})()
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[])
    answer = asyncio.run(make_agent(model, plan).run("Q", "run-map"))
    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    assert any("citation" in item.lower() for item in answer.limitations)


def test_analyst_marks_weak_claim_without_independent_evidence():
    model = type("Model", (), {"complete": lambda self, request: type("R", (), {"parsed": AnalystAnswer(answer="answer", claims=[Claim(id="c", text="weak", citations=[Citation(url="https://example.com/1", title="Source", source_id="s1", chunk_id="c1")], confidence="low")], limitations=[])})()})()
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[])
    answer = asyncio.run(make_agent(model, plan).run("Q", "run-weak"))
    assert answer.claims == []
    assert any("independent" in item.lower() for item in answer.limitations)


# ---------------------------------------------------------------------------
# Cross-check (corroboration) of single-source claims
#
# The cross-check gate must not be keyed on the model's self-reported
# confidence: a model that labels everything "high" is exactly the failure
# mode a confidence-keyed check cannot see. These tests drive real claims
# through bespoke search/fetch pairs so the corroboration outcome is
# controlled.
# ---------------------------------------------------------------------------

def _figure_claim_model(text="In 2024, Acme opened 250 new stores.", confidence="high"):
    return type("Model", (), {"complete": lambda self, request: type("R", (), {"parsed": AnalystAnswer(
        answer=text,
        claims=[Claim(id="c", text=text,
                      citations=[Citation(url="https://example.com/1", title="Source",
                                          source_id="s1", chunk_id="c1")],
                      confidence=confidence)],
        limitations=[],
    )})()})()


class _CorroborationSearcher:
    """Returns the same hit for every query, remembering the query."""

    def __init__(self, urls=("https://example.com/other",)):
        self.urls = list(urls)

    def search(self, query, limit=5):
        return [SearchHit(url=url, title="Source", snippet=query, published_at=None)
                for url in self.urls]


def _agent_with_corroboration(model, searcher, fetcher_text):
    class Fetcher:
        def fetch(self, url):
            return type("Document", (), {"source_id": url, "url": url, "title": "Source",
                                         "text": fetcher_text, "published_at": None})()

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}],
                        entities=[], date_constraints=[])
    return make_agent(model, plan), Fetcher()


def test_single_source_figure_claim_is_rejected_when_independent_sources_do_not_state_the_figure():
    model = _figure_claim_model()
    agent, fetcher = _agent_with_corroboration(model, _CorroborationSearcher(), fetcher_text=(
        "Acme opened fewer than 50 new stores in 2024 and closed several older ones."
    ))
    agent.fetcher = fetcher

    answer = asyncio.run(agent.run("Q", "run-no-corroboration"))

    assert answer.claims == []
    assert any("independent" in item.lower() for item in answer.limitations)
    assert agent.metrics["corroboration_searches"] == 1
    assert agent.metrics["corroboration_fetches"] == 1


def test_single_source_figure_claim_is_accepted_when_an_independent_source_states_the_figure():
    model = _figure_claim_model()
    agent, fetcher = _agent_with_corroboration(model, _CorroborationSearcher(), fetcher_text=(
        "Acme opened 250 new stores in 2024, its annual report confirmed, taking the "
        "total past 1,000 nationwide."
    ))
    agent.fetcher = fetcher

    answer = asyncio.run(agent.run("Q", "run-corroborated"))

    assert [claim.text for claim in answer.claims] == ["In 2024, Acme opened 250 new stores."]
    assert agent.metrics["corroboration_searches"] == 1


def test_the_cross_check_is_not_keyed_on_self_reported_confidence():
    """A claim the model calls 'high' confidence must still be cross-checked.

    This is the gate the old code got backwards: confidence is a model output,
    so a model that labels everything 'high' used to bypass corroboration
    entirely. The figure-bearing claim below is rejected despite 'high'.
    """
    model = _figure_claim_model(confidence="high")
    agent, fetcher = _agent_with_corroboration(model, _CorroborationSearcher(), fetcher_text=(
        "Acme opened 20 new stores in 2024, far below its earlier target."
    ))
    agent.fetcher = fetcher

    answer = asyncio.run(agent.run("Q", "run-high-confidence"))

    assert answer.claims == []
    assert agent.metrics["corroboration_searches"] == 1


def test_a_claim_restated_by_a_supported_memory_skips_the_cross_check():
    """A prior run's *supported* verdict is stronger than a fresh search."""
    text = "Acme opened 250 new stores in 2024."
    memory = _MemoryWithVerdicts([_claim_record(text, "supported", verified=True)])
    agent = _agent_with(memory, _ModelReturning(text))

    result = asyncio.run(agent.run("How many stores did Acme open?", "run-covered"))

    assert [claim.text for claim in result.claims] == [text]
    assert agent.metrics["corroboration_searches"] == 0


def test_a_supported_memory_with_a_different_figure_does_not_cover_the_claim():
    """Wording overlap is not enough: the stored figure must agree.

    The fingerprint used for restatement ignores numbers by construction, so a
    supported memory claiming 250 stores must not bless a new claim of 1,250 —
    the cross-check must still run against independent sources.
    """
    model = _figure_claim_model(text="Acme opened 1,250 new stores in 2024.")
    memory = _MemoryWithVerdicts([_claim_record("Acme opened 250 new stores in 2024.",
                                                "supported", verified=True)])
    agent = _agent_with(memory, model)
    agent.searcher = _CorroborationSearcher()

    class Fetcher:
        def fetch(self, url):
            return type("Document", (), {"source_id": url, "url": url, "title": "Source",
                                         "text": ("Acme opened 20 new stores in 2024, far "
                                                  "below its earlier target."),
                                         "published_at": None})()

    agent.fetcher = Fetcher()

    result = asyncio.run(agent.run("How many stores did Acme open?", "run-uncovered"))

    assert result.claims == []
    assert agent.metrics["corroboration_searches"] == 1


def test_an_off_topic_page_quoting_the_same_number_is_not_corroboration_or_contradiction():
    """A page quoting the same figure about something else proves nothing.

    It must not count as corroboration, but equally must not reject a claim it
    does not address: an off-topic hit is no information either way, and a
    high-confidence claim survives to the auditor, which verifies the cited
    source.
    """
    model = _figure_claim_model()
    agent, fetcher = _agent_with_corroboration(model, _CorroborationSearcher(), fetcher_text=(
        "The Nifty index closed above 250 points in 2024 for the first time."
    ))
    agent.fetcher = fetcher

    answer = asyncio.run(agent.run("Q", "run-off-topic"))

    assert [claim.text for claim in answer.claims] == ["In 2024, Acme opened 250 new stores."]
    assert agent.metrics["corroboration_fetches"] == 1


def test_an_off_topic_page_still_fails_a_low_confidence_claim_closed():
    """Only the low-confidence carve-out rejects on absence of any on-topic source."""
    model = _figure_claim_model(confidence="low")
    agent, fetcher = _agent_with_corroboration(model, _CorroborationSearcher(), fetcher_text=(
        "The Nifty index closed above 250 points in 2024 for the first time."
    ))
    agent.fetcher = fetcher

    answer = asyncio.run(agent.run("Q", "run-off-topic-low"))

    assert answer.claims == []


def test_analyst_rejects_narrative_when_model_returns_no_supported_claims():
    model = type("Model", (), {"complete": lambda self, request: type("R", (), {"parsed": AnalystAnswer(answer="unsupported narrative", claims=[], limitations=[])})()})()
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[])
    answer = asyncio.run(make_agent(model, plan).run("Q", "run-narrative"))
    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []


def test_analyst_rejects_high_confidence_uncited_claim():
    model = type("Model", (), {"complete": lambda self, request: type("R", (), {"parsed": AnalystAnswer(answer="uncited narrative", claims=[Claim(id="c", text="unsupported", citations=[], confidence="high")], limitations=[])})()})()
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[])
    answer = asyncio.run(make_agent(model, plan).run("Q", "run-uncited"))
    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []


def test_analyst_reports_unsupported_non_year_date_constraint():
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=["March 2025"])
    answer = asyncio.run(make_agent(FakeModel(), plan, FakeIndex(evidence=[])).run("Q", "run-date"))
    assert answer.answer == "Insufficient evidence."
    assert any("date" in limitation.lower() for limitation in answer.limitations)


def test_analyst_notes_undated_sources_when_year_filter_applied():
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=["2025"])
    answer = asyncio.run(make_agent(FakeModel(), plan, FakeIndex()).run("Q", "run-undated"))
    assert "Date filter applied to sources published from 2025; sources without a published date were also considered." in answer.limitations


def test_analyst_date_limitation_states_the_range_for_multiple_years():
    """Two constrained years produce a continuous range filter; the limitation
    text must say the range rather than imply a set of individual years."""
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=["2023", "2025"])
    answer = asyncio.run(make_agent(FakeModel(), plan, FakeIndex()).run("Q", "run-range"))
    assert any(
        "from 2023 and 2025" in limitation and "published" in limitation
        for limitation in answer.limitations
    ), answer.limitations


def test_analyst_preserves_query_entity_attribution_and_date_filters():
    class Resolver:
        def resolve(self, mention, context):
            return type("Resolved", (), {"entity_id": "e1" if mention == "Acme" else "e2", "canonical_name": mention, "status": "resolved"})()
    class Memory(FakeMemory):
        pass
    index = FakeIndex()
    plan = ResearchPlan(original_question="Q", subqueries=[
        {"query": "Acme Q", "entities": ["Acme"]}, {"query": "Beta Q", "entities": ["Beta"]}
    ], entities=["Acme", "Beta"], date_constraints=["2025"])
    agent = AnalystAgent(model=FakeModel(), resolver=Resolver(), memory=Memory(), searcher=FakeSearcher(), fetcher=FakeFetcher(), index=index, embedder=FakeEmbedder(), planner=controlled_planner(plan))
    asyncio.run(agent.run("Q", "run-attribution"))
    assert {frozenset(chunk.entity_ids) for chunk in index.upserted} == {frozenset({"e1"}), frozenset({"e2"})}
    # Memory-first retrieval probes the index once per entity before searching,
    # so filters[0] is now a single-entity coverage probe rather than the main
    # retrieval filter. Select the main one by the date range it carries.
    main = next(item for item in index.filters if item.published_after is not None)
    assert main.entity_ids == ["e1", "e2"]
    assert main.published_after == datetime(2025, 1, 1, tzinfo=UTC)
    assert main.published_before == datetime(2026, 1, 1, tzinfo=UTC)


def test_analyst_survives_partial_fetch_failure_and_reports_exclusion():
    fail_url = "https://example.com/1"

    class FlakyFetcher:
        def fetch(self, url):
            if url == fail_url:
                raise ValueError("malformed contents response")
            return type("Document", (), {"source_id": url, "url": url, "title": "Source", "text": "evidence", "published_at": None})()

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    index = FakeIndex()
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=FlakyFetcher(), index=index, embedder=FakeEmbedder(), planner=controlled_planner(plan))
    answer = asyncio.run(agent.run("Q", "run-fetch-failure"))
    assert answer.answer == "Answer"
    assert "Page fetch failed for https://example.com/1; it was excluded from evidence." in answer.limitations
    assert agent.metrics["failed_fetches"] == 1
    assert agent.metrics["fetches"] == 2
    assert len(index.upserted) >= 1


def test_analyst_survives_partial_search_failure_and_reports_exclusion():
    class FlakySearcher:
        def search(self, query, limit=5):
            if query == "Q bad":
                raise TimeoutError("search backend unavailable")
            return [SearchHit(url=f"https://example.com/{query.removeprefix('Q ')}", title="Source", snippet=query, published_at=None)]

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q bad"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FlakySearcher(),
                         fetcher=FakeFetcher(), index=FakeIndex(), embedder=FakeEmbedder(), planner=controlled_planner(plan))
    answer = asyncio.run(agent.run("Q", "run-search-failure"))
    assert answer.answer == "Answer"
    assert "Web search failed for query 'Q bad'; its results were excluded." in answer.limitations
    assert agent.metrics["failed_searches"] == 1
    assert agent.metrics["fetches"] == 2


def test_analyst_returns_insufficient_evidence_when_all_fetches_fail():
    class FailingFetcher:
        def fetch(self, url):
            raise ValueError("malformed contents response")

    class Model:
        def complete(self, request):
            raise AssertionError("empty evidence must not synthesize")

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=Model(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=FailingFetcher(), index=FakeIndex(evidence=[]), embedder=FakeEmbedder(), planner=controlled_planner(plan))
    answer = asyncio.run(agent.run("Q", "run-all-fetch-failures"))
    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    assert "No retrieved evidence was available." in answer.limitations
    fetch_failures = [item for item in answer.limitations if item.startswith("Page fetch failed for ")]
    assert len(fetch_failures) == 2
    assert agent.metrics["failed_fetches"] == 2


def test_analyst_returns_insufficient_evidence_when_all_searches_fail():
    class FailingSearcher:
        def search(self, query, limit=5):
            raise TimeoutError("search backend unavailable")

    class Model:
        def complete(self, request):
            raise AssertionError("empty evidence must not synthesize")

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=Model(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FailingSearcher(),
                         fetcher=FakeFetcher(), index=FakeIndex(evidence=[]), embedder=FakeEmbedder(), planner=controlled_planner(plan))
    answer = asyncio.run(agent.run("Q", "run-all-search-failures"))
    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    search_failures = [item for item in answer.limitations if item.startswith("Web search failed for query ")]
    assert len(search_failures) == 2
    assert agent.metrics["failed_searches"] == 2
    assert agent.metrics["fetches"] == 0


def test_analyst_adds_no_limitations_when_everything_succeeds():
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = make_agent(FakeModel(), plan)
    answer = asyncio.run(agent.run("Q", "run-no-failures"))
    assert answer.answer == "Answer"
    assert answer.limitations == []
    assert agent.metrics["failed_searches"] == 0
    assert agent.metrics["failed_fetches"] == 0


def _read_trace(root, run_id):
    path = Path(root) / "logs" / f"{run_id}.jsonl"
    assert path.exists(), f"expected trace file at {path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_analyst_traces_memory_searches_fetches_and_evidence_for_successful_run(tmp_path):
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=FakeFetcher(), index=FakeIndex(), embedder=FakeEmbedder(),
                         planner=controlled_planner(plan), trace_writer=TraceWriter(tmp_path))
    answer = asyncio.run(agent.run("Q", "run-trace-success"))

    assert answer.answer == "Answer"
    events = _read_trace(tmp_path, "run-trace-success")
    # Assert the shape of the story the log tells, not a frozen list. Pinning
    # the exact event sequence has broken this suite every time a new event was
    # added, which punishes exactly the improvement the brief asks for.
    names = [event["event"] for event in events]
    assert names.index("memory_retrieved") < names.index("plan_created") < names.index("web_searched"), (
        "a reader must see memory consulted and a plan formed before any search"
    )
    assert names.index("page_fetched") < names.index("evidence_selected")
    assert names.count("web_searched") == 2
    assert names.count("page_fetched") == 2
    assert {event["component"] for event in events} == {"analyst"}

    by_event = {event["event"]: event["payload"] for event in events}
    assert by_event["memory_retrieved"] == {"count": 1}
    assert [event["payload"] for event in events if event["event"] == "web_searched"] == [
        {"query": "Q one", "results": 1},
        {"query": "Q two", "results": 1},
    ]
    assert sorted(
        (event["payload"] for event in events if event["event"] == "page_fetched"),
        key=lambda item: item["url"],
    ) == [
        {"url": "https://example.com/1", "chars": len("evidence")},
        {"url": "https://example.com/2", "chars": len("evidence")},
    ]
    assert by_event["plan_created"]["subqueries"] == ["Q one", "Q two"]
    assert by_event["evidence_selected"]["count"] == 1
    assert {event["run_id"] for event in events} == {"run-trace-success"}


def test_analyst_traces_page_fetch_failure_and_still_succeeds(tmp_path):
    fail_url = "https://example.com/1"

    class FlakyFetcher:
        def fetch(self, url):
            if url == fail_url:
                raise ValueError("malformed contents response")
            return type("Document", (), {"source_id": url, "url": url, "title": "Source", "text": "evidence", "published_at": None})()

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=FlakyFetcher(), index=FakeIndex(), embedder=FakeEmbedder(),
                         planner=controlled_planner(plan), trace_writer=TraceWriter(tmp_path))
    answer = asyncio.run(agent.run("Q", "run-trace-fetch-fail"))

    assert answer.answer == "Answer"
    events = _read_trace(tmp_path, "run-trace-fetch-fail")
    failures = [event for event in events if event["event"] == "page_fetch_failed"]
    fetched = [event for event in events if event["event"] == "page_fetched"]
    assert len(failures) == 1
    assert failures[0]["payload"]["url"] == fail_url
    assert "malformed contents response" in failures[0]["payload"]["error"]
    assert [event["payload"]["url"] for event in fetched] == ["https://example.com/2"]
    # The failure must not abort the run: evidence selection still happens after
    # it. Asserted by order rather than by "is the last event", so adding events
    # to the end of the run does not fail a test about fetch failures.
    names = [event["event"] for event in events]
    assert names.index("page_fetch_failed") < names.index("evidence_selected")


def test_analyst_without_trace_writer_emits_no_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=FakeFetcher(), index=FakeIndex(), embedder=FakeEmbedder(),
                         planner=controlled_planner(plan), trace_writer=None)
    answer = asyncio.run(agent.run("Q", "run-trace-none"))

    assert answer.answer == "Answer"
    assert not (tmp_path / "logs").exists()


def test_analyst_survives_ingestion_failure_and_reports_exclusion(tmp_path):
    fail_url = "https://example.com/1"

    class GlitchyEmbedder:
        def embed(self, texts):
            if any("glitch" in text for text in texts):
                raise ValueError("Compatible embedding call failed: retry exhaustion")
            return [[0.0] for _ in texts]

    class MarkerFetcher:
        def fetch(self, url):
            text = "glitch evidence" if url == fail_url else "evidence"
            return type("Document", (), {"source_id": url, "url": url, "title": "Source", "text": text, "published_at": None})()

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    index = FakeIndex()
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=MarkerFetcher(), index=index, embedder=GlitchyEmbedder(),
                         planner=controlled_planner(plan), trace_writer=TraceWriter(tmp_path))
    answer = asyncio.run(agent.run("Q", "run-ingest-failure"))

    assert answer.answer == "Answer"
    assert "Page content from https://example.com/1 could not be indexed for retrieval; it was excluded from evidence." in answer.limitations
    assert agent.metrics["failed_ingestions"] == 1
    assert len(index.upserted) >= 1
    events = _read_trace(tmp_path, "run-ingest-failure")
    failures = [event for event in events if event["event"] == "ingest_failed"]
    fetched = [event for event in events if event["event"] == "page_fetched"]
    assert len(failures) == 1
    assert failures[0]["payload"]["url"] == fail_url
    assert "retry exhaustion" in failures[0]["payload"]["error"]
    assert {event["payload"]["url"] for event in fetched} == {"https://example.com/1", "https://example.com/2"}


def test_analyst_returns_insufficient_evidence_when_all_ingestions_fail():
    class GlitchyEmbedder:
        def embed(self, texts):
            if any("glitch" in text for text in texts):
                raise ValueError("Compatible embedding call failed: retry exhaustion")
            return [[0.0] for _ in texts]

    class GlitchyFetcher:
        def fetch(self, url):
            return type("Document", (), {"source_id": url, "url": url, "title": "Source", "text": "glitch evidence", "published_at": None})()

    class Model:
        def complete(self, request):
            raise AssertionError("empty evidence must not synthesize")

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    index = FakeIndex(evidence=[])
    agent = AnalystAgent(model=Model(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=GlitchyFetcher(), index=index, embedder=GlitchyEmbedder(), planner=controlled_planner(plan))
    answer = asyncio.run(agent.run("Q", "run-all-ingest-failures"))

    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    assert "No retrieved evidence was available." in answer.limitations
    ingest_failures = [item for item in answer.limitations if item.startswith("Page content from ")]
    assert len(ingest_failures) == 2
    assert agent.metrics["failed_ingestions"] == 2
    assert index.upserted == []


def test_analyst_records_no_ingestion_failures_when_everything_succeeds(tmp_path):
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=FakeFetcher(), index=FakeIndex(), embedder=FakeEmbedder(),
                         planner=controlled_planner(plan), trace_writer=TraceWriter(tmp_path))
    answer = asyncio.run(agent.run("Q", "run-no-ingest-failures"))

    assert answer.answer == "Answer"
    assert answer.limitations == []
    assert agent.metrics["failed_ingestions"] == 0
    events = _read_trace(tmp_path, "run-no-ingest-failures")
    assert [event for event in events if event["event"] == "ingest_failed"] == []


def test_analyst_propagates_question_embedding_failure():
    question = "What happened to Acme?"

    class QuestionEmbedFailure:
        def embed(self, texts):
            if texts == [question]:
                raise ValueError("Compatible embedding call failed: retry exhaustion")
            return [[0.0] for _ in texts]

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=FakeSearcher(),
                         fetcher=FakeFetcher(), index=FakeIndex(), embedder=QuestionEmbedFailure(), planner=controlled_planner(plan))
    with pytest.raises(ValueError, match="retry exhaustion"):
        asyncio.run(agent.run(question, "run-question-embed-failure"))


# ---------------------------------------------------------------------------
# Auditor -> analyst feedback loop
#
# This mechanism shipped to main as dead code: the function that was supposed to
# suppress previously rejected claims was never called, and the list feeding it
# was built from `verified is True` — the auditor's *approved* claims. Wired up
# as written it would have suppressed the best claims. It had no tests at all.
# ---------------------------------------------------------------------------

_REJECTED_TEXT = "Acme opened 250 new stores in 2024."


class _MemoryWithVerdicts:
    def __init__(self, records):
        self._records = records

    def search_memory(self, query, limit=10):
        return list(self._records)


def _claim_record(text, verdict_status, verified=False):
    return MemoryRecord(
        id=f"claim::{text}", kind="claim", text=text, entity_ids=["e1"],
        source_ids=[], verified=verified, verdict_status=verdict_status,
    )


class _ModelReturning:
    """Model that always emits one claim with the given text."""

    def __init__(self, text):
        self.text = text
        self.system_prompts = []

    def complete(self, request):
        self.system_prompts.append(request.messages[0]["content"])
        answer = AnalystAnswer(
            answer="Answer",
            claims=[Claim(
                id="c1", text=self.text,
                citations=[Citation(url="https://example.com/1", title="Source",
                                    source_id="s1", chunk_id="c1")],
                confidence="high",
            )],
            limitations=[],
        )
        return type("Response", (), {"parsed": answer})()


def _agent_with(memory, model):
    return AnalystAgent(
        model=model, resolver=FakeResolver(), memory=memory, searcher=FakeSearcher(),
        fetcher=FakeFetcher(), index=FakeIndex(), embedder=FakeEmbedder(), max_subqueries=1,
    )


def test_claim_rejected_by_a_previous_audit_is_blocked_on_the_next_run():
    memory = _MemoryWithVerdicts([_claim_record(_REJECTED_TEXT, "unsupported")])
    agent = _agent_with(memory, _ModelReturning(_REJECTED_TEXT))

    result = asyncio.run(agent.run("How many stores did Acme open?", "run-fb-1"))

    assert result.claims == []
    assert any("earlier audit" in item for item in result.limitations), result.limitations
    assert agent.metrics["claims_blocked_by_audit_feedback"] == 1


def test_contradicted_claims_are_blocked_too():
    memory = _MemoryWithVerdicts([_claim_record(_REJECTED_TEXT, "contradicted")])
    agent = _agent_with(memory, _ModelReturning(_REJECTED_TEXT))

    result = asyncio.run(agent.run("How many stores did Acme open?", "run-fb-2"))

    assert result.claims == []


def test_a_paraphrase_of_a_rejected_claim_is_also_blocked():
    """Substring matching would miss this; fingerprint overlap catches it."""
    memory = _MemoryWithVerdicts([_claim_record(_REJECTED_TEXT, "unsupported")])
    agent = _agent_with(memory, _ModelReturning("In 2024, Acme opened 250 new stores."))

    result = asyncio.run(agent.run("How many stores did Acme open?", "run-fb-3"))

    assert result.claims == []


def test_a_previously_SUPPORTED_claim_is_not_blocked():
    """Regression guard for the inverted condition that shipped to main.

    The old code collected records with verified=True — which memory.py sets for
    *supported* verdicts — into `prior_rejected_claims`. If that inversion ever
    returns, this test fails.
    """
    memory = _MemoryWithVerdicts([_claim_record(_REJECTED_TEXT, "supported", verified=True)])
    agent = _agent_with(memory, _ModelReturning(_REJECTED_TEXT))

    result = asyncio.run(agent.run("How many stores did Acme open?", "run-fb-4"))

    assert [claim.text for claim in result.claims] == [_REJECTED_TEXT]
    assert agent.metrics["claims_blocked_by_audit_feedback"] == 0


def test_an_unaudited_claim_is_not_blocked():
    """verdict_status=None means never audited, which must not imply rejected."""
    memory = _MemoryWithVerdicts([_claim_record(_REJECTED_TEXT, None)])
    agent = _agent_with(memory, _ModelReturning(_REJECTED_TEXT))

    result = asyncio.run(agent.run("How many stores did Acme open?", "run-fb-5"))

    assert len(result.claims) == 1


def test_an_unrelated_claim_about_the_same_entity_is_not_suppressed():
    memory = _MemoryWithVerdicts([_claim_record(_REJECTED_TEXT, "unsupported")])
    agent = _agent_with(memory, _ModelReturning("Acme appointed a new chief financial officer."))

    result = asyncio.run(agent.run("Who is Acme's CFO?", "run-fb-6"))

    assert len(result.claims) == 1


def test_rejected_claims_are_named_in_the_system_prompt():
    memory = _MemoryWithVerdicts([_claim_record(_REJECTED_TEXT, "unsupported")])
    model = _ModelReturning("Acme appointed a new chief financial officer.")
    agent = _agent_with(memory, model)

    asyncio.run(agent.run("Who is Acme's CFO?", "run-fb-7"))

    assert _REJECTED_TEXT in model.system_prompts[0]
    assert "independent auditor" in model.system_prompts[0]


# ---------------------------------------------------------------------------
# Memory-first retrieval (cost reduction that transfers)
#
# The brief is explicit that caching an answer already seen does not count, and
# that only memory transferring to an unseen question does. These tests assert
# transfer: evidence indexed while answering one question suppresses web work on
# a *different* question about the same entity.
# ---------------------------------------------------------------------------

class CountingSearcher:
    def __init__(self):
        self.queries = []

    def search(self, query, limit=5):
        self.queries.append(query)
        return [SearchHit(url=f"https://example.com/{len(self.queries)}", title="Source",
                          snippet=query, published_at=None)]


class CountingFetcher:
    def __init__(self):
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return type("Document", (), {"source_id": url, "url": url, "title": "Source",
                                     "text": "evidence", "published_at": None})()


class StockedIndex:
    """Index that already holds evidence for an entity from prior questions."""

    def __init__(self, sources_for_entity=2, score=0.9):
        self.filters = []
        self.upserted = []
        self._evidence = [
            Evidence(chunk_id=f"c{i}", source_id=f"s{i}", url=f"https://example.com/prior{i}",
                     title="Prior", text="prior evidence", score=score, entity_ids=["e1"])
            for i in range(sources_for_entity)
        ]

    def upsert(self, chunks, vectors):
        self.upserted.extend(chunks)

    def hybrid_search(self, query, vector, filters, limit):
        self.filters.append(filters)
        return list(self._evidence)


def _reuse_agent(index, searcher, fetcher, plan, **kwargs):
    return AnalystAgent(
        model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(), searcher=searcher,
        fetcher=fetcher, index=index, embedder=FakeEmbedder(),
        planner=controlled_planner(plan), **kwargs,
    )


def _entity_plan(question="Q"):
    return ResearchPlan(
        original_question=question,
        subqueries=[{"query": f"Acme {question}", "entities": ["Acme"]}],
        entities=["Acme"], date_constraints=[],
    )


def test_evidence_from_earlier_questions_suppresses_search_and_fetch():
    searcher, fetcher = CountingSearcher(), CountingFetcher()
    agent = _reuse_agent(StockedIndex(sources_for_entity=2), searcher, fetcher, _entity_plan())

    asyncio.run(agent.run("Is Acme profitable?", "run-reuse-1"))

    assert searcher.queries == [], "web search ran despite sufficient indexed evidence"
    assert fetcher.urls == []
    assert agent.metrics["searches_skipped"] == 1
    assert agent.metrics["evidence_reused"] == 1


def test_a_single_prior_source_is_not_enough_to_skip():
    """One uncorroborated prior page is exactly the evidence the analyst distrusts.

    Reusing it would trade correctness for cost, which is not the deal.
    """
    searcher, fetcher = CountingSearcher(), CountingFetcher()
    agent = _reuse_agent(StockedIndex(sources_for_entity=1), searcher, fetcher, _entity_plan())

    asyncio.run(agent.run("Is Acme profitable?", "run-reuse-2"))

    assert len(searcher.queries) == 1
    assert agent.metrics["searches_skipped"] == 0


def test_an_unknown_entity_still_hits_the_web():
    """Reuse must not starve a genuinely novel question."""
    searcher, fetcher = CountingSearcher(), CountingFetcher()

    class UnresolvedResolver:
        def resolve(self, mention, context):
            return type("R", (), {"entity_id": None, "canonical_name": None, "status": "unknown"})()

    agent = AnalystAgent(
        model=FakeModel(), resolver=UnresolvedResolver(), memory=FakeMemory(), searcher=searcher,
        fetcher=fetcher, index=StockedIndex(), embedder=FakeEmbedder(),
        planner=controlled_planner(_entity_plan()),
    )
    asyncio.run(agent.run("Who founded Novel Corp?", "run-reuse-3"))

    assert len(searcher.queries) == 1


def test_reuse_can_be_disabled():
    searcher, fetcher = CountingSearcher(), CountingFetcher()
    agent = _reuse_agent(StockedIndex(), searcher, fetcher, _entity_plan(), reuse_enabled=False)

    asyncio.run(agent.run("Is Acme profitable?", "run-reuse-4"))

    assert len(searcher.queries) == 1


def test_reuse_that_underdelivers_triggers_a_course_correction():
    """Skipping a search is a bet. This is the path that pays it off when wrong."""

    class ProbeRichButEmptyIndex(StockedIndex):
        """Reports coverage on the per-entity probe, then returns nothing for the
        real retrieval — the shape of a stale or mis-filtered index.

        Discriminated by call order, not by the filter: with no date constraints
        the probe filter and the main retrieval filter are identical.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calls = 0

        def hybrid_search(self, query, vector, filters, limit):
            self.filters.append(filters)
            self.calls += 1
            if self.calls == 1:
                return list(self._evidence)      # per-entity coverage probe
            if self.calls == 2:
                return []                        # main retrieval finds nothing
            return list(self._evidence)          # retry after recovery

    searcher, fetcher = CountingSearcher(), CountingFetcher()
    index = ProbeRichButEmptyIndex(sources_for_entity=2)
    agent = _reuse_agent(index, searcher, fetcher, _entity_plan())

    asyncio.run(agent.run("Is Acme profitable?", "run-reuse-5"))

    assert agent.metrics["reuse_corrections"] == 1
    assert len(searcher.queries) == 1, "the skipped query was not re-run"
    assert agent.metrics["searches_skipped"] == 0, "a corrected skip must not be counted as a saving"


def test_the_reuse_decision_is_traced(tmp_path):
    searcher, fetcher = CountingSearcher(), CountingFetcher()
    writer = TraceWriter(root=tmp_path)
    agent = _reuse_agent(StockedIndex(), searcher, fetcher, _entity_plan(), trace_writer=writer)

    asyncio.run(agent.run("Is Acme profitable?", "run-reuse-6"))

    events = [json.loads(line) for line in
              (tmp_path / "logs" / "run-reuse-6.jsonl").read_text().splitlines() if line.strip()]
    reuse = [event for event in events if event["event"] == "memory_reuse_evaluated"]
    assert reuse, "the reuse decision was not traced"
    assert reuse[0]["payload"]["covered_entities"] == 1
    assert reuse[0]["payload"]["skipped_queries"]


class _KnownEntityMemory:
    """Minimal memory stub exposing only what content attribution needs."""

    def __init__(self, entities):
        self._entities = entities

    def known_entities(self):
        return list(self._entities)


def _attributor(entities):
    agent = AnalystAgent.__new__(AnalystAgent)
    agent.memory = _KnownEntityMemory(entities)
    return agent


def test_a_page_is_tagged_with_the_entity_it_discusses_not_the_one_that_found_it():
    """The whole point: attribution follows content, not the query.

    A page about Infosys found while answering a question that names no
    company must still be reusable by a later Infosys question.
    """
    agent = _attributor([("e-inf", "Infosys"), ("e-wip", "Wipro"), ("e-zep", "Zepto")])

    ids = agent._entity_ids_from_content(
        "Bengaluru's largest exporters are Infosys and Wipro, by revenue."
    )

    assert sorted(ids) == ["e-inf", "e-wip"], "page not attributed to the firms it is about"


def test_content_attribution_matches_whole_words_only():
    """Substring matching would tag every page mentioning 'winfosystems'."""
    agent = _attributor([("e-inf", "Infosys")])

    assert agent._entity_ids_from_content("Winfosystems Ltd filed its results.") == []
    assert agent._entity_ids_from_content("Infosys filed its results.") == ["e-inf"]


def test_content_attribution_is_case_insensitive_and_survives_punctuation():
    agent = _attributor([("e-zer", "Zerodha")])

    assert agent._entity_ids_from_content("(ZERODHA), the broker, said...") == ["e-zer"]


def test_content_attribution_degrades_quietly_when_memory_cannot_answer():
    """A tagging failure must never take down a research run."""

    class Broken:
        def known_entities(self):
            raise RuntimeError("db gone")

    agent = AnalystAgent.__new__(AnalystAgent)
    agent.memory = Broken()

    assert agent._entity_ids_from_content("Infosys") == []


# --- course corrections must be legible in the trace -----------------------
# The brief asks for "where it changed course after something failed". Each of
# these rejections is the analyst overruling its own model, and each used to be
# visible only as prose inside the answer's limitations.


def _trace_events(tmp_path, run_id, name):
    return [
        event for event in _read_trace(tmp_path, run_id) if event["event"] == name
    ]


def test_a_claim_with_no_citations_is_traced_as_a_rejection(tmp_path):
    class Uncited:
        def complete(self, request):
            return SimpleNamespace(
                parsed=AnalystAnswer(
                    answer="Answer",
                    claims=[Claim(id="c1", text="Acme is profitable.", citations=[])],
                ),
                input_tokens=1, output_tokens=1, estimated_cost=0.0,
            )

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=Uncited(), resolver=FakeResolver(), memory=FakeMemory(),
                         searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(),
                         embedder=FakeEmbedder(), planner=controlled_planner(plan),
                         trace_writer=TraceWriter(tmp_path))

    asyncio.run(agent.run("Q", "run-uncited"))

    rejections = _trace_events(tmp_path, "run-uncited", "claim_rejected")
    assert [event["payload"]["reason"] for event in rejections] == ["no_citations"]
    assert rejections[0]["payload"]["claim_id"] == "c1"


def test_a_citation_that_was_never_retrieved_is_traced_as_a_rejection(tmp_path):
    """The model citing a page the run never fetched is a fabrication risk."""

    class Fabricator:
        def complete(self, request):
            return SimpleNamespace(
                parsed=AnalystAnswer(
                    answer="Answer",
                    claims=[Claim(
                        id="c1", text="Acme is profitable.",
                        citations=[Citation(url="https://not-fetched.example/x",
                                            source_id="ghost", chunk_id=None, title="Ghost")],
                    )],
                ),
                input_tokens=1, output_tokens=1, estimated_cost=0.0,
            )

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=Fabricator(), resolver=FakeResolver(), memory=FakeMemory(),
                         searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(),
                         embedder=FakeEmbedder(), planner=controlled_planner(plan),
                         trace_writer=TraceWriter(tmp_path))

    asyncio.run(agent.run("Q", "run-ghost"))

    rejections = _trace_events(tmp_path, "run-ghost", "claim_rejected")
    assert [event["payload"]["reason"] for event in rejections] == ["citation_not_in_evidence"]
    assert rejections[0]["payload"]["unmapped_citations"] == ["https://not-fetched.example/x"]


def test_declining_to_answer_is_traced_as_a_decision(tmp_path):
    """"Not found" is a required behaviour, so it is recorded as a choice.

    Inferring it from an empty claim list would make it indistinguishable from
    a crash that happened to produce no claims.
    """

    class Uncited:
        def complete(self, request):
            return SimpleNamespace(
                parsed=AnalystAnswer(
                    answer="Answer",
                    claims=[Claim(id="c1", text="Acme is profitable.", citations=[])],
                ),
                input_tokens=1, output_tokens=1, estimated_cost=0.0,
            )

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=Uncited(), resolver=FakeResolver(), memory=FakeMemory(),
                         searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(),
                         embedder=FakeEmbedder(), planner=controlled_planner(plan),
                         trace_writer=TraceWriter(tmp_path))

    answer = asyncio.run(agent.run("Q", "run-withheld"))

    assert answer.answer == "Insufficient evidence."
    withheld = _trace_events(tmp_path, "run-withheld", "answer_withheld")
    assert withheld and withheld[0]["payload"]["reason"] == "no_claim_survived_validation"

    synthesized = _trace_events(tmp_path, "run-withheld", "answer_synthesized")
    assert synthesized[0]["payload"] == {
        "claims_proposed": 1, "claims_kept": 0, "claims_rejected": 1, "bailed_out": True,
    }


def test_a_model_that_proposes_nothing_is_traced_as_withheld(tmp_path):
    """Evidence was retrieved, and the model still found nothing to claim.

    This is the second of the three routes to "Insufficient evidence.", and it
    is the one the offline harness actually hits: evidence exists, but no
    sentence clears the extractive model's floor, so it proposes zero claims.
    Distinct from the uncited-claim case above -- there the model *did* propose
    and validation struck it -- so the reason string has to differ, otherwise a
    reader of the trace cannot tell "model found nothing" from "model guessed
    and we caught it".
    """

    class NothingUseful:
        """Stands in for the extractive offline model finding no usable sentence.

        The limitation is the model's own, and the analyst passes it through
        rather than inventing one -- which is the point: on this route the
        wording that reaches the user comes from the component that actually
        failed to find anything.
        """

        def complete(self, request):
            return SimpleNamespace(
                parsed=AnalystAnswer(answer="", claims=[],
                                     limitations=["No supplied evidence answered the question."]),
                input_tokens=1, output_tokens=1, estimated_cost=0.0,
            )

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q one"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=NothingUseful(), resolver=FakeResolver(), memory=FakeMemory(),
                         searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(),
                         embedder=FakeEmbedder(), planner=controlled_planner(plan),
                         trace_writer=TraceWriter(tmp_path))

    answer = asyncio.run(agent.run("Q", "run-no-claims"))

    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    assert "No supplied evidence answered the question." in answer.limitations

    withheld = _trace_events(tmp_path, "run-no-claims", "answer_withheld")
    assert withheld, "declining to answer must be traced, not inferred from an empty claim list"
    assert withheld[0]["payload"]["reason"] == "model_proposed_no_claims"

    # Evidence really was retrieved: this is not the empty-evidence early return.
    selected = _trace_events(tmp_path, "run-no-claims", "evidence_selected")
    assert selected and selected[0]["payload"]["count"] > 0

    synthesized = _trace_events(tmp_path, "run-no-claims", "answer_synthesized")
    assert synthesized[0]["payload"] == {
        "claims_proposed": 0, "claims_kept": 0, "claims_rejected": 0, "bailed_out": True,
    }


def test_the_empty_evidence_shortcut_is_not_traced_as_a_withheld_answer(tmp_path):
    """No evidence at all returns before the traced decision, and that is deliberate.

    Pins the asymmetry so it stays a documented choice rather than a silent gap.
    ``_synthesize`` returns early on ``not evidence``: there was no answer to
    decline, because there was nothing to answer from. Emitting
    ``answer_withheld`` there would claim a decision the agent never made, and
    would collapse the distinction between "retrieval found nothing" and "the
    model was shown evidence and could not use it" -- the two have different
    fixes. The limitation string carries the difference instead.
    """

    class Model:
        def complete(self, request):
            raise AssertionError("empty evidence must not synthesize")

    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=[])
    agent = AnalystAgent(model=Model(), resolver=FakeResolver(), memory=FakeMemory(),
                         searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(evidence=[]),
                         embedder=FakeEmbedder(), planner=controlled_planner(plan),
                         trace_writer=TraceWriter(tmp_path))

    answer = asyncio.run(agent.run("Q", "run-no-evidence"))

    assert answer.answer == "Insufficient evidence."
    assert answer.claims == []
    assert answer.limitations == ["No retrieved evidence was available."]

    # The model was never called (it would have raised), so nothing was weighed
    # and nothing was declined.
    assert _trace_events(tmp_path, "run-no-evidence", "answer_withheld") == []
    assert _trace_events(tmp_path, "run-no-evidence", "answer_synthesized") == []

    # Retrieval itself is still traced: the absence of evidence is recorded.
    selected = _trace_events(tmp_path, "run-no-evidence", "evidence_selected")
    assert selected and selected[0]["payload"]["count"] == 0


def test_the_plan_is_traced_before_any_search_happens(tmp_path):
    """"Plan before searching" is a stated requirement; the log must show it."""
    plan = ResearchPlan(
        original_question="Q", subqueries=[{"query": "Q one"}, {"query": "Q two"}],
        entities=["Acme"], date_constraints=["2024"],
    )
    agent = AnalystAgent(model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(),
                         searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(),
                         embedder=FakeEmbedder(), planner=controlled_planner(plan),
                         trace_writer=TraceWriter(tmp_path))

    asyncio.run(agent.run("Q", "run-plan"))

    events = _read_trace(tmp_path, "run-plan")
    names = [event["event"] for event in events]
    assert names.index("plan_created") < names.index("web_searched")

    payload = next(e["payload"] for e in events if e["event"] == "plan_created")
    assert payload["subqueries"] == ["Q one", "Q two"]
    assert payload["entities"] == ["Acme"]
    assert payload["date_constraints"] == ["2024"]


def test_an_accepted_cross_check_is_traced_with_its_confirming_source(tmp_path):
    """Accepted corroboration used to leave no event: 24 fetches per suite run
    with no record of what they confirmed. The trace must show the decision."""
    from dyla.tracing import TraceWriter

    model = _figure_claim_model()
    agent, fetcher = _agent_with_corroboration(model, _CorroborationSearcher(), fetcher_text=(
        "Acme opened 250 new stores in 2024, its annual report confirmed, taking the "
        "total past 1,000 nationwide."
    ))
    agent.fetcher = fetcher
    agent.trace_writer = TraceWriter(tmp_path)

    answer = asyncio.run(agent.run("Q", "run-corroborated-traced"))

    assert len(answer.claims) == 1
    events = _trace_events(tmp_path, "run-corroborated-traced", "claim_corroborated")
    assert len(events) == 1
    assert events[0]["payload"]["accepted"] is True
    assert events[0]["payload"]["source_url"]
    assert events[0]["payload"]["sources_checked"] >= 1


def test_a_rejected_cross_check_is_traced_before_the_rejection(tmp_path):
    """The rejection names the reason; the corroboration event names the work."""
    from dyla.tracing import TraceWriter

    model = _figure_claim_model()
    agent, fetcher = _agent_with_corroboration(model, _CorroborationSearcher(), fetcher_text=(
        "Acme opened fewer than 50 new stores in 2024 and closed several older ones."
    ))
    agent.fetcher = fetcher
    agent.trace_writer = TraceWriter(tmp_path)

    answer = asyncio.run(agent.run("Q", "run-uncorroborated-traced"))

    assert answer.claims == []
    corroborated = _trace_events(tmp_path, "run-uncorroborated-traced", "claim_corroborated")
    assert len(corroborated) == 1
    assert corroborated[0]["payload"]["accepted"] is False
    assert corroborated[0]["payload"]["source_url"] is None
    names = [event["event"] for event in _read_trace(tmp_path, "run-uncorroborated-traced")]
    assert names.index("claim_corroborated") < names.index("claim_rejected")


# ---------------------------------------------------------------------------
# Shadow policies (ADR-0001 increment 2)
#
# A candidate policy runs alongside the live one: decisions are traced under
# both, behaviour follows only the live policy, and no metric moves.
# ---------------------------------------------------------------------------

def _reuse_plan():
    return ResearchPlan(
        original_question="Q",
        subqueries=[{"query": "Acme status", "entities": ["Acme"]}],
        entities=["Acme"],
        date_constraints=[],
    )


def _shadow_agent(tmp_path, shadow_policies, reuse_enabled=True):
    writer = TraceWriter(root=tmp_path)
    return AnalystAgent(
        model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(),
        searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(),
        embedder=FakeEmbedder(), planner=controlled_planner(_reuse_plan()),
        trace_writer=writer, reuse_enabled=reuse_enabled,
        shadow_policies=shadow_policies,
    ), writer


def test_shadow_policies_change_no_behaviour():
    from dyla.policies import Policies

    plain_agent = AnalystAgent(
        model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(),
        searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(),
        embedder=FakeEmbedder(), planner=controlled_planner(_reuse_plan()),
    )
    shadow_agent, _ = _shadow_agent(Path("/tmp/dyla-shadow-unused"), Policies(reuse_min_sources=1))
    plain_answer = asyncio.run(plain_agent.run("Q", "run-shadow-off"))
    shadow_answer = asyncio.run(shadow_agent.run("Q", "run-shadow-on"))

    counters = ("searches", "fetches", "searches_skipped", "evidence_reused", "memory_hits")
    assert {key: plain_agent.metrics[key] for key in counters} == {key: shadow_agent.metrics[key] for key in counters}
    assert shadow_agent.metrics["searches_skipped"] == 0, "the shadow policy leaked into live behaviour"
    assert shadow_answer == plain_answer


def test_shadow_divergence_is_traced_without_changing_behaviour(tmp_path):
    from dyla.policies import Policies

    # Live policy requires 2 sources (the FakeIndex holds 1), so the subquery
    # runs. A shadow policy requiring 1 source would have skipped it: exactly
    # the divergence the event must record, while the search still happens.
    agent, writer = _shadow_agent(tmp_path, Policies(reuse_min_sources=1))
    asyncio.run(agent.run("Q", "run-shadow"))

    assert agent.metrics["searches"] == 1, "the shadow policy changed live behaviour"
    events = [json.loads(line) for line in (tmp_path / "logs" / "run-shadow.jsonl").read_text().splitlines()]
    shadows = [event["payload"] for event in events if event["event"] == "reuse_shadow_evaluated"]
    assert len(shadows) == 1
    assert shadows[0]["divergent"] is True
    assert shadows[0]["live"]["skipped_queries"] == []
    assert shadows[0]["shadow"]["skipped_queries"] == ["Acme status"]


def test_an_identical_shadow_policy_traces_agreement_not_divergence(tmp_path):
    from dyla.policies import Policies

    agent, writer = _shadow_agent(tmp_path, Policies())
    asyncio.run(agent.run("Q", "run-agree"))

    events = [json.loads(line) for line in (tmp_path / "logs" / "run-agree.jsonl").read_text().splitlines()]
    shadows = [event["payload"] for event in events if event["event"] == "reuse_shadow_evaluated"]
    assert len(shadows) == 1
    assert shadows[0]["divergent"] is False
    assert shadows[0]["shadow"]["reuse_min_sources"] == shadows[0]["live"]["reuse_min_sources"]


def test_the_shadow_event_is_on_the_trace_validator_allowlist(tmp_path):
    """The allowlist is a manual-sync coupling; a new event that isn't added
    turns every run 'incomplete'. This runs the gate itself."""
    from dyla.policies import Policies
    from dyla.reliability import QualityGate

    agent, _ = _shadow_agent(tmp_path, Policies(reuse_min_sources=1))
    asyncio.run(agent.run("Q", "run-allowlist"))

    issues: set[str] = set()
    QualityGate._validate_trace(tmp_path / "logs" / "run-allowlist.jsonl", "run-allowlist", issues)
    assert not any("unknown event" in issue for issue in issues), issues


def test_a_budget_exhausted_search_is_not_reported_as_a_provider_failure(tmp_path):
    """The budget wrapper's ValueError reaching the gather path must surface as
    'budget was exhausted', not as 'Web search failed' — and must not count
    against failed_searches."""
    from dyla.policies import Policies

    class BudgetedSearcher(FakeSearcher):
        def __init__(self, free_calls):
            super().__init__()
            self.free_calls = free_calls

        def search(self, query, limit=5):
            if self.started >= self.free_calls:
                raise ValueError("web request budget exceeded")
            return super().search(query, limit)

    searcher = BudgetedSearcher(free_calls=1)
    plan = ResearchPlan(
        original_question="Q",
        subqueries=[{"query": f"Acme {i}"} for i in range(3)],
        entities=[],
        date_constraints=[],
    )
    agent = AnalystAgent(
        model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(),
        searcher=searcher, fetcher=FakeFetcher(), index=FakeIndex(),
        embedder=FakeEmbedder(), planner=controlled_planner(plan),
        trace_writer=TraceWriter(root=tmp_path), reuse_enabled=False,
        policies=Policies(),
    )
    answer = asyncio.run(agent.run("Q", "run-budget"))

    assert any("web-request budget was exhausted" in limitation for limitation in answer.limitations), (
        answer.limitations
    )
    assert not any("Web search failed for query" in limitation for limitation in answer.limitations), (
        answer.limitations
    )
    assert agent.metrics["failed_searches"] == 0, "a budget stop counted as a provider failure"


def test_a_disabled_shadow_policy_never_reports_skipped_queries(tmp_path):
    from dyla.policies import Policies

    # Two sources so the live policy (min 2) covers the entity and skips the
    # subquery; the shadow policy disables reuse entirely, so it must report
    # zero skipped queries — a policy that never skips anything.
    evidence = [
        Evidence(chunk_id=f"c{i}", source_id=f"s{i}", url=f"https://example.com/{i}",
                 title="Source", text="evidence", score=0.9, entity_ids=["e1"])
        for i in range(2)
    ]
    agent = AnalystAgent(
        model=FakeModel(), resolver=FakeResolver(), memory=FakeMemory(),
        searcher=FakeSearcher(), fetcher=FakeFetcher(), index=FakeIndex(evidence=evidence),
        embedder=FakeEmbedder(), planner=controlled_planner(_reuse_plan()),
        trace_writer=TraceWriter(root=tmp_path),
        shadow_policies=Policies(reuse_enabled=False),
    )
    asyncio.run(agent.run("Q", "run-shadow-off"))

    events = [json.loads(line) for line in (tmp_path / "logs" / "run-shadow-off.jsonl").read_text().splitlines()]
    shadows = [event["payload"] for event in events if event["event"] == "reuse_shadow_evaluated"]
    assert len(shadows) == 1
    assert shadows[0]["shadow"]["skipped_queries"] == []
    assert shadows[0]["shadow"]["covered_entities"] == 0
    assert shadows[0]["divergent"] is True, "live skipped, the disabled shadow would not"
