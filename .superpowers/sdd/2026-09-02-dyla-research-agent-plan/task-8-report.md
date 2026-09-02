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
