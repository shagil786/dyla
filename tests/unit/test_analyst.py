import asyncio
import threading
import time
from datetime import UTC, datetime

from dyla.analyst import AnalystAgent
from dyla.domain import AnalystAnswer, Citation, Claim, Evidence, MemoryRecord, ResearchPlan, SearchHit


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


def test_analyst_reports_unsupported_non_year_date_constraint():
    plan = ResearchPlan(original_question="Q", subqueries=[{"query": "Q"}], entities=[], date_constraints=["March 2025"])
    answer = asyncio.run(make_agent(FakeModel(), plan, FakeIndex(evidence=[])).run("Q", "run-date"))
    assert answer.answer == "Insufficient evidence."
    assert any("date" in limitation.lower() for limitation in answer.limitations)


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
