import asyncio
from pathlib import Path

from dyla.domain import AnalystAnswer, AuditVerdict, Claim
from dyla.orchestrator import RunOrchestrator


class FakeAnalyst:
    def __init__(self, events):
        self.events = events
        self.metrics = {
            "input_tokens": 11, "output_tokens": 7, "estimated_cost": 0.25,
            "duration_ms": 12, "searches": 2, "fetches": 3,
            "memory_hits": 4, "parallel_calls": 5,
        }

    async def run(self, question, run_id):
        self.events.append("analyst")
        return AnalystAnswer(
            answer="answer",
            claims=[Claim(id="c1", text="fact", citations=[], confidence="high")],
            limitations=[],
        )


class FakeAuditor:
    def __init__(self, events):
        self.events = events

    def run(self, answer, run_id):
        self.events.append("auditor")
        return [AuditVerdict(claim_id="c1", status="uncited", explanation="no citation", citations_checked=[])]


class FakeMemory:
    def __init__(self, events):
        self.events = events
        self.initialized = False
        self.records = []

    def initialize(self):
        self.initialized = True

    def save_claim(self, claim, verdict):
        self.events.append("memory")
        self.records.append((claim.id, verdict.status))


class FakeTrace:
    def __init__(self, root, events):
        self.root = Path(root)
        self.events = events

    def append(self, event):
        self.events.append("trace")
        path = self.root / "logs" / f"{event.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("trace\n")


def test_ask_runs_analyst_auditor_memory_trace_quality_in_order(tmp_path):
    events = []
    memory = FakeMemory(events)
    result = asyncio.run(RunOrchestrator(
        analyst=FakeAnalyst(events), auditor=FakeAuditor(events), memory=memory,
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
    ).ask("question"))

    # Stages now run through AgentRuntime, which traces "started"/"completed"
    # around each one, so the raw event list interleaves extra trace entries.
    # Assert the relative order of the meaningful stages instead of an exact
    # prefix; the richer tracing is the point, not a regression.
    assert [item for item in events if item != "trace"] == ["analyst", "auditor", "memory"]
    assert events.count("trace") >= 2
    assert result.answer.answer == "answer"
    assert result.quality.status == "incomplete"
    assert result.run_id


def test_orchestrator_aggregates_stage_metrics(tmp_path):
    events = []

    class MetricsAnalyst(FakeAnalyst):
        def __init__(self, events):
            super().__init__(events)
            self.metrics: dict[str, int | float] = {field: 0 for field in self.metrics}

        async def run(self, question, run_id):
            self.metrics.update({
                "input_tokens": 11, "output_tokens": 7, "estimated_cost": 0.25,
                "duration_ms": 12, "searches": 2, "fetches": 3,
                "memory_hits": 4, "parallel_calls": 5,
            })
            return await super().run(question, run_id)

    class MetricsAuditor(FakeAuditor):
        def __init__(self, events):
            super().__init__(events)
            self.metrics: dict[str, int | float] = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0,
                            "duration_ms": 0, "searches": 0, "fetches": 0,
                            "memory_hits": 0, "parallel_calls": 0}

        def run(self, answer, run_id):
            self.metrics.update({
                "input_tokens": 13, "output_tokens": 17, "estimated_cost": 0.75,
                "duration_ms": 8, "searches": 1, "fetches": 2,
                "memory_hits": 1, "parallel_calls": 2,
            })
            return super().run(answer, run_id)

    result = asyncio.run(RunOrchestrator(
        analyst=MetricsAnalyst(events), auditor=MetricsAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
    ).ask("question"))

    assert result.metrics.input_tokens == 24
    assert result.metrics.output_tokens == 24
    assert result.metrics.estimated_cost == 1.0
    assert result.metrics.searches == 3
    assert result.metrics.fetches == 5
    assert result.metrics.memory_hits == 5
    assert result.metrics.parallel_calls == 7
    assert result.metrics.duration_ms >= 0


def test_reused_orchestrator_reports_metrics_per_run(tmp_path):
    events = []

    class ReusedAnalyst(FakeAnalyst):
        def __init__(self, events):
            super().__init__(events)
            self.metrics: dict[str, int | float] = {field: 0 for field in self.metrics}

        async def run(self, question, run_id):
            self.metrics["input_tokens"] += 10
            self.metrics["searches"] += 1
            return await super().run(question, run_id)

    class ReusedAuditor(FakeAuditor):
        def __init__(self, events):
            super().__init__(events)

            self.metrics: dict[str, int | float] = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0,
                            "duration_ms": 0, "searches": 0, "fetches": 0,
                            "memory_hits": 0, "parallel_calls": 0}

        def run(self, answer, run_id):
            self.metrics["fetches"] += 2
            return super().run(answer, run_id)

    analyst = ReusedAnalyst(events)
    auditor = ReusedAuditor(events)
    orchestrator = RunOrchestrator(
        analyst=analyst, auditor=auditor, memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
    )
    first = asyncio.run(orchestrator.ask("first"))
    second = asyncio.run(orchestrator.ask("second"))

    # duration_ms is wall-clock and is deliberately excluded: comparing it for
    # exact equality only passed while both runs happened to round to 0 ms, so
    # any added work in the run path broke it. The property under test is that
    # counters are per-run rather than cumulative.
    counters = lambda metrics: metrics.model_dump(exclude={"duration_ms"})
    assert counters(first.metrics) == counters(second.metrics)
    assert first.metrics.duration_ms >= 0
    assert first.metrics.input_tokens == 10
    assert first.metrics.searches == 1
    assert first.metrics.fetches == 2


def test_reset_style_component_metrics_never_become_negative(tmp_path):
    events = []

    class ResetAnalyst(FakeAnalyst):
        def __init__(self, events):
            super().__init__(events)
            self.metrics["input_tokens"] = 10

        async def run(self, question, run_id):
            self.metrics["input_tokens"] = 2
            return await super().run(question, run_id)

    class ResetAuditor(FakeAuditor):
        def __init__(self, events):
            super().__init__(events)
            self.metrics = {"fetches": 5}

        def run(self, answer, run_id):
            self.metrics["fetches"] = 1
            return super().run(answer, run_id)

    result = asyncio.run(RunOrchestrator(
        analyst=ResetAnalyst(events), auditor=ResetAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
    ).ask("question"))

    assert result.metrics.input_tokens == 2
    assert result.metrics.fetches == 1
    assert all(value >= 0 for value in result.metrics.model_dump().values())


def test_orchestrator_preserves_analyst_claims_when_audit_is_incomplete(tmp_path):
    events = []
    answer = AnalystAnswer(answer="original", claims=[], limitations=[])

    class Analyst:
        async def run(self, question, run_id):
            return answer

    class Auditor:
        def run(self, answer, run_id):
            return []

    result = asyncio.run(RunOrchestrator(
        analyst=Analyst(), auditor=Auditor(), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
    ).ask("question"))

    assert result.answer is answer
    assert result.quality.status == "unaudited"


# ---------------------------------------------------------------------------
# Wall-clock ceiling
#
# The previous implementation compared elapsed time against 120s *after* each
# stage had already returned and appended a note. Nothing was cancelled, so the
# ceiling measured overruns instead of preventing them. These tests assert the
# run actually stops.
# ---------------------------------------------------------------------------

class SlowAnalyst(FakeAnalyst):
    def __init__(self, events, delay):
        super().__init__(events)
        self.delay = delay
        self.completed = False

    async def run(self, question, run_id):
        await asyncio.sleep(self.delay)
        self.completed = True
        return await super().run(question, run_id)


class SlowAuditor(FakeAuditor):
    def __init__(self, events, delay):
        super().__init__(events)
        self.delay = delay

    def run(self, answer, run_id):
        import time as _time
        _time.sleep(self.delay)
        return super().run(answer, run_id)


def test_a_slow_analyst_is_cancelled_at_the_ceiling_not_merely_reported(tmp_path):
    import time as _time

    events = []
    analyst = SlowAnalyst(events, delay=5.0)
    started = _time.monotonic()
    result = asyncio.run(RunOrchestrator(
        analyst=analyst, auditor=FakeAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
        wall_clock_seconds=0.25,
    ).ask("question"))
    elapsed = _time.monotonic() - started

    assert elapsed < 3.0, f"orchestrator waited {elapsed:.2f}s despite a 0.25s ceiling"
    assert not analyst.completed, "the analyst coroutine was not cancelled"
    assert "analyst" not in events
    assert any("wall-clock" in issue for issue in result.quality.issues), result.quality.issues


def test_the_analyst_answer_survives_an_auditor_that_overruns(tmp_path):
    """A slow auditor must not destroy the work the analyst already did."""
    events = []
    result = asyncio.run(RunOrchestrator(
        analyst=FakeAnalyst(events), auditor=SlowAuditor(events, delay=2.0),
        memory=FakeMemory(events), trace_writer=FakeTrace(tmp_path, events),
        quality_gate=None, wall_clock_seconds=0.3,
    ).ask("question"))

    assert result.answer.answer == "answer"
    assert result.verdicts == []
    assert result.quality.status in {"unaudited", "incomplete"}
    assert any("wall-clock" in issue for issue in result.quality.issues), result.quality.issues


def test_the_budget_shrinks_across_stages(tmp_path):
    """Analyst and auditor share one ceiling; they cannot each consume the full one."""
    import time as _time

    events = []
    started = _time.monotonic()
    asyncio.run(RunOrchestrator(
        analyst=SlowAnalyst(events, delay=0.4), auditor=SlowAuditor(events, delay=5.0),
        memory=FakeMemory(events), trace_writer=FakeTrace(tmp_path, events),
        quality_gate=None, wall_clock_seconds=0.6,
    ).ask("question"))
    elapsed = _time.monotonic() - started

    # Analyst consumes 0.4s of the 0.6s ceiling, leaving the auditor ~0.2s of a
    # 5s job. Without a shrinking budget the auditor would get a fresh 0.6s.
    assert elapsed < 2.0, f"combined stages ran {elapsed:.2f}s against a 0.6s ceiling"


def test_a_normal_run_is_unaffected_by_the_ceiling(tmp_path):
    events = []
    result = asyncio.run(RunOrchestrator(
        analyst=FakeAnalyst(events), auditor=FakeAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
    ).ask("question"))

    assert result.answer.answer == "answer"
    assert len(result.verdicts) == 1
    assert not any("wall-clock" in issue for issue in result.quality.issues)


def test_orchestrator_persists_run_namespaced_claim_ids(tmp_path):
    """The orchestrator's memory write must use the same namespaced key as the
    auditor's, or the two writes diverge and cross-run history is lost."""
    events = []
    memory = FakeMemory(events)
    result = asyncio.run(RunOrchestrator(
        analyst=FakeAnalyst(events), auditor=FakeAuditor(events), memory=memory,
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
    ).ask("question"))

    assert memory.records == [(f"{result.run_id}:c1", "uncited")]


# ---------------------------------------------------------------------------
# Web-request budget
#
# The analyst holds its own searcher/fetcher and bypasses the ToolRegistry
# whose guarded handlers were the only place before_web_request fired, so
# max_web_requests was decorative on the stage making the most web calls.
# ---------------------------------------------------------------------------

class CountingSearcher:
    def __init__(self):
        self.searches = 0

    def search(self, query, limit=5):
        self.searches += 1
        return []

    def fetch(self, url):
        raise AssertionError("fetch not expected in this test")


class SearchingAnalyst(FakeAnalyst):
    def __init__(self, events, searcher):
        super().__init__(events)
        self.searcher = searcher

    async def run(self, question, run_id):
        for _ in range(5):
            self.searcher.search(question, 5)
        return await super().run(question, run_id)


def test_the_web_request_budget_counts_the_analyst_own_providers(tmp_path):
    events = []
    searcher = CountingSearcher()
    analyst = SearchingAnalyst(events, searcher)
    result = asyncio.run(RunOrchestrator(
        analyst=analyst, auditor=FakeAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
        max_web_requests=2, wall_clock_seconds=2.0,
    ).ask("question"))

    assert searcher.searches == 2, "the web budget did not stop the analyst's own searcher"
    assert any("web request budget exceeded" in issue for issue in result.quality.issues), (
        result.quality.issues
    )
    assert not any("wall-clock" in issue for issue in result.quality.issues), (
        "a budget breach was misreported as a wall-clock overrun"
    )
    # The provider is restored after the run, not left wrapped.
    assert analyst.searcher is searcher


class CountingFetcher:
    def __init__(self):
        self.fetches = 0

    def search(self, query, limit=5):
        raise AssertionError("search not expected in this test")

    def fetch(self, url):
        self.fetches += 1
        return object()


def test_the_auditor_fetcher_is_also_budgeted(tmp_path):
    events = []

    class FetchingAuditor(FakeAuditor):
        def __init__(self, events, fetcher):
            super().__init__(events)
            self.fetcher = fetcher

        def run(self, answer, run_id):
            for index in range(4):
                self.fetcher.fetch(f"https://example.com/{index}")
            return super().run(answer, run_id)

    fetcher = CountingFetcher()
    result = asyncio.run(RunOrchestrator(
        analyst=FakeAnalyst(events), auditor=FetchingAuditor(events, fetcher),
        memory=FakeMemory(events), trace_writer=FakeTrace(tmp_path, events),
        quality_gate=None, max_web_requests=1, wall_clock_seconds=2.0,
    ).ask("question"))

    assert fetcher.fetches == 1, "the web budget did not stop the auditor's fetcher"
    assert any("web request budget exceeded" in issue for issue in result.quality.issues), (
        result.quality.issues
    )


# ---------------------------------------------------------------------------
# Blocking analyst work
#
# The analyst's blocking work runs via asyncio.to_thread, which wait_for cannot
# stop and whose executor asyncio.run joins at shutdown. The stage therefore
# runs on its own daemon-threaded loop, the same isolation the auditor has.
# ---------------------------------------------------------------------------

class BlockingAnalyst(FakeAnalyst):
    def __init__(self, events, delay):
        super().__init__(events)
        self.delay = delay

    async def run(self, question, run_id):
        import time as _time
        _time.sleep(self.delay)  # blocks whatever thread runs this coroutine
        return await super().run(question, run_id)


def test_a_blocking_analyst_cannot_hold_the_caller_past_the_ceiling(tmp_path):
    import time as _time

    events = []
    started = _time.monotonic()
    result = asyncio.run(RunOrchestrator(
        analyst=BlockingAnalyst(events, delay=5.0), auditor=FakeAuditor(events),
        memory=FakeMemory(events), trace_writer=FakeTrace(tmp_path, events),
        quality_gate=None, wall_clock_seconds=0.25,
    ).ask("question"))
    elapsed = _time.monotonic() - started

    assert elapsed < 3.0, f"orchestrator waited {elapsed:.2f}s despite a 0.25s ceiling"
    assert result.answer.answer == "Insufficient evidence."
    assert any("wall-clock" in issue for issue in result.quality.issues), result.quality.issues


# ---------------------------------------------------------------------------
# Review follow-ups: budget wrappers survive a timed-out stage, and failure
# reasons are reported truthfully in the answer's limitations.
# ---------------------------------------------------------------------------

def test_a_timed_out_analyst_keeps_its_budget_wrappers_attached(tmp_path):
    """Restoring the raw providers while the abandoned daemon thread is still
    running would let its remaining calls bypass the budget entirely; the
    wrappers are left attached instead (and rewrapped by the next run)."""
    from dyla.orchestrator import _BudgetedWebProvider

    events = []
    searcher = CountingSearcher()
    analyst = BlockingAnalyst(events, delay=5.0)
    analyst.searcher = searcher
    orchestrator = RunOrchestrator(
        analyst=analyst, auditor=FakeAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
        wall_clock_seconds=0.25,
    )
    asyncio.run(orchestrator.ask("question"))

    assert isinstance(analyst.searcher, _BudgetedWebProvider), (
        "the timed-out stage's budget wrapper was removed while its thread still runs"
    )


def test_the_next_run_rewraps_a_leftover_budget_wrapper(tmp_path):
    events = []
    searcher = CountingSearcher()

    class BlockOnceAnalyst(FakeAnalyst):
        def __init__(self, events):
            super().__init__(events)
            self.calls = 0

        async def run(self, question, run_id):
            self.calls += 1
            if self.calls == 1:
                import time as _time
                _time.sleep(5.0)  # abandoned past the ceiling
            return await super().run(question, run_id)

    analyst = BlockOnceAnalyst(events)
    analyst.searcher = searcher
    orchestrator = RunOrchestrator(
        analyst=analyst, auditor=FakeAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
        wall_clock_seconds=0.25,
    )
    first = asyncio.run(orchestrator.ask("first"))
    assert first.answer.answer == "Insufficient evidence."

    second = asyncio.run(orchestrator.ask("second"))
    assert second.answer.answer == "answer", "the leftover wrapper broke the next run"
    assert searcher.searches == 0, "the wrapper was not rewired to the new ledger"


def test_a_budget_breach_is_not_reported_as_a_wall_clock_timeout_in_the_answer(tmp_path):
    events = []
    searcher = CountingSearcher()
    analyst = SearchingAnalyst(events, searcher)
    result = asyncio.run(RunOrchestrator(
        analyst=analyst, auditor=FakeAuditor(events), memory=FakeMemory(events),
        trace_writer=FakeTrace(tmp_path, events), quality_gate=None,
        max_web_requests=2, wall_clock_seconds=2.0,
    ).ask("question"))

    assert result.answer.limitations, result.answer
    assert "web-request budget" not in result.answer.limitations[0] or (
        "wall-clock" not in result.answer.limitations[0]
    )
    assert any("web request budget exceeded" in limitation for limitation in result.answer.limitations), (
        result.answer.limitations
    )
    assert not any("wall-clock" in limitation for limitation in result.answer.limitations), (
        result.answer.limitations
    )
