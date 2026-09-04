import asyncio
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
    assert "Date filter applied for 2025; sources without a published date were also considered." in answer.limitations


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
    assert index.filters[0].entity_ids == ["e1", "e2"]
    assert index.filters[0].published_after == datetime(2025, 1, 1, tzinfo=UTC)
    assert index.filters[0].published_before == datetime(2026, 1, 1, tzinfo=UTC)


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
    assert [(event["component"], event["event"]) for event in events] == [
        ("analyst", "memory_retrieved"),
        ("analyst", "web_searched"),
        ("analyst", "web_searched"),
        ("analyst", "page_fetched"),
        ("analyst", "page_fetched"),
        ("analyst", "evidence_selected"),
    ]
    assert events[0]["payload"] == {"count": 1}
    assert events[1]["payload"] == {"query": "Q one", "results": 1}
    assert events[2]["payload"] == {"query": "Q two", "results": 1}
    assert sorted(
        (event["payload"] for event in events if event["event"] == "page_fetched"),
        key=lambda item: item["url"],
    ) == [
        {"url": "https://example.com/1", "chars": len("evidence")},
        {"url": "https://example.com/2", "chars": len("evidence")},
    ]
    assert events[-1]["payload"] == {"count": 1}
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
    assert events[-1]["event"] == "evidence_selected"


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
