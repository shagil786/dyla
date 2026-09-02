import asyncio

from dyla.agent_runtime import AgentRuntime, ToolRegistry
from dyla.domain import AgentInput, AgentResult, Budget
from pydantic import BaseModel


class Output(BaseModel):
    value: str


def test_concurrent_runs_receive_distinct_runtime_contexts():
    registry = ToolRegistry()
    contexts = []

    class Agent:
        async def run(self, input, tools):
            contexts.append(tools._runtime_context)
            await asyncio.sleep(0.01)
            return AgentResult(data=Output(value=input.question), metrics={})

    async def run_pair():
        runtime = AgentRuntime(tools=registry)
        budget = Budget(deadline_seconds=1, max_model_tokens=1, max_cost=0, max_web_requests=1)
        return await asyncio.gather(
            runtime.run(Agent(), AgentInput(question="a", context={}), budget),
            runtime.run(Agent(), AgentInput(question="b", context={}), budget),
        )

    asyncio.run(run_pair())
    assert contexts[0] is not contexts[1]
