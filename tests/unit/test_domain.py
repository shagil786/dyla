from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dyla.domain import (
    AgentInput,
    AgentResult,
    AnalystAnswer,
    AuditVerdict,
    Budget,
    Citation,
    Claim,
    Document,
    Evidence,
    EvidenceChunk,
    MemoryRecord,
    Metrics,
    ResearchPlan,
    RunEvent,
    SearchFilters,
    SearchHit,
)


def test_domain_models_accept_the_shared_contract_shapes():
    citation = Citation(
        url="https://example.com/source",
        title="Example",
        source_id="source-1",
        chunk_id="chunk-1",
    )
    claim = Claim(id="claim-1", text="A claim", citations=[citation], confidence="high")

    assert AnalystAnswer(answer="An answer", claims=[claim], limitations=[]).claims == [claim]
    assert AuditVerdict(
        claim_id="claim-1",
        status="supported",
        explanation="The citation supports it.",
        citations_checked=[citation],
    ).status == "supported"
    assert RunEvent(
        run_id="run-1",
        timestamp=datetime(2026, 9, 2, tzinfo=UTC),
        component="research",
        event="started",
        payload={"query": "A claim"},
        duration_ms=None,
        error=None,
    ).payload == {"query": "A claim"}
    assert Document(
        source_id="source-1",
        url="https://example.com/source",
        title="Example",
        text="Body",
        published_at=None,
    ).text == "Body"
    assert EvidenceChunk(
        chunk_id="chunk-1",
        source_id="source-1",
        url="https://example.com/source",
        title="Example",
        section=None,
        text="Body",
        position=0,
        entity_ids=["entity-1"],
        content_hash="hash",
    ).position == 0
    assert Evidence(
        chunk_id="chunk-1",
        source_id="source-1",
        url="https://example.com/source",
        title="Example",
        text="Body",
        score=0.95,
        entity_ids=["entity-1"],
    ).score == 0.95
    assert SearchHit(
        url="https://example.com/source",
        title="Example",
        snippet="A snippet",
        published_at=None,
    ).snippet == "A snippet"
    assert SearchFilters().entity_ids is None
    assert MemoryRecord(
        id="memory-1",
        kind="fact",
        text="A fact",
        entity_ids=["entity-1"],
        source_ids=["source-1"],
        verified=True,
    ).verified is True
    assert Budget(
        deadline_seconds=10.0,
        max_model_tokens=1000,
        max_cost=1.5,
        max_web_requests=5,
    ).max_cost == 1.5
    assert AgentInput(question="What?", context={"scope": "test"}).question == "What?"
    assert AgentResult(data=AnalystAnswer(answer="", claims=[], limitations=[]), metrics={}).metrics == {}
    assert ResearchPlan(
        original_question="What?",
        subqueries=[{"query": "What?"}],
        entities=["entity-1"],
        date_constraints=[],
    ).entities == ["entity-1"]
    assert Metrics(
        input_tokens=1,
        output_tokens=2,
        estimated_cost=0.01,
        duration_ms=3,
        searches=1,
        fetches=1,
        memory_hits=0,
        parallel_calls=1,
    ).output_tokens == 2


def test_audit_verdict_rejects_status_outside_the_shared_literal():
    with pytest.raises(ValidationError):
        AuditVerdict.model_validate(
            {
                "claim_id": "claim-1",
                "status": "maybe",
                "explanation": "Invalid",
                "citations_checked": [],
            }
        )


def test_required_domain_fields_are_not_silently_defaulted():
    with pytest.raises(ValidationError):
        Citation.model_validate({"url": "https://example.com", "source_id": "source-1"})
