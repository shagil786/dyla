# Task 2 Report: Domain schemas and deterministic run tracing

## Status

Implemented Task 2 from the research-agent plan. The shared Pydantic domain contracts and deterministic JSONL trace writer are present, tested, and ready for later tasks.

## Files changed

- Created `src/dyla/domain.py`
  - Added all 16 requested Pydantic models: `Citation`, `Claim`, `AnalystAnswer`, `AuditVerdict`, `RunEvent`, `Document`, `EvidenceChunk`, `Evidence`, `SearchHit`, `SearchFilters`, `MemoryRecord`, `Budget`, `AgentInput`, `AgentResult`, `ResearchPlan`, and `Metrics`.
  - `AuditVerdict.status` uses the requested `Literal` values.
  - `SearchFilters` uses the requested optional fields with `None` defaults.
  - `AgentResult.data` accepts a Pydantic `BaseModel` and carries a metrics dictionary.

- Created `src/dyla/tracing.py`
  - Added `TraceWriter.append(event: RunEvent) -> None`.
  - Creates `logs/` beneath the configured root when needed.
  - Appends one JSON object per line to `logs/<run_id>.jsonl`.
  - Serializes Pydantic models in JSON mode, sorts object keys, and uses compact separators for deterministic bytes.
  - Recursively redacts dictionary keys whose names contain `api_key`, `authorization`, `token`, or `secret`, case-insensitively. Redaction covers nested dictionaries and dictionaries inside lists.

- Created `tests/unit/test_domain.py`
  - Covers construction of the shared model shapes.
  - Verifies the audit status literal rejects invalid values.
  - Verifies required fields are not silently defaulted.

- Created `tests/unit/test_tracing.py`
  - Verifies exact deterministic JSONL output and UTC datetime serialization.
  - Verifies repeated appends produce identical lines.
  - Verifies log-directory creation and recursive sensitive-key redaction.

- Preserved `src/dyla/cli.py` and the existing `dyla = "dyla.cli:app"` console entry point in `pyproject.toml` unchanged.

## TDD evidence

### RED

Command:

```text
.venv/bin/pytest -q tests/unit/test_domain.py tests/unit/test_tracing.py
```

Output before implementing the production modules:

```text
============================================== ERRORS ==============================================
____________________________ ERROR collecting tests/unit/test_domain.py ____________________________
E   ModuleNotFoundError: No module named 'dyla.domain'
___________________________ ERROR collecting tests/unit/test_tracing.py ____________________________
E   ModuleNotFoundError: No module named 'dyla.domain'
!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```

The tests failed during collection because the requested modules did not yet exist.

### GREEN

After implementing the modules and correcting the expected sorted-key order in the exact-output assertion:

Command:

```text
.venv/bin/pytest -q tests/unit/test_domain.py tests/unit/test_tracing.py
```

Output:

```text
.....                                                                                        [100%]
5 passed in 0.12s
```

Final full-suite verification:

Command:

```text
.venv/bin/pytest -q
```

Output:

```text
........                                                                                     [100%]
8 passed in 0.08s
```

## Schema and design decisions

- Models use standard Pydantic `BaseModel` behavior without extra permissive defaults, so required contract fields remain required.
- Nullable fields such as citation titles, publication dates, and trace duration/error are explicitly typed as `str | None` or `datetime | None` but remain required unless the brief specified a default. This distinguishes an explicit `null` from an omitted field.
- `SearchFilters` is the exception because the brief explicitly specifies `None` defaults for all four filters.
- Trace serialization uses `model_dump(mode="json")` so datetimes and nested Pydantic-compatible values are JSON-safe before redaction.
- `json.dumps(..., sort_keys=True, separators=(",", ":"))` provides stable key ordering and compact output. Each append adds exactly one newline-terminated JSON object.
- Sensitive matching is substring-based and case-insensitive, so keys such as `client_secret_value`, `my_token_count`, and `Authorization` are redacted as required by “keys matching” the named patterns.
- Redaction happens on the serialized event record immediately before writing, leaving the in-memory `RunEvent` unchanged.

## Concerns

- Project-wide diagnostics still report a pre-existing error in `src/dyla/config.py` and a warning in `src/dyla/cli.py`; neither file was changed because they are outside Task 2. The new production files and both new test files have no diagnostics.
- No real credentials or external services were used.

## Review-fix report (2026-09-02)

### Findings addressed

1. `TraceWriter.append()` now sanitizes the complete serialized event recursively, not only payload values. It handles dictionaries, lists, tuples, and strings, including secret-like text in `error`, `component`, `event`, and nested values. Key names matching `api_key`, `authorization`, `token`, or `secret` are still replaced with `[REDACTED]`; string assignments such as `authorization=real-secret` have their value replaced as well.
2. `run_id` is validated as a safe filename component before creating or opening a file. Only IDs matching `[A-Za-z0-9][A-Za-z0-9._-]*` are accepted, preserving ordinary IDs while rejecting traversal and absolute path forms with `ValueError`.
3. Regression tests cover secret text in `error`, nested tuple values, path traversal IDs, and absolute IDs.
4. Contract tests now verify every allowed `AuditVerdict.status` value in addition to the existing invalid-status and required-field checks.

### Review-fix TDD evidence

#### RED

Command:

```text
.venv/bin/pytest -q tests/unit/test_tracing.py
```

Output after adding the regression tests but before the tracing fix:

```text
..FF                                                                                         [100%]
============================================= FAILURES =============================================
... assert 'real-secret' not in ...
... Failed: DID NOT RAISE <class 'ValueError'>
2 failed, 2 passed in 0.06s
```

The failures reproduced the unredacted `error` string and accepted traversal ID.

#### GREEN focused verification

Command:

```text
.venv/bin/pytest -q tests/unit/test_domain.py tests/unit/test_tracing.py
```

Output:

```text
...........                                                                                  [100%]
11 passed in 0.06s
```

#### GREEN full-suite verification

Command:

```text
.venv/bin/pytest -q
```

Output:

```text
..............                                                                               [100%]
14 passed in 0.06s
```

Diagnostics for `src/dyla/tracing.py`, `tests/unit/test_tracing.py`, and `tests/unit/test_domain.py` report no errors or warnings.

### Review-fix concerns

- The safe run-ID policy intentionally rejects IDs containing path separators or characters outside the conservative filename-component allowlist; callers using such IDs must normalize them before constructing `RunEvent`.
- The pre-existing project-wide diagnostics in `src/dyla/config.py` and `src/dyla/cli.py` remain outside this fix scope.
