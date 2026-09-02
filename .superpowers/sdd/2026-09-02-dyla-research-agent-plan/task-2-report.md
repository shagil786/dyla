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
- `run_id` is used directly as the JSONL filename, matching the required `logs/<run_id>.jsonl` interface. Callers should provide a filesystem-safe run identifier; filename sanitization was intentionally not added because it would alter the specified path contract.
- No real credentials or external services were used.
