# Task 3 Report: SQLite application memory and deterministic entity resolution

## Status

Implemented Task 3 from `task-3-brief.md` using the existing domain models from `src/dyla/domain.py`. No Azure credentials or Azure services were used. Existing trace/config behavior was not modified.

## Files changed

- `src/dyla/memory.py`
  - Added `MemoryStore` backed by stdlib `sqlite3`.
  - Added idempotent normalized entity upserts with deterministic UUID5 IDs.
  - Added normalized aliases with confidence validation and conflict updates.
  - Added memory record insertion/search returning the existing `MemoryRecord` model.
  - Added claim persistence, citation/source persistence, and optional audit verdict persistence.
  - Added tables for entities, aliases, claims, audit verdicts, sources, research warnings, and memory records.
  - All application SQL values are parameterized; schema setup is idempotent.
- `src/dyla/entities.py`
  - Added Pydantic `ResolvedEntity` with the required fields/status literal.
  - Added deterministic `EntityResolver` with normalized exact lookup, fuzzy candidate scoring, stable tie ordering, and explicit `ambiguous`/`unknown` results.
- `tests/unit/test_memory.py`
  - Added schema, idempotent upsert, exact alias, memory search, claim persistence, and repeated initialization tests.
- `tests/unit/test_entities.py`
  - Added exact alias, fuzzy match, ambiguous match, and unknown match tests.

## TDD test history

1. Initial command from the brief:

   ```text
   pytest tests/unit/test_memory.py tests/unit/test_entities.py -q
   ```

   Output:

   ```text
   sh: pytest: command not found
   ```

2. Re-run using the project virtual environment (RED):

   ```text
   .venv/bin/pytest tests/unit/test_memory.py tests/unit/test_entities.py -q
   ```

   Output: collection failed because both requested production modules were absent:

   ```text
   ModuleNotFoundError: No module named 'dyla.memory'
   ModuleNotFoundError: No module named 'dyla.entities'
   2 errors during collection
   ```

3. First implementation run exposed two test failures: the test helper expected attribute access on a SQLite row, and exact alias resolution retained alias confidence instead of returning exact-match confidence. The test expectation was corrected to use the row mapping, and punctuation normalization plus exact-match handling were implemented.

4. The next run exposed one real implementation defect: a normalized upsert overwrote the original canonical display name with a whitespace-variant input. The conflict update was changed to preserve the existing canonical name.

5. Focused verification:

   ```text
   .venv/bin/pytest tests/unit/test_memory.py tests/unit/test_entities.py -q
   ```

   Output:

   ```text
   9 passed in 0.07s
   ```

6. Full verification:

   ```text
   .venv/bin/pytest -q
   ```

   Output:

   ```text
   23 passed in 0.09s
   ```

7. Diagnostics:

   - `src/dyla/memory.py`: no errors or warnings.
   - `src/dyla/entities.py`: no errors or warnings.

8. Additional command attempted:

   ```text
   python -m compileall -q src tests
   ```

   Output:

   ```text
   sh: python: command not found
   ```

   The project virtual-environment pytest run already exercised import and bytecode compilation for the changed modules.

## Decisions

- SQLite remains application memory only. No Azure AI Search integration was added; searchable evidence chunks remain outside this task.
- `MemoryStore` accepts a filesystem path or `:memory:` and exposes its SQLite connection for controlled inspection/testing.
- Normalization uses Unicode NFKC, case folding, whitespace collapsing, and surrounding ASCII punctuation removal. This makes aliases such as `ACME Corp.` and mentions such as `acme corp` exact matches while retaining canonical display text.
- Entity IDs are deterministic UUID5 values derived from the normalized entity name. Repeated normalized upserts therefore reuse the same ID.
- Exact matches always win and return confidence `1.0`. Fuzzy matches use `difflib.SequenceMatcher`, alias confidence, a fixed threshold, and a fixed ambiguity margin. Ranking ties are broken by canonical name and ID so results are reproducible.
- The resolver accepts `context` to preserve the specified interface, but intentionally does not use it: resolution is deterministic and does not depend on an LLM or non-reproducible context interpretation.
- Claims store citation JSON, sources are deduplicated by source ID, and a supported audit verdict marks the claim memory record as verified. Other verdict statuses remain persisted but do not mark the claim verified.
- Memory search uses parameterized `LIKE` predicates over SQLite application-memory records. Azure AI Search is intentionally deferred for chunk search.

## Concerns and follow-up

- `EntityResolver` currently treats `context` as an interface-preserving input rather than a ranking signal. If future requirements need context-sensitive disambiguation, that behavior should be specified and tested separately because it would change deterministic resolution semantics.
- The memory schema includes `research_warnings` as required, but Task 3 does not specify a public warning-write API; no extra API was invented.
- The requested environment does not expose `pytest` or `python` on `PATH`; validation used `.venv/bin/pytest` successfully.
- No real Azure credentials, network calls, or Azure Search dependencies were introduced.

## Review-fix report — 2026-09-02

### Findings addressed

1. **Canonical fuzzy candidate loss:** `MemoryStore.entity_candidates()` now emits the canonical normalized name as its own candidate row for every entity, then emits aliases separately. `EntityResolver` scores every candidate and retains the highest score per entity, so adding an alias cannot hide a stronger canonical match.
2. **Regression coverage:** Added `test_resolve_considers_canonical_name_after_alias_is_added`, which adds an `IBM` alias and verifies a near-canonical mention resolves to `International Business Machines`.
3. **Research-warning API:** Added `MemoryStore.save_research_warning(warning: str) -> int` and `MemoryStore.read_research_warnings(limit: int = 50) -> list[str]`. Warnings are trimmed, empty values are rejected, IDs are returned for feedback-loop correlation, and reads return newest-first with a bounded limit. Added round-trip/order/limit and empty-warning tests.
4. **Configuration validation:** `EntityResolver` now rejects `fuzzy_threshold` and `ambiguity_margin` values outside the inclusive `[0, 1]` range, with regression coverage for both lower and upper bounds.
5. **Diagnostics correction:** Added an explicit `lastrowid is None` guard for the warning insert so static typing does not treat the returned warning ID as nullable.

### Review-fix TDD history and exact verification

- RED command:

  ```text
  .venv/bin/pytest tests/unit/test_memory.py tests/unit/test_entities.py -q
  ```

  Output:

  ```text
  4 failed, 9 passed in 0.13s
  ```

  The failures were the missing warning API, canonical candidate suppression, and missing resolver configuration validation.

- Focused verification after fixes:

  ```text
  .venv/bin/pytest tests/unit/test_memory.py tests/unit/test_entities.py -q
  ```

  Output:

  ```text
  13 passed in 0.11s
  ```

- Full verification after fixes:

  ```text
  .venv/bin/pytest -q
  ```

  Output:

  ```text
  27 passed in 0.12s
  ```

- Diagnostics after fixes:

  ```text
  src/dyla/memory.py: File doesn't have errors or warnings!
  src/dyla/entities.py: File doesn't have errors or warnings!
  ```

### Review-fix files changed

- `src/dyla/memory.py`
- `src/dyla/entities.py`
- `tests/unit/test_memory.py`
- `tests/unit/test_entities.py`
- This report was appended to `.superpowers/sdd/2026-09-02-dyla-research-agent-plan/task-3-report.md`.

### Remaining concerns

- Warning reads return warning text only; the current brief does not require exposing warning IDs or timestamps on read. The save return ID is available for future feedback-loop correlation.
- `context` remains accepted but unused to preserve deterministic resolution semantics.
- No Azure Search integration or credentials were introduced.
