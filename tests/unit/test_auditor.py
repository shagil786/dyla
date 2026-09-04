import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from dyla.auditor import AuditorAgent, ModelComparator
from dyla.compatible import CompatibleModelProvider
from dyla.domain import AnalystAnswer, Citation, Claim, Document
from dyla.models import ModelResponse


def citation(url="https://example.com/source", source_id="source-1"):
    return Citation(url=url, title="Source", source_id=source_id, chunk_id="chunk-1")


def answer_with(*claims):
    return AnalystAnswer(answer="Answer", claims=list(claims), limitations=[])


class FakeFetcher:
    def __init__(self, documents=None, failures=None):
        self.documents = documents or {}
        self.failures = failures or set()
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        if url in self.failures:
            raise OSError("fetch failed")
        return self.documents[url]


class FakeComparator:
    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = []

    def compare(self, claim, documents):
        self.calls.append((claim.id, sorted(documents)))
        return self.statuses[claim.id], f"comparison for {claim.id}"


class FakeMemory:
    def __init__(self):
        self.claims = []
        self.warnings = []

    def save_claim(self, claim, verdict):
        self.claims.append((claim.id, verdict.status if verdict else None))

    def save_research_warning(self, warning):
        self.warnings.append(warning)


class FakeTrace:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def test_auditor_compares_each_claim_against_independently_fetched_sources():
    c1, c2 = citation(), citation("https://example.com/other", "source-2")
    claims = [
        Claim(id="supported", text="supported", citations=[c1], confidence="high"),
        Claim(id="unsupported", text="unsupported", citations=[c2], confidence="high"),
    ]
    fetcher = FakeFetcher({c1.url: Document(source_id="s1", url=c1.url, title="Source", text="source", published_at=None), c2.url: Document(source_id="s2", url=c2.url, title="Other", text="other", published_at=None)})
    comparator = FakeComparator({"supported": "supported", "unsupported": "unsupported"})

    verdicts = AuditorAgent(fetcher=fetcher, comparator=comparator).run(answer_with(*claims), "run-1")

    assert [verdict.status for verdict in verdicts] == ["supported", "unsupported"]
    assert fetcher.calls == [c1.url, c2.url]
    assert comparator.calls == [("supported", [c1.url]), ("unsupported", [c2.url])]


def test_auditor_emits_contradicted_and_uncited_verdicts_and_persists_them():
    contradicted = Claim(id="contradicted", text="wrong", citations=[citation()], confidence="high")
    uncited = Claim(id="uncited", text="no source", citations=[], confidence="high")
    url = contradicted.citations[0].url
    memory = FakeMemory()
    fetcher = FakeFetcher({url: Document(source_id="s1", url=url, title="Source", text="source", published_at=None)})
    comparator = FakeComparator({"contradicted": "contradicted"})

    verdicts = AuditorAgent(fetcher=fetcher, comparator=comparator, memory=memory).run(
        answer_with(contradicted, uncited), "run-2"
    )

    assert [verdict.status for verdict in verdicts] == ["contradicted", "uncited"]
    assert [item[0] for item in memory.claims] == ["contradicted", "uncited"]
    assert verdicts[1].citations_checked == []


def test_auditor_fetch_failure_is_a_deterministic_unsupported_verdict_and_warning():
    claim = Claim(id="failed", text="claim", citations=[citation()], confidence="high")
    memory = FakeMemory()

    verdicts = AuditorAgent(fetcher=FakeFetcher(failures={claim.citations[0].url}), comparator=FakeComparator({}), memory=memory).run(
        answer_with(claim), "run-3"
    )

    assert verdicts[0].status == "unsupported"
    assert "fetch" in verdicts[0].explanation.lower()
    assert memory.warnings == ["run-3: failed: source fetch failed"]


def test_auditor_preserves_partial_verdicts_and_reports_late_failure():
    class BrokenComparator:
        def compare(self, claim, documents):
            if claim.id == "second":
                raise RuntimeError("comparator down")
            return "supported", "checked"

    first = Claim(id="first", text="claim", citations=[citation()], confidence="high")
    second = Claim(id="second", text="claim", citations=[citation("https://example.com/second")], confidence="high")
    fetcher = FakeFetcher({
        citation().url: Document(source_id="s1", url=citation().url, title="Source", text="source", published_at=None),
        second.citations[0].url: Document(source_id="s2", url=second.citations[0].url, title="Source", text="source", published_at=None),
    })

    agent = AuditorAgent(fetcher=fetcher, comparator=BrokenComparator())
    verdicts = agent.run(answer_with(first, second), "run-partial")

    assert [item.claim_id for item in verdicts] == ["first"]
    assert agent.audit_state.status == "partial"
    assert agent.audit_state.issues == ["run-partial: auditor failed: comparator down"]


def test_auditor_resets_state_between_reused_runs():
    class FailsOnceComparator:
        def __init__(self):
            self.failed = False

        def compare(self, claim, documents):
            if not self.failed:
                self.failed = True
                raise RuntimeError("temporary comparator failure")
            return "supported", "checked"

    claim = Claim(id="reused", text="claim", citations=[citation()], confidence="high")
    document = Document(source_id="s1", url=claim.citations[0].url, title="Source", text="source", published_at=None)
    agent = AuditorAgent(
        fetcher=FakeFetcher({claim.citations[0].url: document}),
        comparator=FailsOnceComparator(),
    )

    first = agent.run(answer_with(claim), "run-first")
    second = agent.run(answer_with(claim), "run-second")

    assert first == []
    assert agent.audit_state.status == "complete"
    assert agent.audit_state.issues == []
    assert second[0].status == "supported"


def test_auditor_reports_persistence_and_trace_failures_in_audit_state():
    class BrokenMemory(FakeMemory):
        def save_claim(self, claim, verdict):
            raise OSError("database down")

    class BrokenTrace:
        def append(self, event):
            raise OSError("trace down")

    claim = Claim(id="c1", text="claim", citations=[], confidence="high")
    agent = AuditorAgent(fetcher=FakeFetcher(), memory=BrokenMemory(), trace_writer=BrokenTrace())

    verdicts = agent.run(answer_with(claim), "run-failures")

    assert len(verdicts) == 1
    assert agent.audit_state.status == "partial"
    assert agent.audit_state.issues == [
        "run-failures: c1: memory persistence failed: database down",
        "run-failures: claim_audited tracing failed: trace down",
    ]


def test_auditor_failure_persists_warning_and_returns_no_verdicts():
    class BrokenComparator:
        def compare(self, claim, documents):
            raise RuntimeError("comparator down")

    claim = Claim(id="broken", text="claim", citations=[citation() ], confidence="high")
    memory = FakeMemory()
    url = claim.citations[0].url
    fetcher = FakeFetcher({url: Document(source_id="s1", url=url, title="Source", text="source", published_at=None)})

    verdicts = AuditorAgent(fetcher=fetcher, comparator=BrokenComparator(), memory=memory).run(answer_with(claim), "run-4")

    assert verdicts == []
    assert memory.warnings == ["run-4: auditor failed: comparator down"]


def test_auditor_comparator_timeout_records_descriptive_issue():
    class SlowComparator:
        def compare(self, claim, documents):
            time.sleep(0.5)
            return "supported", "checked"

    claim = Claim(id="slow", text="claim", citations=[citation()], confidence="high")
    url = claim.citations[0].url
    fetcher = FakeFetcher({url: Document(source_id="s1", url=url, title="Source", text="source", published_at=None)})
    agent = AuditorAgent(fetcher=fetcher, comparator=SlowComparator(), timeout_seconds=0.05)

    verdicts = agent.run(answer_with(claim), "run-timeout")

    assert verdicts == []
    assert agent.audit_state.status in {"failed", "partial"}
    assert any("comparator did not finish within" in issue for issue in agent.audit_state.issues)


def test_auditor_retries_fetch_with_a_bounded_attempt_count():
    class EventuallyWorks:
        def __init__(self):
            self.calls = 0

        def fetch(self, url):
            self.calls += 1
            if self.calls < 3:
                raise OSError("temporary")
            return Document(source_id="s1", url=url, title="Source", text="source", published_at=None)

    claim = Claim(id="retry", text="claim", citations=[citation()], confidence="high")
    fetcher = EventuallyWorks()
    comparator = FakeComparator({"retry": "supported"})

    verdicts = AuditorAgent(fetcher=fetcher, comparator=comparator, retries=2).run(answer_with(claim), "run-5")

    assert verdicts[0].status == "supported"
    assert fetcher.calls == 3


def chat_response(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})


def comparator_claim(url):
    return Claim(id="c1", text="Water boils at 100C at sea level.", citations=[citation(url)], confidence="high")


def test_model_comparator_parses_valid_json_verdict_from_mocked_transport():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return chat_response(json.dumps({"status": "supported", "explanation": "The claim matches the source."}))

    provider = CompatibleModelProvider("https://host.example/v1", "fake-key", "judge", transport=httpx.MockTransport(handler))
    comparator = ModelComparator(provider)
    url = citation().url
    claim = comparator_claim(url)
    document = Document(source_id="s1", url=url, title="Physics", text="Water boils at 100C at sea level.", published_at=None)

    result = comparator.compare(claim, {url: document})

    assert result == ("supported", "The claim matches the source.")
    payload = requests[0]
    assert payload["model"] == "judge"
    assert payload["max_tokens"] == 300
    assert payload["temperature"] == 0
    assert payload["response_format"]["json_schema"]["name"] == "AuditorVerdictModel"
    system, user = payload["messages"][0]["content"], payload["messages"][-1]["content"]
    assert "json" in system.casefold()
    for expected in ("supported", "unsupported", "contradicted", "uncited"):
        assert expected in system
    assert claim.text in user
    assert url in user
    assert document.title in user


def test_model_comparator_bounds_document_excerpts_and_total_prompt():
    captured = []

    class CapturingProvider:
        def complete(self, request):
            captured.append(request)
            return ModelResponse(text="", parsed=SimpleNamespace(status="uncited", explanation="not addressed"), input_tokens=0, output_tokens=0, latency_ms=0)

    comparator = ModelComparator(CapturingProvider())
    url = citation().url
    claim = comparator_claim(url)
    long_document = Document(source_id="s1", url=url, title="Source", text="x" * 9000, published_at=None)

    status, explanation = comparator.compare(claim, {url: long_document})

    assert (status, explanation) == ("uncited", "not addressed")
    user_prompt = captured[0].messages[-1]["content"]
    assert "x" * 4001 not in user_prompt
    assert len(user_prompt) <= 24000


def test_model_comparator_raises_value_error_on_invalid_status_output():
    class LooseProvider:
        def complete(self, request):
            parsed = SimpleNamespace(status="  MAYBE  ", explanation="unclear")
            return ModelResponse(text='{"status": "maybe", "explanation": "unclear"}', parsed=parsed, input_tokens=0, output_tokens=0, latency_ms=0)

    comparator = ModelComparator(LooseProvider())
    url = citation().url
    claim = comparator_claim(url)
    document = Document(source_id="s1", url=url, title="Source", text="text", published_at=None)

    with pytest.raises(ValueError, match="invalid audit status"):
        comparator.compare(claim, {url: document})


def test_model_comparator_raises_value_error_when_provider_returns_no_verdict():
    class EmptyProvider:
        def complete(self, request):
            return ModelResponse(text="", parsed=None, input_tokens=0, output_tokens=0, latency_ms=0)

    comparator = ModelComparator(EmptyProvider())
    url = citation().url
    claim = comparator_claim(url)
    document = Document(source_id="s1", url=url, title="Source", text="text", published_at=None)

    with pytest.raises(ValueError, match="no structured verdict"):
        comparator.compare(claim, {url: document})


def test_auditor_run_with_model_comparator_produces_verdicts_and_no_issues():
    def handler(request):
        return chat_response(json.dumps({"status": "contradicted", "explanation": "The source states the opposite."}))

    provider = CompatibleModelProvider("https://host.example/v1", "fake-key", "judge", transport=httpx.MockTransport(handler))
    url = citation().url
    claim = comparator_claim(url)
    document = Document(source_id="s1", url=url, title="Source", text="the opposite of the claim", published_at=None)
    memory = FakeMemory()
    trace = FakeTrace()
    agent = AuditorAgent(fetcher=FakeFetcher({url: document}), comparator=ModelComparator(provider), memory=memory, trace_writer=trace)

    verdicts = agent.run(answer_with(claim), "run-model")

    assert [verdict.status for verdict in verdicts] == ["contradicted"]
    assert verdicts[0].explanation == "The source states the opposite."
    assert verdicts[0].citations_checked == [citation()]
    assert agent.audit_state.status == "complete"
    assert agent.audit_state.issues == []
    assert [(event.event, event.payload.get("status")) for event in trace.events] == [
        ("source_fetched", None),
        ("claim_audited", "contradicted"),
    ]
    assert memory.claims == [("c1", "contradicted")]
