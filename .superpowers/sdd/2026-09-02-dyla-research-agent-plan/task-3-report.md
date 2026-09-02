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
