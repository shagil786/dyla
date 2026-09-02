import asyncio
from pathlib import Path

from dyla.domain import AnalystAnswer, AuditVerdict, Claim, Metrics, RunEvent
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
    auditor = FakeAuditor(events)
    auditor.metrics = {
        "input_tokens": 13, "output_tokens": 17, "estimated_cost": 0.75,
        "duration_ms": 8, "searches": 1, "fetches": 2,
        "memory_hits": 1, "parallel_calls": 2,
    }
    result = asyncio.run(RunOrchestrator(
        analyst=FakeAnalyst(events), auditor=auditor, memory=FakeMemory(events),
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
