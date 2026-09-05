# P5 memory-durability proof of record (claim-ID collision + probe pollution)

Date: 2026-09-05. Branch: `arena/01a070ee-dyla`. All runs: offline fixtures,
`uv run`, repo tree code.

## What was found, and how

Inspecting `dyla.db` after a full eight-question suite run (the user instruction
for this session explicitly asked that SQLite updates be verified locally):

    uv run python scripts/run_suite.py --no-reuse
    uv run python -c "import sqlite3; ..."   # dump claims / audit_verdicts

`claims` held **4 rows**, not ~28. Worse, the rows were lies:

| id | text |
|---|---|
| c1 | Nithin Kamath is the chief executive officer of Infosys. |
| c2 | Infosys was founded in 2010 by Nithin Kamath, who remains chief executive officer. |
| c3 | The company announced a secondary listing on the Singapore Exchange in the same quarter. |
| c4 | Kailash Nadh is the chief technology officer of Infosys and holds a PhD in computer scienc… |

Two independent defects, both in the local-SQLite path:

1. **Claim-ID collision across runs.** Claim IDs are per-answer (`c1`..`cN`):
   `OfflineModel` numbers from 1 in every answer, and a live model does the
   same. `save_claim` upserts by bare ID, so each run overwrote the previous
   run's rows in `claims`, `audit_verdicts` and `memory_records`. Durable
   memory held only the latest answer, and the P1-5/P3-4 audit-feedback loop
   could never see further back than one run.
2. **Seeded-defect probe pollution.** `run_seeded_defect_audit` calls the real
   `AuditorAgent.run`, which persisted every probe verdict. The planted lies
   above (a `swapped_entity` batch and a `fabricated_claim`) overwrote the
   real Q8 claims under their bare IDs. A measurement probe was writing to the
   system under measurement.

## The fix

- `dyla.memory.memory_claim_id(run_id, claim_id)`: storage keys are
  run-namespaced (`<run_id>:c1`). Applied at both write sites (auditor
  `_persist` and the orchestrator's idempotent second write) by re-keying
  copies; answers, traces and verdicts keep the bare IDs. No production reader
  SELECTs these tables by ID (`search_memory` full-scans), so no reader
  changes. Old bare-ID rows coexist harmlessly; no migration needed.
- `AuditorAgent.run(..., persist=True)`: `persist=False` audits read-only
  (no claims, no warnings). `scripts/run_suite.py` passes it for the seeded
  audit. Probes still read live memory (the misattribution check needs entity
  knowledge) but write nothing.
- New trace event `claim_corroborated` (accepted/source/checked/detail on every
  cross-check): found while reconciling fetch counters — accepted
  cross-checks previously left no event, 24 fetches per run with no record.

## Verification

    uv run pytest -q                              -> 319 passed (was 302)
    scratch-equivalent: run_suite.py [--no-reuse] -> 8/8 + seeded 20/20 both modes

Post-fix `dyla.db` (reuse run): **28 claims, 28 supported, 8 distinct run
prefixes, 0 fabricated rows, 0 warnings.**

Behaviour deltas from memory that actually accumulates (all measured, all in
the committed artifacts): `memory_hits` 7 → 61 per suite (both modes); the
memory-fed planner now expands entity-prefixed subqueries, so retrieval
searches rise in both modes (9 → 19 baseline, 4 → 6 reuse) while reuse still
skips every Q5–Q8 search (13 → 0); token savings move 13.5% → 12.7% (all
eight) and 27.8% → 24.1% (Q5–Q8). Rejected-claim sets are unchanged from the
P4-2 proof (no-reuse 3, reuse 4). P3-3 re-run after the fix: byte-identical
8/8 both modes, `runlogs/P3-3-result-*.txt` unchanged.

Red proof for the new tests (fix stashed, tests kept):

    pytest tests/unit/test_auditor.py -k "both_persist or persist_false"
        -> 2 failed (second run overwrote the first; probe rows persisted)
    pytest tests/unit/test_analyst.py -k "cross_check_is_traced"
        -> 2 failed (no claim_corroborated event without the fix)
    pytest tests/unit/test_orchestrator.py -k namespaced -> 1 failed
    (restored) pytest -q -> 319 passed
