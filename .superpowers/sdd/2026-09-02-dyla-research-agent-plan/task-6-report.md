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

# Review-fix report

## Findings fixed

1. Added a runtime-owned `BudgetLedger` and `BudgetedModel`; model token/cost totals and web-tool calls are counted during execution and terminal agent metrics are overwritten with ledger values. Web-like registered tools are rejected before exceeding the request cap.
2. Added deterministic insufficient-evidence output and citation-to-evidence validation. Claims with unmapped citations are rejected; weak/medium/low claims require at least two independent source IDs.
3. Preserved `run_id` in planner trace events and recorded original query, deduplicated/capped generated queries, and cap value.
4. Added deterministic weak-claim rejection when independent evidence is absent.
5. Associated fetched pages with entity IDs from their originating query instead of tagging every page with every resolved entity.
6. Converted planner date years to inclusive start/exclusive next-year `SearchFilters` bounds.
7. Moved synchronous planner/model/embedder calls onto worker threads in the async analyst path.
8. Strengthened search concurrency coverage with active-call overlap tracking and a sleep-based overlap proof.
9. Added focused tests covering budgets, traces, evidence emptiness, citation mapping, weak claims, dates, attribution, and concurrency.
10. `ToolRegistry` now accepts async callable objects.

## Fix validation and exact output

Focused review-fix tests:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py tests/unit/test_query_planner.py tests/unit/test_analyst.py
..............                                                                               [100%]
14 passed in 0.26s
```

Full suite:

```text
.venv/bin/pytest -q
s....................................................................................        [100%]
84 passed, 1 skipped in 0.41s
```

Diagnostics after fixes:

- `src/dyla/agent_runtime.py`: no errors or warnings.
- `src/dyla/query_planner.py`: no errors or warnings.
- `src/dyla/analyst.py`: no errors or warnings.
- Existing unrelated diagnostics remain in `config.py`, `tests/unit/test_azure_models.py`, and other pre-existing files.

## Review-fix concerns

- A model provider can only report actual token/cost usage after a synchronous provider call returns; the wrapper prevents calls whose requested token ceiling exceeds remaining budget and rejects over-budget actual usage immediately afterward.
- Web-request classification is based on registered tool names containing `web`, `search`, `fetch`, or `http`; callers should use descriptive names for externally backed tools.
- Date constraints are currently year constraints. More granular dates require extending the shared `ResearchPlan` contract.
