# Dyla — Verified Fix Backlog

**Date:** 2026-09-05
**Branch:** `arena/01a06e12-dyla`
**Baseline:** `main` @ `95584a7`
**Companion doc:** `docs/PROJECT_STATUS.md` (full diagnostic)

Every item below was verified by execution, not by reading. Where a prior gap
analysis and a measurement disagree, the measurement is recorded and the command
that produced it is cited.

---

## Part 1 — Reconciling the prior gap analysis

The gap analysis supplied alongside this work reports four gaps "✅ FIXED with
code changes" in commit `95584a7`. I tested all four. **None of them function.**
Three further statements in that document could not be reproduced. This is not a
criticism of the intent behind those changes — the four things chosen are the
right four things — but the code as committed does not do what the summary says.

| # | Claim in the gap analysis | Measured reality | How verified |
|---|---|---|---|
| 1 | Auditor "detects when claim appears in only some fetched sources vs all" | The comparator matches the **entire claim string** as a substring of the document. Real prose never matches, so the disagreement branch is unreachable and every claim returns `unsupported`. | Ran `_TextComparator().compare()` with a paraphrased-but-supporting source → `('unsupported', 'claim text was not found…')` |
| 2 | Cost in rupees: "`cost_in_rupees` column… rupees column in cost summary and trend" | The module containing it **did not compile** on the declared Python floor, so the feature could never execute. The rate `RUPEES_PER_ADAPTER_UNIT = 0.8` is a self-labelled placeholder, not a price. | `dyla --help` → `SyntaxError`; `pytest` → 3 collection errors |
| 3 | "Two-minute wall clock ceiling… enforced" | Checked *after* each stage returns. Nothing is cancelled. A 10-minute stage runs to completion and then gets a note. | `orchestrator.py:47-60` — `if time.monotonic() - started > …: self._run_issues.append(...)` |
| 4 | "`_was_previously_rejected()` rejects new claims containing key phrases from prior rejected claims" | The function is **never called**. Its input list is built from `record.verified`, which `memory.py` sets to `status == "supported"` — so the variable named `prior_rejected_claims` holds the auditor's *approved* claims. Wired up as written, it would suppress the best claims. | `grep -rn "_was_previously_rejected"` → definition only; `memory.py:save_claim` → `int(verdict.status == "supported")` |
| 5 | "Test impact: 218 passed, 11 pre-existing failed, 1 skipped — zero new failures" | Not reproducible. On the declared floor the suite ran **0 tests**. With the blocker fixed it is **210 passed, 1 skipped, 0 failed**. The repo contains 199 test functions; 218 + 11 = 229 exceeds what this checkout can collect even with parametrisation. There are no "11 pre-existing failures". | `pytest -q` before and after the P0 fix |
| 6 | "Slot queries (`_slot_query`), per-entity evidence selection (`_select_evidence`), content attribution (`_entity_ids_from_content`) all functional" | **None of these three identifiers exist anywhere in the repository.** `AnalystAgent` has exactly six methods: `__init__`, `run`, `_trace`, `_filters`, `_synthesize`, `_citation_maps`. | `grep -rn "_slot_query\|_select_evidence\|_entity_ids_from_content" src/ tests/` → no matches |
| 7 | "Mark claims supported/unsupported/contradicted/uncited — `AuditVerdict.status` covers all four" | The *enum* has four values, but the **default comparator can only ever emit two** (`supported`, `unsupported`). It contains no path to `contradicted`. The deterministic auditor is structurally incapable of detecting a contradiction — the single most important thing an auditor does. | `_TextComparator` body contains zero occurrences of `contradicted` |

**Takeaway for the write-up.** The most valuable paragraph this project can contain
is an honest account of #1 and #4: two features that were written, committed,
described as working, and were not. The brief explicitly rewards "a weakness found
and named before we found it."

### Correcting the headline number

The gap analysis concludes "the core agent architecture… covers ~70% of Problem 3
requirements." That figure counts features by their presence in the source tree.
Counting by *demonstrated behaviour* — which is what the brief grades, since it
asks for run logs — the honest number before today's fix was **0%: nothing could
be executed at all.** After the P0 fix the runnable core is real, but every
"take it further" item remains unearned.

---

## Part 2 — The backlog

Status key: `DONE` · `TODO` · `DECIDE` (needs a call from you before work starts)

### P0 — Restore the gate

The brief stops reading if a clean checkout does not run.

| ID | Item | Status |
|---|---|---|
| **P0-1** | Remove PEP 701 f-strings from `evaluation.py` (lines 129, 141, 316 + cost table) via a `_md_escape()` helper | **DONE** |
| **P0-2** | Regression test: sweep-import every `dyla.*` module, so a syntax error in any module fails a test instead of silently aborting collection | **DONE** |
| **P0-3** | CI on a 3.11 + 3.12 matrix, asserting module imports, `dyla --help`, and `pytest` | **DONE** |

Result: `pytest -q` → **210 passed, 1 skipped, 0 failed**. `dyla --help` lists all six commands.

### P1 — Make the auditor mean something

An auditor that rejects everything scores the same as one that approves everything.

| ID | Item | Why | Effort |
|---|---|---|---|
| **P1-1** | Replace `_TextComparator`'s whole-claim substring match with real support scoring: extract numbers, dates, named entities and units from the claim, require the material ones to appear in the source, and score partial overlap | Today a source that plainly supports a claim is marked unsupported. This is the root cause of #1 and #7 above. | M |
| **P1-2** | Give the deterministic comparator a `contradicted` path — detect a claim's numeric/date/entity slot filled with a *different* value in the source (e.g. claim says ₹1,53,670 cr, source says ₹1,22,000 cr) | Without this the auditor cannot catch the exact failure it exists to catch. | M |
| **P1-3** | Rewrite `tests/unit/test_auditor.py` fixtures to use real paraphrased prose | Current fixtures assert claim `"supported"` against document `"source"`. They pass under a matcher that is wrong, which is why the bug shipped. | S |
| **P1-4** | Decide the default: promote `ModelComparator` to default and relabel `local` as an explicit offline stub, or keep `local` default once P1-1/P1-2 make it credible | `.env.example` ships `DYLA_AUDITOR_PROVIDER=local`, so the broken comparator is what a fresh checkout runs. | `DECIDE` |
| **P1-5** | Fix the inverted `verified` condition in `analyst.py` and actually call `_was_previously_rejected` | The feedback loop is the brief's "closest thing to what we actually build". | S |
| **P1-6** | Enforce the 120s ceiling with `asyncio.wait_for` and a budget that shrinks across stages, instead of a post-hoc note | The ceiling exists to force parallelism and expose sequential chains; observing a breach exposes nothing. | M |
| **P1-7** | Resolve the orphaned `agent_runtime.py`: wire `AgentRuntime`/`BudgetLedger` into the real pipeline, or delete it and its 224 lines of tests | 185 lines implementing exactly the budget + deadline machinery P1-6 needs, imported by nothing. Shipping it disconnected while the spec claims both agents share it is worse than not having it. | `DECIDE` |

### P2 — The deliverables that are actually graded

The brief: *"Your run logs matter as much as your answers here."*

| ID | Item | Why | Effort |
|---|---|---|---|
| **P2-1** | Run the eight-question suite live, end to end | Currently exercised only through mocked unit tests. The suite design is good; it has never been executed. | M |
| **P2-2** | Commit `logs/` and `reports/` (un-ignore, or add a `reports/committed/` path) | Both are gitignored and absent. The brief's gate requires logs to be in the repo. | S |
| **P2-3** | Replace `RUPEES_PER_ADAPTER_UNIT = 0.8` with real per-1K-token pricing for the configured model | "Cost per question in tokens and rupees" needs an actual price, not an internal unit × a placeholder. | S |
| **P2-4** | Run the auditor over the analyst's answers and write up **what it caught**, including false negatives | Explicitly requested. Requires P1-1 to produce meaningful verdicts. | M |
| **P2-5** | Promote planner subqueries, search failures, retries and bail-outs to first-class trace events | The brief wants "where it changed course after something failed" legible in the trace. | S |
| **P2-6** | **The write-up.** Why the architecture is shaped this way; what was tried, measured and rejected; named weaknesses | The brief says it carries more weight than most candidates assume. Part 1 of this document is a first draft of the "named weaknesses" section. | L |

### P3 — "Take it further" (the brief says solve *one* properly)

| ID | Item | Notes |
|---|---|---|
| **P3-1** | **Cost falls by half with accuracy held.** Make `memory_hits` actually suppress redundant search/fetch: before dispatching a subquery, check whether resolved entities already have verified claims covering it, and skip the web round-trip | This is the strongest candidate. It is the one the brief describes most concretely, memory infrastructure already exists, and "memory that transfers to an unseen question" is exactly what Q5–Q8 were designed to demonstrate. Today `memory_hits` is counted but changes no behaviour. |
| **P3-2** | Source conflict auto-resolution — pick a number and justify it, rather than reporting both | Needs recency, primary-vs-secondary and publisher weighting. Depends on P1-1. |
| **P3-3** | Adversarial analyst — tell it an auditor will check every claim, measure whether citation quality improves or whether it starts citing authoritative-looking sources that don't support the claim | Cheap to run once P2-1 works: same suite, two prompts, diff the verdict distribution. Reporting a *negative* result here is fully acceptable and still scores. |
| **P3-4** | Auditor findings feed back automatically into the next run | P1-5 is the prerequisite; this is its honest, completed form. |

**Recommendation:** commit to **P3-1** and treat P3-3 as a bonus, since P3-3 is
nearly free once the suite runs live. The brief is explicit: *"Solve one properly
rather than four loosely."*

### P4 — Minor correctness

| ID | Item |
|---|---|
| P4-1 | `cli._build_memory` accepts `settings`, does `del settings`, hardcodes `dyla.db` in CWD — DB location unconfigurable and CWD-dependent |
| P4-2 | Cross-check only triggers on self-reported `low`/`medium`/`weak` confidence; a model that labels everything `high` bypasses corroboration entirely |
| P4-3 | Design spec documents `dyla audit runs/run-001.json # audit a saved answer`; the command only greps an existing trace and never re-audits |
| P4-4 | `memory_records_text` indexes a free-text column no query can use; `search_memory` full-scans and scores in Python |
| P4-5 | Spec references a `runs/` artifact directory that was never implemented |

---

## Part 3 — Decisions needed before P1/P2 start

1. **Live API access.** P2-1 through P2-4 and all of P3 need working keys for the
   model, embedding and You.com search providers. Without them the ceiling is a
   recorded-fixture harness — defensible, but it must be stated plainly in the
   write-up rather than presented as a live run.
2. **P1-4** — is `local` a credible default auditor, or an offline stub?
3. **P1-7** — wire in `agent_runtime.py`, or delete it?
4. **Scope.** P0 is done. P1 + P2 is the honest-and-complete submission. P3-1 on
   top is what moves it toward the brief's "Yes" pile.
