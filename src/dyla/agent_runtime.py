"""Budgeted async execution for injected Dyla agents and tools."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from .domain import AgentInput, AgentResult, Budget, RunEvent

Handler = Callable[..., Awaitable[Any]]
ToolCategory = Literal["generic", "web"]


class BudgetLedger:
    """Runtime-owned counters; agents cannot increase or replace these values."""

    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.model_tokens = 0
        self.cost = 0.0
        self.web_requests = 0

    def before_model(self, max_tokens: int) -> None:
        if max_tokens < 0 or self.model_tokens + max_tokens > self.budget.max_model_tokens:
            raise ValueError("model token budget exceeded")

    def after_model(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        self.model_tokens += input_tokens + output_tokens
        self.cost += cost
        if self.model_tokens > self.budget.max_model_tokens:
            raise ValueError("model token budget exceeded")
        if self.cost > self.budget.max_cost:
            raise ValueError("cost budget exceeded")

    def before_web_request(self) -> None:
        if self.web_requests >= self.budget.max_web_requests:
            raise ValueError("web request budget exceeded")
        self.web_requests += 1


class BudgetedModel:
    def __init__(self, model: Any, ledger: BudgetLedger) -> None:
        self._model, self._ledger = model, ledger

    def complete(self, request: Any) -> Any:
        self._ledger.before_model(int(getattr(request, "max_tokens", 0)))
        response = self._model.complete(request)
        self._ledger.after_model(
            int(getattr(response, "input_tokens", 0)),
            int(getattr(response, "output_tokens", 0)),
            float(getattr(response, "estimated_cost", 0.0)),
        )
        return response


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[Handler, ToolCategory]] = {}
        self.model: BudgetedModel | None = None
        self.ledger: BudgetLedger | None = None

    def register(self, name: str, handler: Handler, *, category: ToolCategory = "generic") -> None:
        callable_async = callable(handler) and (inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(handler.__call__))
        if not name.strip() or not callable_async:
            raise ValueError("tool name and async handler are required")
        if name in self._handlers:
            raise ValueError(f"tool already registered: {name}")
        self._handlers[name] = (handler, category)

    def has_unclassified(self) -> bool:
        return any(category == "generic" for _, category in self._handlers.values())

    def scoped(self) -> ToolRegistry:
        scoped = ToolRegistry()
        scoped._handlers = self._handlers.copy()
        return scoped

    def get(self, name: str) -> Handler:
        try:
            handler, category = self._handlers[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

        async def guarded(*args: Any, **kwargs: Any) -> Any:
            if self.ledger is not None and category == "web":
                self.ledger.before_web_request()
            return await handler(*args, **kwargs)

        return guarded

    async def invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return await self.get(name)(*args, **kwargs)

    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)


class Agent(Protocol):
    async def run(self, input: AgentInput, tools: ToolRegistry) -> AgentResult: ...


class AgentRuntime:
    def __init__(self, *, model: Any | None = None, tools: ToolRegistry | None = None, trace_writer: Any | None = None) -> None:
        self.tools = tools or ToolRegistry()
        self.model = model
        self.trace_writer = trace_writer

    async def run(self, agent: Agent, input: AgentInput, budget: Budget) -> AgentResult:
        self._validate_budget(budget)
        if self.tools.has_unclassified():
            raise ValueError("tool category is required for a budgeted run")
        ledger = BudgetLedger(budget)
        tools = self.tools.scoped()
        tools.ledger = ledger
        if self.model is not None:
            tools.model = BudgetedModel(self.model, ledger)
        started = time.monotonic()
        self._trace(input, "started", {"tools": tools.names()})
        try:
            result = await asyncio.wait_for(agent.run(input, tools), budget.deadline_seconds)
            if not isinstance(result, AgentResult):
                raise TypeError("agent must return AgentResult")
            metrics = dict(result.metrics)
            metrics.update({"model_tokens": ledger.model_tokens, "cost": ledger.cost, "web_requests": ledger.web_requests})
            metrics.setdefault("duration_ms", int((time.monotonic() - started) * 1000))
            self._trace(input, "completed", metrics)
            return AgentResult(data=result.data, metrics=metrics)
        except TimeoutError as exc:
            self._trace(input, "failed", {"error": "deadline exceeded"})
            raise ValueError("budget deadline exceeded") from exc
        except Exception as exc:
            self._trace(input, "failed", {"error": str(exc)})
            raise
        finally:
            tools.model = None
            tools.ledger = None

    @staticmethod
    def _validate_budget(budget: Budget) -> None:
        if budget.deadline_seconds <= 0 or budget.max_model_tokens < 0 or budget.max_cost < 0 or budget.max_web_requests < 0:
            raise ValueError("budget values must be non-negative and deadline must be positive")

    def _trace(self, input: AgentInput, event: str, payload: dict[str, Any]) -> None:
        if self.trace_writer is None:
            return
        self.trace_writer.append(RunEvent(
            run_id=str(input.context.get("run_id", "agent-run")), timestamp=datetime.now(UTC),
            component="agent_runtime", event=event, payload=payload, duration_ms=None, error=None,
        ))
