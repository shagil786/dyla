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

# Second review-fix report

## Findings fixed

1. `AgentRuntime` now treats the supplied `ToolRegistry` as a reusable template. Every run receives a scoped copy with a private `BudgetLedger` and temporary `BudgetedModel`; both wrappers are cleared in `finally`, and the template model remains clear.
2. Tool categories are explicit (`generic` or `web`) rather than inferred from names. Both `get()` and `invoke()` return/use guarded handlers, so direct handler access cannot bypass web accounting. Model access is only exposed through the run-scoped budgeted model.
3. Analyst synthesis now rejects arbitrary narrative when the model returns no claims. Invalid citations or claims rejected for insufficient independent evidence produce deterministic `Insufficient evidence.` output with limitations.
4. Non-year date constraints are reported as explicit limitations instead of being silently discarded; year constraints continue to produce inclusive-start/exclusive-next-year filters.

## Tests and exact output

Focused review-fix tests:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py tests/unit/test_query_planner.py tests/unit/test_analyst.py
.................                                                                            [100%]
17 passed in 0.36s
```

Full suite:

```text
.venv/bin/pytest -q
s.......................................................................................     [100%]
87 passed, 1 skipped in 0.50s
```

Diagnostics after fixes:

- `src/dyla/agent_runtime.py`: no errors or warnings.
- `src/dyla/analyst.py`: no errors or warnings.
- Existing unrelated diagnostics remain in pre-existing project files.

## Second review-fix concerns

- A tool must be registered with `category="web"` to consume the web-request budget; unclassified tools are intentionally treated as generic rather than guessed from names.
- Direct access to the original model object captured by arbitrary user code cannot be intercepted; the runtime-owned model boundary is `tools.model`, and agents must use that injected wrapper.
- The shared `ResearchPlan.date_constraints` contract is still string-based; common non-year formats are surfaced as limitations rather than applied as potentially incorrect filters.

# Third review-fix report

## Findings fixed

1. Budgeted runs now reject registries containing any unclassified (`generic`) tool before the agent starts. Web tools must use the explicit `category="web"` registration contract; no name heuristics are used.
2. Analyst claims with zero citations are rejected before mapping/confidence checks. If all claims are empty or rejected, the answer is deterministically `Insufficient evidence.` and the model narrative is not preserved.

## Tests and exact output

Focused review-fix tests:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py tests/unit/test_query_planner.py tests/unit/test_analyst.py
...................                                                                          [100%]
19 passed in 0.40s
```

Full suite:

```text
.venv/bin/pytest -q
s.........................................................................................   [100%]
89 passed, 1 skipped in 0.55s
```

Diagnostics after fixes:

- `src/dyla/agent_runtime.py`: no errors or warnings.
- `src/dyla/analyst.py`: no errors or warnings.

## Third review-fix concerns

- Existing callers that use `ToolRegistry.register()` without a category can continue using the registry outside a budgeted run, but must specify `category="generic"` or `category="web"` appropriately before invoking `AgentRuntime`.
- The runtime intentionally fails closed for any generic tool in a budgeted run because the existing registration contract cannot infer whether an unclassified handler performs web I/O.

# Fourth review-fix report

## Finding fixed

`ToolRegistry.register()` now fails closed at registration: `category` must be explicitly set to the supported `"generic"` or `"web"` value. Omitted categories and unsupported values such as `"internal"` raise `ValueError`, so omission cannot be confused with explicit generic classification. Existing callers/tests were updated to use explicit categories.

## Tests and exact output

TDD red run before the runtime change:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py
...FF......                                                                                  [100%]
2 failed, 9 passed in 0.09s

Failures:
- test_tool_registry_rejects_invalid_category_at_registration: DID NOT RAISE
- test_tool_registry_requires_explicit_category_at_registration: DID NOT RAISE
```

Focused suite after the fix:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py tests/unit/test_query_planner.py tests/unit/test_analyst.py
......................                                                                       [100%]
22 passed in 0.45s
```

Full suite after the fix:

```text
.venv/bin/pytest -q
s........................................................................................... [ 98%]
.                                                                                            [100%]
92 passed, 1 skipped in 0.55s
```

Diagnostics:

- `src/dyla/agent_runtime.py`: no errors or warnings.
- The focused test file retains unrelated pre-existing diagnostics: import formatting, unused `time`, and a broad `BaseModel.value` type warning.

# Fifth review-fix report

## Finding fixed

`ToolRegistry.scoped()` previously copied only handlers, so a scope created during a budgeted run lost the active ledger and its web-request guard. Scoped web-tool invocations could therefore bypass the per-run request budget. The public contract now preserves the active run ledger/model wrapper through further scopes, while each `AgentRuntime.run()` still owns a private ledger and clears its run-scoped wrappers during cleanup.

The regression test invokes a scoped web tool under a zero-request budget and verifies rejection plus zero recorded requests; concurrent-run coverage continues to verify ledger isolation and template cleanup. Explicit tool-category validation remains unchanged.

## Pre-fix reproduction

```text
.venv/bin/python - <<'PY' ...
root_ledger=True scoped_ledger=False result=allowed
```

## Tests and exact output

TDD red run before the runtime change:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py -k scoped_web_tool_preserves_active_budget_ledger
F                                                                                            [100%]
============================================= FAILURES =============================================
_______________________ test_scoped_web_tool_preserves_active_budget_ledger ________________________

E       Failed: DID NOT RAISE <class 'ValueError'>

1 failed, 11 deselected in 0.06s
```

Focused suite after the fix:

```text
.venv/bin/pytest -q tests/unit/test_agent_runtime.py tests/unit/test_query_planner.py tests/unit/test_analyst.py
.......................                                                                      [100%]
23 passed in 0.37s
```

Full suite after the fix:

```text
.venv/bin/pytest -q
s........................................................................................... [ 97%]
..                                                                                           [100%]
93 passed, 1 skipped in 0.54s
```

Diagnostics after the fix:

- `src/dyla/agent_runtime.py`: no errors or warnings.

## Files changed

- `src/dyla/agent_runtime.py`
- `tests/unit/test_agent_runtime.py`

## Fifth review-fix concerns

- A manually created scope outside a budgeted runtime has no ledger and remains unbudgeted by design; budget enforcement applies when the runtime injects its run-owned ledger.
- Nested scopes share the active run wrappers intentionally, while concurrent runs receive distinct scoped registries and ledgers.

## Files changed

- `src/dyla/agent_runtime.py`
- `tests/unit/test_agent_runtime.py`
