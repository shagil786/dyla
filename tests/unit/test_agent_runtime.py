import asyncio
import time

import pytest
from pydantic import BaseModel

from dyla.domain import AgentInput, AgentResult, Budget
from dyla.agent_runtime import AgentRuntime, ToolRegistry
from dyla.models import ModelResponse


class Output(BaseModel):
    value: str


def test_tool_registry_registers_and_invokes_async_handlers():
    registry = ToolRegistry()

    async def add(value):
        return value + 1

    registry.register("add", add)
    assert asyncio.run(registry.invoke("add", 2)) == 3
    with pytest.raises(ValueError):
        registry.register("add", add)


def test_runtime_rejects_budget_before_running_agent():
    class Agent:
        async def run(self, input, tools):
            raise AssertionError("must not run")

    with pytest.raises(ValueError, match="budget"):
        asyncio.run(AgentRuntime().run(
            Agent(), AgentInput(question="Q", context={}),
            Budget(deadline_seconds=0, max_model_tokens=10, max_cost=1, max_web_requests=1),
        ))


def test_async_callable_object_is_a_valid_tool():
    class Tool:
        async def __call__(self, value):
            return value + 1

    registry = ToolRegistry()
    registry.register("callable", Tool())
    assert asyncio.run(registry.invoke("callable", 2)) == 3


def test_runtime_enforces_model_and_web_budgets_during_calls_not_final_metrics():
    class Model:
        def complete(self, request):
            return ModelResponse(text="ok", parsed=Output(value="ok"), input_tokens=4, output_tokens=4, estimated_cost=0.6, latency_ms=0)

    async def fetch():
        return "page"

    registry = ToolRegistry()
    registry.register("web_fetch", fetch, category="web")

    class Agent:
        async def run(self, input, tools):
            tools.model.complete(type("Request", (), {"max_tokens": 4})())
            await tools.invoke("web_fetch")
            await tools.invoke("web_fetch")
            return AgentResult(data=Output(value="ok"), metrics={})

    with pytest.raises(ValueError, match="budget"):
        asyncio.run(AgentRuntime(model=Model(), tools=registry).run(
            Agent(), AgentInput(question="Q", context={}),
            Budget(deadline_seconds=1, max_model_tokens=5, max_cost=1, max_web_requests=1),
        ))


def test_concurrent_runs_have_independent_ledgers_and_direct_handler_calls_are_counted():
    registry = ToolRegistry()

    async def fetch():
        await asyncio.sleep(0.01)
        return "page"

    registry.register("fetch", fetch, category="web")

    class Agent:
        async def run(self, input, tools):
            await tools.get("fetch")()
            await asyncio.sleep(0.01)
            return AgentResult(data=Output(value=input.question), metrics={})

    async def run_pair():
        runtime = AgentRuntime(tools=registry)
        budget = Budget(deadline_seconds=1, max_model_tokens=1, max_cost=0, max_web_requests=1)
        return await asyncio.gather(
            runtime.run(Agent(), AgentInput(question="a", context={}), budget),
            runtime.run(Agent(), AgentInput(question="b", context={}), budget),
        )

    results = asyncio.run(run_pair())
    assert [result.metrics["web_requests"] for result in results] == [1, 1]
    assert registry.model is None
    assert registry.ledger is None


def test_runtime_traces_query_expansion_with_run_id():
    events = []
    class Writer:
        def append(self, event):
            events.append(event)

    class Agent:
        async def run(self, input, tools):
            return AgentResult(data=Output(value="ok"), metrics={})

    asyncio.run(AgentRuntime(trace_writer=Writer()).run(
        Agent(), AgentInput(question="Q", context={"run_id": "trace-7"}),
        Budget(deadline_seconds=1, max_model_tokens=5, max_cost=1, max_web_requests=1),
    ))
    assert {event.run_id for event in events} == {"trace-7"}


def test_runtime_validates_agent_result_and_tracks_metrics():
    class Agent:
        async def run(self, input, tools):
            return AgentResult(data=Output(value=input.question), metrics={"model_tokens": 2, "cost": 0.1})

    result = asyncio.run(AgentRuntime().run(
        Agent(), AgentInput(question="Q", context={}),
        Budget(deadline_seconds=1, max_model_tokens=10, max_cost=1, max_web_requests=1),
    ))
    assert result.data.value == "Q"
    assert result.metrics["model_tokens"] == 0
