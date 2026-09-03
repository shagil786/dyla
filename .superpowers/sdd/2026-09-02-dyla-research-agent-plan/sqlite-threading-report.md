# SQLite Threading Report

Date: 2026-09-03

## Failure reproduced

The regression test `tests/unit/test_memory.py::test_memory_operations_are_safe_from_worker_threads_and_concurrent_access` initially failed with:

```text
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
```

The failure occurred when `asyncio.to_thread(store.search_memory, ...)` invoked a `MemoryStore` connection created on the main thread.

## Fix

`MemoryStore` now:

- opens its shared SQLite connection with `check_same_thread=False`; and
- serializes every public database operation with a per-store `threading.RLock`, including complete write transactions.

All SQL values remain parameterized; the dynamically generated `LIKE` clause still uses placeholders for every term.

## Validation

- Initial `pytest -q ...` attempt: not run; `pytest` was not on `PATH` (exit 127).
- Focused RED test, using `.venv/bin/pytest`: failed as expected with the cross-thread `sqlite3.ProgrammingError` above (exit 1).
- Focused memory suite: `.venv/bin/pytest -q tests/unit/test_memory.py` — **8 passed in 0.08s**.
- Full suite: `.venv/bin/pytest -q` — **130 passed, 1 skipped in 0.91s**.
- Configured `dyla ask --json` smoke test: **not run**. The local `.env` selects live compatible-model and You.com providers, so running it would make external network/API calls and could incur usage/cost; no secrets were printed or inspected.

## Commit

Recorded after validation in the Git commit created for this fix.
