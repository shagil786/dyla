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

    assert events[:5] == ["analyst", "auditor", "memory", "trace", "trace"]
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

    assert first.metrics == second.metrics
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
