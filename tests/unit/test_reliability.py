from pathlib import Path

from dyla.domain import AnalystAnswer, AuditVerdict, Citation, Claim
from dyla.reliability import QualityGate, QualityResult


def claim(claim_id, citations=None):
    return Claim(id=claim_id, text=claim_id, confidence="high", citations=citations or [])


def verdict(claim_id, status, citations=None):
    return AuditVerdict(claim_id=claim_id, status=status, explanation=status, citations_checked=citations or [])


def test_quality_gate_is_complete_only_when_all_evidence_gates_are_met(tmp_path):
    trace = tmp_path / "run.jsonl"
    trace.write_text('{"event":"completed"}\n')
    citation = Citation(url="https://example.com", title="Source", source_id="s1", chunk_id="c1")

    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1", [citation])], limitations=[]),
        [verdict("c1", "supported", [citation])], trace,
    )

    assert result == QualityResult(status="complete", issues=[])


def test_quality_gate_returns_incomplete_for_missing_or_bad_evidence_in_stable_order(tmp_path):
    trace = tmp_path / "run.jsonl"
    trace.write_text('{"event":"completed"}\n')
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
    trace.write_text('{"event":"partial"}\n')

    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1")], limitations=[]), [], trace,
    )

    assert result == QualityResult(status="unaudited", issues=["no audit verdicts were produced"])


def test_quality_gate_requires_saved_trace(tmp_path):
    citation = Citation(url="https://example.com", title=None, source_id="s", chunk_id=None)
    result = QualityGate().validate(
        AnalystAnswer(answer="answer", claims=[claim("c1", [citation])], limitations=[]),
        [verdict("c1", "supported", [citation])], tmp_path / "missing.jsonl",
    )

    assert result.status == "incomplete"
    assert result.issues == ["research trace was not saved"]
