"""Shared Pydantic contracts for the Dyla research agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Citation(BaseModel):
    url: str
    title: str | None
    source_id: str
    chunk_id: str | None


class Claim(BaseModel):
    id: str
    text: str
    citations: list[Citation]
    confidence: str


class AnalystAnswer(BaseModel):
    answer: str
    claims: list[Claim]
    limitations: list[str]


class AuditVerdict(BaseModel):
    claim_id: str
    status: Literal["supported", "unsupported", "contradicted", "uncited"]
    explanation: str
    citations_checked: list[Citation]


class RunEvent(BaseModel):
    run_id: str
    timestamp: datetime
    component: str
    event: str
    payload: dict
    duration_ms: int | None
    error: str | None


class Document(BaseModel):
    source_id: str
    url: str
    title: str | None
    text: str
    published_at: datetime | None


class EvidenceChunk(BaseModel):
    chunk_id: str
    source_id: str
    url: str
    title: str | None
    section: str | None
    text: str
    position: int
    entity_ids: list[str]
    content_hash: str


class Evidence(BaseModel):
    chunk_id: str
    source_id: str
    url: str
    title: str | None
    text: str
    score: float
    entity_ids: list[str]


class SearchHit(BaseModel):
    url: str
    title: str | None
    snippet: str
    published_at: datetime | None


class SearchFilters(BaseModel):
    entity_ids: list[str] | None = None
    source_ids: list[str] | None = None
    published_after: datetime | None = None
    published_before: datetime | None = None


class MemoryRecord(BaseModel):
    id: str
    kind: str
    text: str
    entity_ids: list[str]
    source_ids: list[str]
    verified: bool


class Budget(BaseModel):
    deadline_seconds: float
    max_model_tokens: int
    max_cost: float
    max_web_requests: int


class AgentInput(BaseModel):
    question: str
    context: dict


class AgentResult(BaseModel):
    data: BaseModel
    metrics: dict


class ResearchPlan(BaseModel):
    original_question: str
    subqueries: list[dict]
    entities: list[str]
    date_constraints: list[str]


class Metrics(BaseModel):
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    duration_ms: int
    searches: int
    fetches: int
    memory_hits: int
    parallel_calls: int
