"""Application composition for a complete research run."""

from __future__ import annotations

import asyncio
import time
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
        self._run_issues: list[str] = []

    async def ask(self, question: str) -> RunResult:
        if not question.strip():
            raise ValueError("question must not be empty")
        started = time.monotonic()
        baseline = self._snapshot_metrics()
        run_id = str(self.run_id_factory())
        self._run_issues = []
        self.memory.initialize()
        answer = await self.analyst.run(question, run_id)
        verdicts = await asyncio.to_thread(self.auditor.run, answer, run_id)
        for claim in answer.claims:
            verdict = next((item for item in verdicts if item.claim_id == claim.id), None)
            try:
                self.memory.save_claim(claim, verdict)
            except Exception as exc:
                self._run_issues.append(f"{run_id}: {claim.id}: memory persistence failed: {exc}")
        self._trace(run_id, "memory_saved", {"claims": len(answer.claims)})
        trace_path = self._trace_path(run_id)
        audit_state = getattr(self.auditor, "audit_state", None)
        audit_issues = list(getattr(audit_state, "issues", [])) + self._run_issues
        quality = self.quality_gate.validate(
            answer, verdicts, trace_path, run_id=run_id, audit_issues=audit_issues,
        )
        if not self._trace(run_id, "quality_completed", {"status": quality.status, "issues": quality.issues}):
            quality = QualityResult("incomplete", sorted({*quality.issues, *self._run_issues}))
        metrics = self._aggregate_metrics(started, baseline)
        return RunResult(run_id, answer, verdicts, quality, metrics, trace_path)

    def _snapshot_metrics(self) -> list[dict[str, int | float]]:
        snapshots = []
        for component in (self.analyst, self.auditor, self.memory):
            values = getattr(component, "metrics", {})
            snapshots.append({
                field: value for field, value in values.items()
                if field in Metrics.model_fields and isinstance(value, (int, float))
            } if isinstance(values, dict) else {})
        return snapshots

    def _aggregate_metrics(self, started: float, baseline: list[dict[str, int | float]]) -> Metrics:
        totals: dict[str, int | float] = {field: 0 for field in Metrics.model_fields}
        for index, component in enumerate((self.analyst, self.auditor, self.memory)):
            values = getattr(component, "metrics", {})
            if not isinstance(values, dict):
                continue
            previous = baseline[index]
            for field in totals:
                value = values.get(field, 0)
                before = previous.get(field, 0)
                if isinstance(value, (int, float)) and isinstance(before, (int, float)):
                    delta = value - before if value >= before else value
                    totals[field] += max(0, delta)
        totals["duration_ms"] = max(
            int((time.monotonic() - started) * 1000), int(totals["duration_ms"])
        )
        return Metrics(
            input_tokens=int(totals["input_tokens"]), output_tokens=int(totals["output_tokens"]),
            estimated_cost=float(totals["estimated_cost"]), duration_ms=int(totals["duration_ms"]),
            searches=int(totals["searches"]), fetches=int(totals["fetches"]),
            memory_hits=int(totals["memory_hits"]), parallel_calls=int(totals["parallel_calls"]),
        )

    def _trace(self, run_id: str, event: str, payload: dict[str, Any]) -> bool:
        try:
            self.trace_writer.append(RunEvent(
                run_id=run_id, component="orchestrator", event=event,
                payload=payload, timestamp=datetime.now(UTC),
                duration_ms=None, error=None,
            ))
        except Exception as exc:
            self._run_issues.append(f"{run_id}: {event} tracing failed: {exc}")
            return False
        return True

    def _trace_path(self, run_id: str) -> Path:
        root = Path(getattr(self.trace_writer, "root", "."))
        return root / "logs" / f"{run_id}.jsonl"
