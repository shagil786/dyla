"""End-to-end guard: the offline suite must produce clean, complete traces.

This exists because of a specific near-miss. Adding four trace events to satisfy
the "log the course corrections" requirement turned **every question in the
suite** `incomplete`, because the trace validator holds an allowlist of event
names and an unrecognised event is treated as a corrupt trace. Every unit test
still passed: none of them ran a real question end to end and then validated the
resulting trace.

So the guard is deliberately not a unit test. It runs actual questions through
the real orchestrator against the recorded corpus and asserts on the artifact a
reviewer would open.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dyla.analyst import AnalystAgent
from dyla.auditor import AuditorAgent
from dyla.entities import EntityResolver
from dyla.local_vector import LocalVectorStore
from dyla.memory import MemoryStore
from dyla.offline import OfflineEmbedder, OfflineModel, OfflineResearchProvider
from dyla.orchestrator import RunOrchestrator
from dyla.tracing import TraceWriter


@pytest.fixture()
def orchestrator(tmp_path):
    memory = MemoryStore(tmp_path / "dyla.db")
    memory.initialize()
    for name in ("Zerodha", "Infosys"):
        memory.upsert_entity(name, "company")
    provider = OfflineResearchProvider()
    writer = TraceWriter(root=tmp_path)
    analyst = AnalystAgent(
        model=OfflineModel(), resolver=EntityResolver(memory), memory=memory,
        searcher=provider, fetcher=provider, index=LocalVectorStore(),
        embedder=OfflineEmbedder(), trace_writer=writer,
    )
    return RunOrchestrator(
        analyst=analyst,
        auditor=AuditorAgent(fetcher=provider, memory=memory, trace_writer=writer,
                             retries=1, timeout_seconds=10.0),
        memory=memory, trace_writer=writer,
    ), tmp_path


def _events(root: Path, run_id: str) -> list[dict]:
    path = root / "logs" / f"{run_id}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_real_run_produces_a_trace_the_validator_accepts(orchestrator):
    """Every emitted event must be in the validator's allowlist.

    Regression: four new events were not, and the whole suite silently went from
    7/8 to 0/8 while the unit tests stayed green.
    """
    runner, root = orchestrator

    result = asyncio.run(runner.ask("Who is the current chief executive officer of Zerodha?"))

    unknown = [issue for issue in result.quality.issues if "unknown event" in issue]
    assert unknown == [], f"trace contains events the validator rejects: {unknown}"


def test_a_real_run_logs_the_plan_before_it_searches(orchestrator):
    """The brief's first Part A requirement, asserted on the real artifact."""
    runner, root = orchestrator

    result = asyncio.run(runner.ask("Who is the current chief executive officer of Zerodha?"))

    names = [event["event"] for event in _events(root, result.run_id)]
    assert "plan_created" in names, "a reviewer cannot see what the analyst intended"
    assert names.index("plan_created") < names.index("web_searched")


def test_a_real_run_records_what_it_spent(orchestrator):
    """Token counts must survive redaction and reach the log.

    They were being scrubbed: the credential filter matched the substring
    "token" in "model_tokens" and replaced the value.
    """
    runner, root = orchestrator

    result = asyncio.run(runner.ask("Who is the current chief executive officer of Zerodha?"))

    completed = [
        event for event in _events(root, result.run_id) if event["event"] == "completed"
    ]
    assert completed, "no stage reported completion"
    analyst_stage = completed[0]["payload"]
    assert analyst_stage["input_tokens"] > 0
    assert analyst_stage["embedding_tokens"] > 0
    assert "[REDACTED]" not in json.dumps(analyst_stage)


def test_the_trace_shows_every_tool_call_and_its_result(orchestrator):
    """"Every tool call and what came back" -- asserted, not assumed."""
    runner, root = orchestrator

    result = asyncio.run(runner.ask("Who is the current chief executive officer of Zerodha?"))
    events = _events(root, result.run_id)
    by_name = {event["event"] for event in events}

    assert {"web_searched", "page_fetched", "evidence_selected", "answer_synthesized"} <= by_name

    searched = next(e for e in events if e["event"] == "web_searched")
    assert "query" in searched["payload"] and "results" in searched["payload"]

    selected = next(e for e in events if e["event"] == "evidence_selected")
    assert selected["payload"]["source_ids"], "evidence must say where it came from"


def test_the_validator_also_accepts_the_course_correction_events(tmp_path):
    """The happy path never rejects a claim, so it cannot validate those events.

    Verified deliberately: deleting `claim_rejected` from the allowlist left the
    happy-path test above green. A guard that only covers the path where nothing
    goes wrong is not covering the events that exist for when something does.
    """
    from types import SimpleNamespace

    from dyla.domain import AnalystAnswer, Claim

    class UncitedModel:
        """Proposes a claim with no citations, which the analyst must reject."""

        def complete(self, request):
            return SimpleNamespace(
                parsed=AnalystAnswer(
                    answer="Answer",
                    claims=[Claim(id="c1", text="Zerodha is profitable.", citations=[])],
                ),
                input_tokens=10, output_tokens=5, estimated_cost=0.0,
            )

    memory = MemoryStore(tmp_path / "dyla.db")
    memory.initialize()
    memory.upsert_entity("Zerodha", "company")
    provider = OfflineResearchProvider()
    writer = TraceWriter(root=tmp_path)
    analyst = AnalystAgent(
        model=UncitedModel(), resolver=EntityResolver(memory), memory=memory,
        searcher=provider, fetcher=provider, index=LocalVectorStore(),
        embedder=OfflineEmbedder(), trace_writer=writer,
    )
    runner = RunOrchestrator(
        analyst=analyst,
        auditor=AuditorAgent(fetcher=provider, memory=memory, trace_writer=writer,
                             retries=1, timeout_seconds=10.0),
        memory=memory, trace_writer=writer,
    )

    result = asyncio.run(runner.ask("Is Zerodha profitable?"))

    names = [event["event"] for event in _events(tmp_path, result.run_id)]
    assert "claim_rejected" in names
    assert "answer_withheld" in names

    unknown = [issue for issue in result.quality.issues if "unknown event" in issue]
    assert unknown == [], f"trace contains events the validator rejects: {unknown}"


class _SingleClaimModel:
    """Proposes exactly one claim, cited to the first evidence item in the prompt.

    Copying url/source_id/chunk_id from the prompt's evidence blocks guarantees
    the citation maps to what this run actually retrieved, so the claim reaches
    the specific rejection gate each test is aimed at rather than dying on the
    citation-mapping gate.
    """

    def __init__(self, text: str, confidence: str = "high") -> None:
        from types import SimpleNamespace

        self.text = text
        self.confidence = confidence
        self._namespace = SimpleNamespace

    def complete(self, request):
        from dyla.domain import AnalystAnswer, Claim, Citation
        from dyla.offline import _parse_prompt

        prompt = "\n".join(str(message.get("content", "")) for message in request.messages)
        _, evidence = _parse_prompt(prompt)
        item = evidence[0]
        claim = Claim(
            id="c1", text=self.text,
            citations=[Citation(url=item["url"], title=item["title"],
                                source_id=item["source_id"], chunk_id=item["chunk_id"])],
            confidence=self.confidence,
        )
        return self._namespace(
            parsed=AnalystAnswer(answer=self.text, claims=[claim], limitations=[]),
            input_tokens=10, output_tokens=5, estimated_cost=0.0,
        )


def _rejection_reasons(root: Path, run_id: str) -> list[dict]:
    return [
        event["payload"] for event in _events(root, run_id)
        if event["event"] == "claim_rejected"
    ]


def test_an_under_corroborated_claim_is_traced_with_its_reason_code(orchestrator):
    """`insufficient_corroboration` must be asserted on the trace artifact.

    It used to have no trace-level assertion at all: no test drove a claim
    through the real analyst with low confidence and a single source, so a
    change that silently dropped or renamed the event would have stayed green.
    """
    runner, root = orchestrator
    runner.analyst.model = _SingleClaimModel(
        "Nithin Kamath is the chief executive officer of Zerodha.",
        confidence="low",
    )

    result = asyncio.run(runner.ask("Who is the current chief executive officer of Zerodha?"))

    payloads = _rejection_reasons(root, result.run_id)
    assert any(item["reason"] == "insufficient_corroboration" for item in payloads), payloads
    event = next(item for item in payloads if item["reason"] == "insufficient_corroboration")
    assert event["confidence"] == "low"
    assert event["distinct_sources"] == 1
    assert event["claim_text"] == "Nithin Kamath is the chief executive officer of Zerodha."


def test_audit_feedback_blocking_is_traced_with_its_reason_code(orchestrator):
    """`blocked_by_audit_feedback` must be asserted on the trace artifact.

    The metric existed and the unit tests asserted it, but nothing asserted the
    trace event: the machine-readable record a reviewer actually opens. Two
    real runs — the first audited and rejected, the second restating the claim
    — are the honest way to exercise it.
    """
    runner, root = orchestrator

    runner.analyst.model = _SingleClaimModel(
        "Nithin Kamath took over as chief executive officer of Zerodha in 2019."
    )
    first = asyncio.run(runner.ask("Who is the current chief executive officer of Zerodha?"))
    first_audits = [
        event["payload"] for event in _events(root, first.run_id)
        if event["event"] == "claim_audited"
    ]
    assert any(item["status"] == "unsupported" for item in first_audits), first_audits

    # The model ignores the "an auditor rejected this" instruction in its
    # system prompt and restates the claim; the post-synthesis filter is the
    # backstop the trace must record.
    runner.analyst.model = _SingleClaimModel(
        "In 2019, Nithin Kamath became the chief executive officer of Zerodha."
    )
    second = asyncio.run(runner.ask("Who is the current chief executive officer of Zerodha?"))

    payloads = _rejection_reasons(root, second.run_id)
    assert any(item["reason"] == "blocked_by_audit_feedback" for item in payloads), payloads
    assert runner.analyst.metrics["claims_blocked_by_audit_feedback"] == 1
    withheld = [
        event for event in _events(root, second.run_id)
        if event["event"] == "answer_withheld"
    ]
    assert withheld, "a run whose every claim was rejected must say so in the trace"
