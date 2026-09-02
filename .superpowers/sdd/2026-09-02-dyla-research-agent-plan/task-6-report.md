# Task 6 report

## Tests and exact output

TDD red run:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py tests/unit/test_query_planner.py tests/unit/test_analyst.py
3 errors in collection: ModuleNotFoundError for dyla.agent_runtime, dyla.query_planner, and dyla.analyst
```

Focused green run:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py tests/unit/test_query_planner.py tests/unit/test_analyst.py
......                                                                                       [100%]
6 passed in 0.04s
```

Full suite run:

```text
.venv/bin/pytest -q
s............................................................................                [100%]
76 passed, 1 skipped in 0.21s
```

The focused suite was run again after the final accounting/memory changes: `6 passed in 0.06s`.

## Files

Created:

- `src/dyla/agent_runtime.py`
- `src/dyla/query_planner.py`
- `src/dyla/analyst.py`
- `tests/unit/test_agent_runtime.py`
- `tests/unit/test_query_planner.py`
- `tests/unit/test_analyst.py`

## Decisions

- `ToolRegistry` accepts unique named async handlers and exposes `get`, `invoke`, and stable `names` helpers.
- `AgentRuntime` validates budgets before execution, applies the deadline with `asyncio.wait_for`, validates `AgentResult`, checks model-token/cost/web-request metrics, and emits optional lifecycle traces through the existing `TraceWriter` contract.
- `QueryPlanner` performs one bounded planning pass. It normalizes blank/duplicate queries case-insensitively, caps output at `max_subqueries`, preserves purposes, and supports optional structured model output. The fallback planner derives simple entity/date context from supplied memory and the original question.
- `AnalystAgent` keeps model, resolver, memory, search, fetch, index, and embedder dependencies injected. It resolves entities, performs entity-aware memory retrieval/filtering, runs independent searches concurrently, fetches and ingests pages, retrieves filtered evidence, and requests an `AnalystAnswer` using the existing model response-schema contract.
- Tests use local fakes only; no Azure credentials or live services are used.

## Concerns

- The shared domain contract does not define a richer `Agent` protocol or a dedicated planner response model, so the runtime and planner use small local protocols/duck-typed injected dependencies while returning the existing Pydantic models.
- `AnalystAgent.run` currently has no `Budget` parameter because the brief specifies `run(question, run_id)`; budget enforcement is provided by `AgentRuntime` around agents that implement its async `run(AgentInput, ToolRegistry)` contract.
- The analyst currently performs page ingestion sequentially after concurrent search result collection. Independent searches are concurrent as required; fetch/index fan-out can be optimized in a later task if needed.
- Cross-checking is represented by evidence retrieval and structured synthesis, but there is no existing audit-model dependency in the Task 6 interfaces for a separate claim-audit pass.
- Project-wide diagnostics still report unrelated pre-existing issues in `config.py` and `tests/unit/test_azure_models.py`; the new production modules have no errors (only import/style hints where supported).
