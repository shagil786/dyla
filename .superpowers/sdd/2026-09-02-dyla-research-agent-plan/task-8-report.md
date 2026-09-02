# Task 8 Report: Orchestrator and CLI Composition

## Status

Implemented and verified.

The named brief describes the provider-adapter slice, which was already present at commit `7db93af` as stated in the request. This report covers the requested follow-on composition: analyst → auditor → memory → trace → quality, the complete CLI command tree, configuration-driven provider construction, and the parked Task 6 runtime-context fix.

## Changes

- Added `src/dyla/orchestrator.py`.
  - Exposes `RunOrchestrator.ask(question) -> RunResult`.
  - Generates a safe run ID, initializes memory, preserves the original `AnalystAnswer`, runs the independent auditor, persists claims/verdicts, writes orchestration trace events, applies `QualityGate`, and returns metrics plus trace path.
  - Keeps quality states fail-closed (`complete`, `incomplete`, or `unaudited`).
- Replaced the placeholder `src/dyla/cli.py` with a Typer CLI containing:
  - `dyla ask`
  - `dyla analyst`
  - `dyla audit`
  - `dyla evaluate`
  - `dyla memory list`
  - `dyla replay`
  - Human-readable output and `--json` output where applicable.
  - Runtime composition through `load_settings()` and `build_search_provider(settings)`; You.com remains limited to web search/page retrieval while Azure adapters provide model, embeddings, and vector search.
  - Replay reads a saved JSONL trace and makes no model or web calls.
- Fixed the parked Task 6 issue in `src/dyla/agent_runtime.py`.
  - Each independent `AgentRuntime.run()` now receives a fresh mutable runtime context.
  - Nested `ToolRegistry.scoped()` handles continue to share their parent run’s context.
- Added fake-backed tests:
  - `tests/unit/test_orchestrator.py`
  - `tests/unit/test_runtime_isolation.py`
  - `tests/integration/test_cli.py`
  - Added package markers under `tests/unit/` and `tests/integration/` so both existing and new `test_cli.py` modules collect safely.
- Added Typer to the project dependencies in `pyproject.toml`.

## TDD evidence

- Red: focused tests initially failed because `dyla.orchestrator` and the CLI command/dependency were absent; the isolation test targeted the shared mutable registry context.
- Green: focused tests passed after the minimal implementation and context allocation fix.

## Verification

- Focused orchestration/runtime: `.venv/bin/pytest tests/unit/test_orchestrator.py tests/unit/test_runtime_isolation.py -q` — 3 passed.
- Focused CLI: `.venv/bin/pytest tests/integration/test_cli.py -q` — 3 passed.
- Runtime regression suite: `.venv/bin/pytest tests/unit/test_agent_runtime.py -q` — 12 passed.
- Full offline suite: `.venv/bin/pytest -q` — 104 passed, 1 skipped.

## Concerns

- `dyla evaluate` currently provides the command surface and a clear not-configured response; the eight-question evaluation harness remains the subsequent planned task.
- CLI commands that construct live adapters intentionally require the configured environment and credentials; all tests use fakes and do not make live requests.
- Metrics are returned with the stable schema, but detailed model/search/fetch aggregation remains a follow-on enhancement once the evaluation harness consumes per-stage telemetry.
- The project virtualenv required installing the newly declared Typer dependency before CLI tests could run.

## Task 8 review-fix report

### Fixes

- `dyla analyst` now builds and invokes `AnalystAgent` directly, without invoking the auditor, orchestrator `ask`, persistence, or quality flow.
- `dyla audit` and `dyla replay` now accept an existing JSONL trace/artifact path or a run ID resolved as `logs/<run-id>.jsonl`; malformed artifacts fail with a clear CLI parameter error.
- `dyla evaluate` now runs the default eight-question suite and writes `reports/evaluation.json` and `reports/evaluation.md`. The evaluation runner remains injectable for offline tests and records complete/failed quality outcomes.
- Orchestrator metrics now aggregate numeric stage metrics and wall-clock duration into the shared `Metrics` contract. Analyst and auditor expose nonzero model/tool counters where work occurs.
- Provider factory composition and independent runtime context isolation were preserved.

### TDD evidence

- Red: new CLI and orchestrator regressions failed because the analyst builder/evaluation flow/path resolution were absent and metrics were hard-coded to zero.
- Green: focused CLI/orchestrator/integration tests passed after the minimal fixes.

### Verification

- `.venv/bin/pytest tests/unit/test_cli.py tests/unit/test_orchestrator.py tests/integration/test_cli.py -q` — 9 passed.
- `.venv/bin/pytest -q` — 108 passed, 1 skipped.
- Project diagnostics are clean for the modified CLI, evaluation, analyst, and orchestrator paths; pre-existing auditor broad-exception warnings remain outside this fix.

### Concerns

- Running the default evaluation suite against live adapters still requires the configured Azure/You credentials and search service; tests use fakes and make no live requests.
- Evaluation questions are the planned default suite in this repository because no separate Task 9 implementation or question-set file was present.

## Task 8 review-fix report (metrics and trace validation)

### Fixes

- `RunOrchestrator` now snapshots component metrics before each run and aggregates only the post-run delta, so reused analyst/auditor instances produce isolated `Metrics` values for each evaluation question.
- `_read_trace()` now requires every non-empty JSONL line to decode to a JSON object and raises a clear `typer.BadParameter` when it does not.

### TDD evidence

- Red: the reused-orchestrator regression observed growing metrics on the second run, and the non-object JSONL regression did not raise the promised CLI error.
- Green: both regressions and the existing CLI/orchestrator tests pass after the focused changes.

### Verification

- `.venv/bin/pytest tests/unit/test_orchestrator.py::test_orchestrator_aggregates_stage_metrics tests/unit/test_orchestrator.py::test_reused_orchestrator_reports_metrics_per_run tests/unit/test_cli.py::test_read_trace_rejects_non_object_json_values tests/unit/test_cli.py tests/unit/test_orchestrator.py -q` — 12 passed.
- `.venv/bin/pytest -q` — 110 passed, 1 skipped.
- Final diagnostics are clean for the changed CLI, orchestrator, and regression-test files; `git diff --check` passed.

### Concerns

- Metric isolation relies on stage metrics being monotonic within an individual run; the concrete analyst/auditor counters follow that contract.

## Task 8 review-fix report (metric reset handling and ask JSON)

### Fixes

- Metric aggregation now handles counters that decrease because a component reset or supplied already-per-run values: it uses the current value in that case and clamps every contribution to zero, preventing negative `Metrics` fields.
- `dyla ask --json` now includes the computed `RunResult.metrics` object alongside the answer, verdicts, quality, and trace path.

### TDD evidence

- Red: reset-style counters produced negative metrics, and the CLI JSON regression found the missing `metrics` field.
- Green: both regressions and the existing CLI/orchestrator tests pass after the focused changes.

### Verification

- `.venv/bin/pytest tests/unit/test_orchestrator.py::test_reset_style_component_metrics_never_become_negative tests/unit/test_cli.py::test_ask_json_includes_computed_metrics tests/unit/test_cli.py tests/unit/test_orchestrator.py -q` — 13 passed.
- `.venv/bin/pytest -q` — 112 passed, 1 skipped.
- Final diagnostics are clean for changed production and test files; `git diff --check` passed.

### Concerns

- A decreasing counter is interpreted as a reset/per-run value rather than a negative delta; this intentionally favors nonnegative, useful telemetry over attributing a reset as work subtraction.
