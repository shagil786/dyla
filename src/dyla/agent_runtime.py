"""Budgeted async execution for injected Dyla agents and tools."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from .domain import AgentInput, AgentResult, Budget, RunEvent


Handler = Callable[..., Awaitable[Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, handler: Handler) -> None:
        if not name.strip() or not callable(handler) or not inspect.iscoroutinefunction(handler):
            raise ValueError("tool name and async handler are required")
        if name in self._handlers:
            raise ValueError(f"tool already registered: {name}")
        self._handlers[name] = handler

    def get(self, name: str) -> Handler:
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    async def invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return await self.get(name)(*args, **kwargs)

    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)


class Agent(Protocol):
    async def run(self, input: AgentInput, tools: ToolRegistry) -> AgentResult: ...


class AgentRuntime:
    def __init__(self, *, tools: ToolRegistry | None = None, trace_writer: Any | None = None) -> None:
        self.tools = tools or ToolRegistry()
        self.trace_writer = trace_writer

    async def run(self, agent: Agent, input: AgentInput, budget: Budget) -> AgentResult:
        self._validate_budget(budget)
        started = time.monotonic()
        self._trace(input, "started", {"tools": self.tools.names()})
        try:
            result = await asyncio.wait_for(agent.run(input, self.tools), budget.deadline_seconds)
            if not isinstance(result, AgentResult):
                raise TypeError("agent must return AgentResult")
            metrics = dict(result.metrics)
            tokens = int(metrics.get("model_tokens", metrics.get("output_tokens", 0)))
            cost = float(metrics.get("cost", metrics.get("estimated_cost", 0.0)))
            web_requests = int(metrics.get("web_requests", metrics.get("fetches", 0)))
            if tokens > budget.max_model_tokens:
                raise ValueError("model token budget exceeded")
            if cost > budget.max_cost:
                raise ValueError("cost budget exceeded")
            if web_requests > budget.max_web_requests:
                raise ValueError("web request budget exceeded")
            metrics.setdefault("duration_ms", int((time.monotonic() - started) * 1000))
            self._trace(input, "completed", metrics)
            return AgentResult(data=result.data, metrics=metrics)
        except TimeoutError as exc:
            self._trace(input, "failed", {"error": "deadline exceeded"})
            raise ValueError("budget deadline exceeded") from exc
        except Exception as exc:
            self._trace(input, "failed", {"error": str(exc)})
            raise

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
