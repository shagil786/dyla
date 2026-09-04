import json
from datetime import UTC, datetime
from pathlib import Path

from dyla.domain import AnalystAnswer, AuditVerdict, Citation, Claim, RunEvent
from dyla.reliability import QualityGate, QualityResult


def claim(claim_id, citations=None):
    return Claim(id=claim_id, text=claim_id, confidence="high", citations=citations or [])


def verdict(claim_id, status, citations=None):
    return AuditVerdict(claim_id=claim_id, status=status, explanation=status, citations_checked=citations or [])


def write_trace(path: Path, run_id="run-1", event="claim_audited", payload=None):
    path.write_text(json.dumps(RunEvent(
        run_id=run_id, timestamp=datetime.now(UTC), component="auditor",
        event=event, payload=payload or {"claim_id": "c1", "status": "supported"},
        duration_ms=None, error=None,
    ).model_dump(mode="json")) + "\n")


def test_quality_gate_is_complete_only_when_all_evidence_gates_are_met(tmp_path):
    trace = tmp_path / "run.jsonl"
    write_trace(trace)
    citation = Citation(url="https://example.com", title="Source", source_id="s1", chunk_id="c1")

    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1", [citation])], limitations=[]),
        [verdict("c1", "supported", [citation])], trace,
    )

    assert result == QualityResult(status="complete", issues=[])


def test_quality_gate_returns_incomplete_for_missing_or_bad_evidence_in_stable_order(tmp_path):
    trace = tmp_path / "run.jsonl"
    write_trace(trace)
    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("b"), claim("a", [Citation(url="https://a", title=None, source_id="s", chunk_id=None)])], limitations=[]),
        [verdict("a", "contradicted")], trace,
    )

    assert result.status == "incomplete"
    assert result.issues == [
        "claim a has citations that were not retrieved",
        "claim a is contradicted",
        "claim b has no audit verdict",
        "claim b has no citations",
    ]


def test_quality_gate_returns_unaudited_when_auditor_produced_no_verdicts(tmp_path):
    trace = tmp_path / "run.jsonl"
    write_trace(trace, event="auditor_failed", payload={"error": "failed"})

    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1")], limitations=[]), [], trace,
    )

    assert result == QualityResult(status="unaudited", issues=["no audit verdicts were produced"])


def test_quality_gate_rejects_duplicate_and_incomplete_verdict_coverage(tmp_path):
    trace = tmp_path / "run.jsonl"
    write_trace(trace)
    citation = Citation(url="https://example.com", title=None, source_id="s", chunk_id=None)
    answer = AnalystAnswer(answer="answer", claims=[claim("c1", [citation]), claim("c2", [citation])], limitations=[])

    result = QualityGate().validate(
        answer, [verdict("c1", "supported", [citation]), verdict("c1", "supported", [citation])], trace,
    )

    assert result.status == "incomplete"
    assert result.issues == [
        "claim c1 has multiple audit verdicts",
        "claim c2 has no audit verdict",
    ]


def test_quality_gate_rejects_duplicate_claim_ids(tmp_path):
    trace = tmp_path / "run.jsonl"
    write_trace(trace)
    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1"), claim("c1")], limitations=[]),
        [verdict("c1", "uncited")], trace,
    )

    assert result.status == "incomplete"
    assert "answer contains duplicate claim id: c1" in result.issues


def test_quality_gate_rejects_trace_from_another_run_and_invalid_events(tmp_path):
    trace = tmp_path / "run.jsonl"
    write_trace(trace, run_id="other-run")
    trace.write_text(trace.read_text() + json.dumps(RunEvent(
        run_id="other-run", timestamp=datetime.now(UTC), component="auditor",
        event="arbitrary", payload={}, duration_ms=None, error=None,
    ).model_dump(mode="json")) + "\n")
    citation = Citation(url="https://example.com", title=None, source_id="s", chunk_id=None)

    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1", [citation])], limitations=[]),
        [verdict("c1", "supported", [citation])], trace, run_id="requested-run",
    )

    assert result.status == "incomplete"
    assert "research trace contains event for another run: other-run" in result.issues
    assert "research trace has unknown event: arbitrary" in result.issues


def test_quality_gate_accepts_ingest_failed_events(tmp_path):
    trace = tmp_path / "run.jsonl"
    write_trace(trace, event="ingest_failed", payload={"url": "https://example.com", "error": "retry exhaustion"})
    citation = Citation(url="https://example.com", title="Source", source_id="s1", chunk_id="c1")

    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1", [citation])], limitations=[]),
        [verdict("c1", "supported", [citation])], trace,
    )

    assert result == QualityResult(status="complete", issues=[])


def test_quality_gate_requires_saved_trace(tmp_path):
    citation = Citation(url="https://example.com", title=None, source_id="s", chunk_id=None)
    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1", [citation])], limitations=[]),
        [verdict("c1", "supported", [citation])], tmp_path / "missing.jsonl",
    )

    assert result.status == "incomplete"
    assert result.issues == ["research trace was not saved"]
