"""Application composition for a complete research run."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain import AnalystAnswer, AuditVerdict, Metrics, RunEvent
from .reliability import QualityGate, QualityResult


@dataclass(frozen=True)
class RunResult:
    run_id: str
    answer: AnalystAnswer
    verdicts: list[AuditVerdict]
    quality: QualityResult
    metrics: Metrics
    trace_path: Path


class RunOrchestrator:
    """Run analyst, independent audit, persistence, tracing, and quality gates."""

    def __init__(
        self, *, analyst: Any, auditor: Any, memory: Any, trace_writer: Any,
        quality_gate: QualityGate | None = None, run_id_factory: Any | None = None,
    ) -> None:
        self.analyst = analyst
        self.auditor = auditor
        self.memory = memory
        self.trace_writer = trace_writer
        self.quality_gate = quality_gate or QualityGate()
        self.run_id_factory = run_id_factory or (lambda: uuid.uuid4().hex)

    async def ask(self, question: str) -> RunResult:
        if not question.strip():
            raise ValueError("question must not be empty")
        run_id = str(self.run_id_factory())
        self.memory.initialize()
        answer = await self.analyst.run(question, run_id)
        verdicts = await asyncio.to_thread(self.auditor.run, answer, run_id)
        for claim in answer.claims:
            verdict = next((item for item in verdicts if item.claim_id == claim.id), None)
            self.memory.save_claim(claim, verdict)
        self._trace(run_id, "memory_saved", {"claims": len(answer.claims)})
        trace_path = self._trace_path(run_id)
        quality = self.quality_gate.validate(answer, verdicts, trace_path)
        self._trace(run_id, "quality_completed", {"status": quality.status, "issues": quality.issues})
        metrics = Metrics(
            input_tokens=0, output_tokens=0, estimated_cost=0.0,
            duration_ms=0, searches=0, fetches=0, memory_hits=0, parallel_calls=0,
        )
        return RunResult(run_id, answer, verdicts, quality, metrics, trace_path)

    def _trace(self, run_id: str, event: str, payload: dict[str, Any]) -> None:
        self.trace_writer.append(RunEvent(
            run_id=run_id, component="orchestrator", event=event,
            payload=payload, timestamp=datetime.now(UTC),
            duration_ms=None, error=None,
        ))

    def _trace_path(self, run_id: str) -> Path:
        root = Path(getattr(self.trace_writer, "root", "."))
        return root / "logs" / f"{run_id}.jsonl"
