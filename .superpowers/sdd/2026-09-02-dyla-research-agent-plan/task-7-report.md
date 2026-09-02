# Task 7 Report: Independent Auditor and Reliability/Quality Gates

## Status

Implemented and verified.

## Changes

- Added `src/dyla/auditor.py` with `AuditorAgent.run(answer, run_id)`.
  - Retrieves every cited URL independently; analyst evidence summaries are never used.
  - Deduplicates URLs per claim while preserving citation order.
  - Uses bounded retries and per-fetch/per-comparison timeouts.
  - Produces supported, unsupported, contradicted, and uncited verdicts.
  - Emits partial trace events and fails closed to an unaudited result when the auditor itself fails.
  - Persists claims/verdicts and research warnings through the existing memory contract.
  - Includes a deterministic text comparator fallback for deployments without a judge comparator.
- Added `src/dyla/reliability.py` with `QualityGate` and immutable `QualityResult`.
  - Deterministically checks citations, retrieved sources, matching verdicts, contradictory/unsupported states, orphan verdicts, duplicate verdicts, and non-empty saved traces.
  - Returns `complete`, `incomplete`, or `unaudited` with sorted stable issue messages.
- Added fake-driven tests in `tests/unit/test_auditor.py` and `tests/unit/test_reliability.py`.

## Task 6 integration concern

No `ToolRegistry` or scoped-context code was changed. The parked load-bearing concern remains: concurrent scoped contexts may share mutable runtime state through the registry lineage. Task 7 is injected with independent fetcher/comparator/memory/trace contracts and does not create or mutate tool scopes, so it does not worsen that issue. When integrated into the runtime, auditor instances and their injected state should be owned per run or otherwise protected from concurrent mutation; avoid storing run-specific auditor state on shared registry objects.

## Verification

- Focused: `.venv/bin/pytest -q tests/unit/test_auditor.py tests/unit/test_reliability.py` — 9 passed.
- Full: `.venv/bin/pytest -q` — 102 passed, 1 skipped.
- Compilation: `.venv/bin/python -m compileall -q src` — passed.
- Diagnostics: no errors in `src/dyla/reliability.py`; auditor warnings are limited to intentional broad exception boundaries used to fail safely around arbitrary external adapters and persistence/tracing sinks.

## Concerns

- The comparator contract is intentionally small (`compare(claim, documents)`) and supports a deterministic local fallback; production deployments should inject a separately configured judge/model implementation if semantic comparison beyond exact normalized text is required.
- A timed-out fetch/comparison worker may continue running in the background because cleanup is non-blocking; the caller is not blocked past the configured stage timeout, but injected adapters should be cancellation-safe.

## Review-fix report (2026-09-03)

### Changes

- `QualityGate` now rejects duplicate analyst claim IDs, duplicate verdict IDs, missing verdict coverage, and orphan verdicts without allowing map replacement to hide the duplicate.
- Trace validation now parses every JSONL line as `RunEvent`, checks the requested `run_id` when supplied, and rejects malformed or unknown events. Legitimate runtime, planner, auditor, orchestrator, and quality events are accepted.
- `AuditorAgent` now exposes `audit_state` with explicit `complete`, `partial`, or `failed` status and failure messages for persistence, warning persistence, tracing, and auditor-stage failures.
- Auditor failures preserve verdicts already produced before a later claim fails. The orchestrator forwards audit and persistence/tracing failures into the returned `QualityResult` while preserving the original analyst answer.

### Regression coverage

Added tests for duplicate/incomplete verdict coverage, duplicate claim IDs, run-bound and schema/event-aware trace validation, persistence/tracing failure state, and partial verdict preservation after a later auditor failure.

### Verification

- Focused: `.venv/bin/pytest -q tests/unit/test_auditor.py tests/unit/test_reliability.py tests/unit/test_orchestrator.py` — 19 passed.
- Full: `.venv/bin/pytest -q` — 117 passed, 1 skipped.
- Compilation: `.venv/bin/python -m compileall -q src` — passed.

### Concerns

- Trace event validation uses the repository’s current event vocabulary; adding a new producer event requires adding it to the quality-gate allowlist.
- Adapter exceptions remain intentionally broad at external boundaries, but they are now surfaced in audit/quality state rather than silently discarded.
