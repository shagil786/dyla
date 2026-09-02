import asyncio

import pytest
from pydantic import BaseModel

from dyla.domain import AgentInput, AgentResult, Budget
from dyla.agent_runtime import AgentRuntime, ToolRegistry


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


def test_runtime_validates_agent_result_and_tracks_metrics():
    class Agent:
        async def run(self, input, tools):
            return AgentResult(data=Output(value=input.question), metrics={"model_tokens": 2, "cost": 0.1})

    result = asyncio.run(AgentRuntime().run(
        Agent(), AgentInput(question="Q", context={}),
        Budget(deadline_seconds=1, max_model_tokens=10, max_cost=1, max_web_requests=1),
    ))
    assert result.data.value == "Q"
    assert result.metrics["model_tokens"] == 2
