# P4-2 proof of record (cross-check not keyed on self-reported confidence)

Date: 2026-09-05. All runs: offline fixtures, fresh DB per mode, repo tree code copied verbatim.
Commands executed:

    git status        -> 5 files dirty (analyst.py, verification.py, 3 test files) on HEAD 1eda644
    .venv/bin/pytest -q                       -> 298 passed (baseline was 283 at 1eda644)
    (red proof) git show HEAD:src/dyla/{analyst,verification}.py | restore-less revert
        pytest tests/unit/test_analyst.py     -> 6 failed (new corroboration tests)
        pytest tests/unit/test_verification.py -> collection error (corroborates/on_topic missing)
        pytest tests/integration/test_trace_completeness.py -> 1 failed (reason-code test)
    (restored) .venv/bin/pytest -q            -> 298 passed
    scratch: for v in base(1eda644) p42(HEAD+worktree); run_suite.py [--no-reuse]
        -> 8/8 complete + seeded-defect audit 20/20 in every variant


| variant | code | mode | questions | seeded by class (caught/planted) | totals |
|---|---|---|---|---|---|
| baseline-no-reuse | 1eda644 | no-reuse | 8/8 complete | dropped_citation:4/4/fabricated_claim:4/4/inflated_figure:4/4/negated_claim:4/4/swapped_entity:4/4 | searches=9 fetches=67 mem_hits=8 |
| baseline-reuse | 1eda644 | reuse | 8/8 complete | dropped_citation:4/4/fabricated_claim:4/4/inflated_figure:4/4/negated_claim:4/4/swapped_entity:4/4 | searches=4 fetches=51 mem_hits=10 |
| p42-no-reuse | HEAD+worktree | no-reuse | 8/8 complete | dropped_citation:4/4/fabricated_claim:4/4/inflated_figure:4/4/negated_claim:4/4/swapped_entity:4/4 | searches=9 fetches=64 mem_hits=7 |
| p42-reuse | HEAD+worktree | reuse | 8/8 complete | dropped_citation:4/4/fabricated_claim:4/4/inflated_figure:4/4/negated_claim:4/4/swapped_entity:4/4 | searches=4 fetches=47 mem_hits=7 |

## What P4-2 changes end-to-end (claim level, fresh-DB suite runs)

Corroboration metrics (analyst, summed over the 8 questions):
  baseline-no-reuse: searches=0 fetches=0 claims_rejected=0
  p42-no-reuse: searches=19 fetches=32 claims_rejected=3

Final confirmation run on the exact committed tree (after docs edits; code identical):
    .venv/bin/pytest -q                              -> 298 passed
    scratch run_suite.py (no-reuse | reuse)          -> 8/8 + seeded 20/20 both modes
    p42 no-reuse: corroboration_searches=19 fetches=32 claims_rejected=3 claims_kept=29
    p42 reuse   : corroboration_searches=20 fetches=32 claims_rejected=4 claims_kept=28
Claim-level rejects (fresh DB, p42):
    no-reuse: q06 c1 + q08 c4 "Infosys ... revenue of 1,53,670 crore ..." (planted wrong
              figure; baseline carried both as supported), q04 c4 "The round valued
              Zepto at 5 billion dollars." (true, single source; no other corpus page)
    reuse   : q04 c4 and q07 c4 (5 billion dollars), q06 c4 (Wipro net profit
              13,135 crore), q08 c3 ("He joined Zerodha in 2013.")
Baseline (1eda644) rejected none of these (0/0/0 metrics absent pre-P4-2); the auditor
then verified every kept claim supported, so answer content is limited by the same
honest rule: a single cited source is not enough for a figure no independent page states.

Post-everything confirmation (HEAD 07542b8, after P4-4/P4-3/P3-3 commits; fresh
scratch copy of the committed tree):
    scratch run_suite.py (no-reuse | reuse) -> 8/8 + seeded 20/20 both modes
    .venv/bin/pytest -q                     -> 302 passed
Seeded-defect audit before/after the P4-2 change: 20/20 -> 20/20 (baseline
1eda644 and P4-2 runs measured identically, by class 4/4 across all five
defect classes; see table above).
