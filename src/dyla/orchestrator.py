"""Application composition for a complete research run.

Wall-clock enforcement
----------------------
The brief puts a hard two-minute ceiling on each question, and the point of that
ceiling is to force genuine parallelism and expose an agent that is really a long
sequential chain. The previous implementation compared elapsed time against 120s
*after* each stage had already returned and appended a note to the issue list.
Nothing was cancelled, so a ten-minute analyst stage ran for ten minutes and then
got told it was late. That measures the ceiling; it does not impose one.

Here each stage runs through ``AgentRuntime``, which wraps it in
``asyncio.wait_for`` against the time still remaining in the run budget. The
budget shrinks as stages consume it, so analyst plus auditor cannot jointly
exceed the ceiling.

Honest limitation: ``AuditorAgent.run`` is synchronous and is executed on a
worker thread. Python cannot kill a thread, so on timeout the orchestrator stops
waiting and reports a partial run, but the abandoned thread runs to completion in
the background. The caller-visible ceiling holds; process-level CPU use may
briefly overrun it. The analyst is genuinely async and is cancelled properly.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent_runtime import AgentRuntime, BudgetedModel, BudgetLedger
from .domain import AgentInput, AgentResult, AnalystAnswer, AuditReport, AuditVerdict, Budget, Metrics, RunEvent
from .reliability import QualityGate, QualityResult

DEFAULT_WALL_CLOCK_SECONDS = 120.0
# Generous but finite. The deadline is the gate the brief asks for; these stop a
# runaway loop from burning the account and are reported when they bite.
DEFAULT_MAX_MODEL_TOKENS = 200_000
DEFAULT_MAX_COST = 100.0
DEFAULT_MAX_WEB_REQUESTS = 200
# Floor on the deadline handed to a stage, so a nearly-exhausted budget produces
# a clean timeout rather than a Budget validation error.
_MINIMUM_STAGE_SECONDS = 0.01


async def _run_on_daemon_thread(function: Any) -> Any:
    """Await a synchronous call on a daemon thread.

    ``asyncio.to_thread`` uses the loop's default executor, and ``asyncio.run``
    joins that executor during shutdown. A stage abandoned by ``wait_for``
    therefore still blocked the caller until the worker finished, which silently
    defeated the wall-clock ceiling: a 5s auditor overran a 0.6s budget by the
    full 5s even though the timeout had fired. A daemon thread lets the caller
    return on time and cannot hold up interpreter exit.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    def target() -> None:
        try:
            value = function()
        except BaseException as exc:  # noqa: BLE001 - relayed to the awaiting task
            loop.call_soon_threadsafe(lambda: None if future.done() else future.set_exception(exc))
        else:
            loop.call_soon_threadsafe(lambda: None if future.done() else future.set_result(value))

    threading.Thread(target=target, daemon=True, name="dyla-stage").start()
    return await future


@dataclass(frozen=True)
class RunResult:
    run_id: str
    answer: AnalystAnswer
    verdicts: list[AuditVerdict]
    quality: QualityResult
    metrics: Metrics
    trace_path: Path


class _CoroutineAgent:
    """Adapt a zero-argument coroutine factory to the AgentRuntime Agent protocol.

    The analyst and auditor predate the runtime and have their own signatures
    (`run(question, run_id)` and `run(answer, run_id)`). Adapting here makes the
    runtime load-bearing without rewriting two well-tested agents.
    """

    def __init__(self, factory: Any) -> None:
        self._factory = factory

    async def run(self, input: AgentInput, tools: Any) -> AgentResult:
        del tools
        data = await self._factory()
        return AgentResult(data=data, metrics={})


class RunOrchestrator:
    """Run analyst, independent audit, persistence, tracing, and quality gates."""

    def __init__(
        self, *, analyst: Any, auditor: Any, memory: Any, trace_writer: Any,
        quality_gate: QualityGate | None = None, run_id_factory: Any | None = None,
        wall_clock_seconds: float = DEFAULT_WALL_CLOCK_SECONDS,
        max_model_tokens: int = DEFAULT_MAX_MODEL_TOKENS,
        max_cost: float = DEFAULT_MAX_COST,
        max_web_requests: int = DEFAULT_MAX_WEB_REQUESTS,
    ) -> None:
        self.analyst = analyst
        self.auditor = auditor
        self.memory = memory
        self.trace_writer = trace_writer
        self.quality_gate = quality_gate or QualityGate()
        self.run_id_factory = run_id_factory or (lambda: uuid.uuid4().hex)
        self.wall_clock_seconds = wall_clock_seconds
        self.max_model_tokens = max_model_tokens
        self.max_cost = max_cost
        self.max_web_requests = max_web_requests
        self._run_issues: list[str] = []

    async def ask(self, question: str) -> RunResult:
        if not question.strip():
            raise ValueError("question must not be empty")
        started = time.monotonic()
        baseline = self._snapshot_metrics()
        run_id = str(self.run_id_factory())
        self._run_issues = []
        self.memory.initialize()

        runtime = AgentRuntime(trace_writer=self.trace_writer)
        ledger = BudgetLedger(self._budget(self.wall_clock_seconds))

        answer = await self._run_stage(
            runtime, ledger, run_id, "analyst", started,
            lambda: self.analyst.run(question, run_id),
        )
        if answer is None:
            answer = AnalystAnswer(
                answer="Insufficient evidence.", claims=[],
                limitations=[
                    "The analyst stage did not finish within the run's wall-clock budget "
                    f"of {self.wall_clock_seconds:.0f}s."
                ],
            )

        deadline = started + self.wall_clock_seconds
        report = await self._run_stage(
            runtime, ledger, run_id, "auditor", started,
            lambda: _run_on_daemon_thread(
                lambda: AuditReport(verdicts=self._audit(answer, run_id, deadline))
            ),
        )
        verdicts: list[AuditVerdict] = list(report.verdicts) if report is not None else []

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

    def _audit(self, answer: AnalystAnswer, run_id: str, deadline: float) -> list[AuditVerdict]:
        """Call the auditor, passing the deadline when it can honour one.

        Cooperative stopping inside the auditor is the real bound on this stage;
        the external timeout is only a backstop, because a thread cannot be
        killed. Auditors that predate the deadline parameter still work.
        """
        if self._auditor_accepts_deadline():
            return self.auditor.run(answer, run_id, deadline)
        return self.auditor.run(answer, run_id)

    def _auditor_accepts_deadline(self) -> bool:
        """Inspect the signature rather than catching TypeError.

        Calling with the extra argument and retrying on TypeError would also
        swallow a TypeError raised *inside* a deadline-aware auditor and run the
        whole audit a second time.
        """
        try:
            parameters = inspect.signature(self.auditor.run).parameters
        except (TypeError, ValueError):
            return False
        if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters.values()):
            return True
        return "deadline" in parameters or len(parameters) >= 3

    # -- stage execution -----------------------------------------------------

    def _budget(self, seconds: float) -> Budget:
        return Budget(
            deadline_seconds=max(seconds, _MINIMUM_STAGE_SECONDS),
            max_model_tokens=self.max_model_tokens,
            max_cost=self.max_cost,
            max_web_requests=self.max_web_requests,
        )

    def _remaining(self, started: float) -> float:
        return self.wall_clock_seconds - (time.monotonic() - started)

    async def _run_stage(
        self, runtime: AgentRuntime, ledger: BudgetLedger, run_id: str,
        stage: str, started: float, factory: Any,
    ) -> Any:
        """Run one stage under the remaining wall-clock budget.

        Returns the stage payload, or None if it timed out or failed. A stage
        that overruns degrades the run to a reported partial result rather than
        raising, so a slow auditor still leaves the analyst's answer intact.
        """
        remaining = self._remaining(started)
        if remaining <= _MINIMUM_STAGE_SECONDS:
            message = (
                f"{run_id}: {stage} stage skipped: the {self.wall_clock_seconds:.0f}s "
                "wall-clock ceiling was already exhausted"
            )
            self._run_issues.append(message)
            self._trace(run_id, "failed", {"stage": stage, "error": "wall clock exhausted"})
            return None

        runtime.model = None
        budget = self._budget(remaining)
        agent = _CoroutineAgent(factory)
        restore = self._attach_ledger(stage, ledger)
        try:
            result = await runtime.run(agent, AgentInput(question="", context={"run_id": run_id}), budget)
            return result.data
        except ValueError as exc:
            # AgentRuntime converts a deadline overrun into ValueError.
            message = (
                f"{run_id}: {stage} stage exceeded the {self.wall_clock_seconds:.0f}s "
                f"wall-clock ceiling: {exc}"
            )
            self._run_issues.append(message)
            self._trace(run_id, "failed", {"stage": stage, "error": str(exc)})
            return None
        except Exception as exc:
            self._run_issues.append(f"{run_id}: {stage} stage failed: {exc}")
            self._trace(run_id, "failed", {"stage": stage, "error": str(exc)})
            return None
        finally:
            restore()

    def _attach_ledger(self, stage: str, ledger: BudgetLedger) -> Any:
        """Route the stage's model calls through the shared budget ledger.

        The ledger only counts what passes through it, and the agents hold their
        own provider reference rather than pulling one from the tool registry.
        Swapping the attribute for the duration of the stage is what makes the
        token and cost caps real instead of decorative; without it the runtime
        would enforce the deadline only.
        """
        target = self.analyst if stage == "analyst" else self.auditor
        original = getattr(target, "model", None)
        if original is None or isinstance(original, BudgetedModel):
            return lambda: None
        try:
            target.model = BudgetedModel(original, ledger)
        except Exception:
            return lambda: None

        def restore() -> None:
            try:
                target.model = original
            except Exception:
                pass

        return restore

    # -- metrics and tracing -------------------------------------------------

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
            embedding_tokens=int(totals["embedding_tokens"]),
            estimated_cost=float(totals["estimated_cost"]), duration_ms=int(totals["duration_ms"]),
            searches=int(totals["searches"]), fetches=int(totals["fetches"]),
            memory_hits=int(totals["memory_hits"]), parallel_calls=int(totals["parallel_calls"]),
            searches_skipped=int(totals["searches_skipped"]),
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
