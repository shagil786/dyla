from pathlib import Path

from dyla.auditor import AuditorAgent
from dyla.domain import AnalystAnswer, Citation, Claim, Document


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
