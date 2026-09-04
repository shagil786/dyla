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
After P1 the suite stands at **251 passed, 1 skipped, 0 failed**.

### P1 — Make the auditor mean something — **COMPLETE**

An auditor that rejects everything scores the same as one that approves everything.

| ID | Item | Status |
|---|---|---|
| **P1-1** | Replaced the whole-claim substring match with slot-based verification in `dyla/verification.py`: numeric facts (lakh/crore and million/billion), years, currency/percent kinds, content-word and entity topicality | **DONE** |
| **P1-2** | `contradicted` path added — numeric conflict in on-topic context, plus antonym/negation polarity for non-numeric claims | **DONE** |
| **P1-3** | `tests/unit/test_verification.py`, 28 tests on realistic paraphrased prose | **DONE** |
| **P1-4** | Decision: `local` **stays the default**. It is now credible rather than a stub, and a deterministic default means a clean checkout audits without a second API key | **DONE** |
| **P1-5** | Feedback loop fixed: `verdict_status` persisted, rejected claims named in the prompt *and* enforced by a post-synthesis filter, fingerprint matching catches paraphrase | **DONE** |
| **P1-6** | Ceiling enforced via `asyncio.wait_for` on a shrinking budget, plus cooperative per-claim deadline checks inside the auditor | **DONE** |
| **P1-7** | `agent_runtime.py` wired in — both stages run through `AgentRuntime`, each stage's model wrapped in `BudgetedModel` so the ledger is load-bearing | **DONE** |

**Verdict discrimination, same claim, five sources:**

| Source | Before | After |
|---|---|---|
| paraphrased support | unsupported | **supported** |
| rounded restatement (1.54 lakh crore) | unsupported | **supported** |
| different figure (₹1,22,000 cr) | unsupported | **contradicted** |
| on topic, omits the figure | unsupported | unsupported |
| off topic | unsupported | **uncited** |

**Four bugs the new tests caught during the work**, none of which the old suite could have found:

1. The number regex split `2024` into `202` and `4` (the comma-group alternative used `*` and won greedily at three digits), so the bare-year guard never fired and years were compared against monetary amounts.
2. Numeric tokens inside `content_words` dragged topicality below the floor, so on-topic sources were misfiled as `uncited` rather than `unsupported`.
3. Checking the concatenation of all sources let one agreeing source mask another that disagreed — the verdict came back `supported` while the sources conflicted. Now checked per document.
4. `asyncio.run` joins the default executor at shutdown, so a stage abandoned by `wait_for` still blocked the caller for its full duration. A 5s auditor overran a 0.6s ceiling by the whole 5s *despite the timeout firing*. Stages now run on daemon threads.

**Honest limitations of the new auditor**, for the write-up:

- Sentence segmentation is regex-based and mis-splits on abbreviations.
- No co-reference resolution: "the company reported X" is matched by topical word overlap, not by knowing which company.
- Polarity uses a fixed antonym/negation table and will miss paraphrased reversals.
- A sentence discussing two entities can yield a false contradiction when the rival figure belongs to the other one.
- A thread cannot be killed. Cooperative deadline checks bound the auditor between claims; a single wedged fetch is bounded only by its own clamped timeout.

### P2 — The deliverables that are actually graded

The brief: *"Your run logs matter as much as your answers here."*

| ID | Item | Why | Effort |
|---|---|---|---|
| **P2-1** | ✅ **DONE.** Run the eight-question suite end to end | Runs via `scripts/run_suite.py` against the recorded corpus in `dyla.offline`. Not a live LLM run — no keys were available — and every artifact says so. | M |
| **P2-2** | ✅ **DONE.** Commit run logs and reports | `runs/<mode>/qNN-*.jsonl` (readable copies) and `reports/` are tracked. `logs/` stays ignored as the scratch directory a run writes into. | S |
| **P2-3** | ✅ **DONE.** Real pricing | `dyla.pricing` holds published per-1M-token prices with check dates and a USD/INR rate. Unknown models report `unpriced` with remediation, never `0`. | S |
| **P2-4** | ✅ **DONE.** Report what the auditor caught | `reports/auditor-findings.md`. Because the extractive offline model cannot hallucinate, real verdicts alone prove nothing, so `dyla.findings` also plants known-bad claims and measures detection: **19/20**, up from 15/20 before misattribution checking. | M |
| **P2-5** | ✅ **DONE.** Promote the plan, retries and bail-outs to first-class trace events | New events: `plan_created`, `claim_rejected` (4 stable reason codes), `answer_synthesized`, `answer_withheld`, `source_fetch_retried`, `source_fetch_recovered`. `evidence_selected` now names its sources and its reuse provenance. Fixed two things found while doing it: the redactor was scrubbing every token count out of the log (`model_tokens` matched the credential pattern), and per-stage `completed` reported only ledger totals, so a stage that spent 426 tokens logged `model_tokens: 0`. Guarded by `tests/integration/test_trace_completeness.py`. | S |
| **P2-6** | ✅ **DONE** — `docs/WRITEUP.md`. **The write-up.** Why the architecture is shaped this way; what was tried, measured and rejected; named weaknesses | The brief says it carries more weight than most candidates assume. Part 1 of this document is a first draft of the "named weaknesses" section. | L |

### P3 — "Take it further" (the brief says solve *one* properly)

| ID | Item | Notes |
|---|---|---|
| **P3-1** | ⚠️ **PARTIAL — 27.8%, not 50%.** Measured and reported as a shortfall in `docs/WRITEUP.md` §3, not rounded up. Searches fall 56% (9→4) and four of eight questions do zero searches; total tokens fall 13.5% over all eight and 27.8% over the four that can reuse anything. Memory removes the search step, not the grounding step. **Cost falls by half with accuracy held.** Make `memory_hits` actually suppress redundant search/fetch: before dispatching a subquery, check whether resolved entities already have verified claims covering it, and skip the web round-trip | This is the strongest candidate. It is the one the brief describes most concretely, memory infrastructure already exists, and "memory that transfers to an unseen question" is exactly what Q5–Q8 were designed to demonstrate. Today `memory_hits` is counted but changes no behaviour. |
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
2. ~~**P1-4** — is `local` a credible default auditor, or an offline stub?~~
   **Resolved:** it stays the default, now that it is credible.
3. ~~**P1-7** — wire in `agent_runtime.py`, or delete it?~~ **Resolved:** wired in.
4. **Scope.** P0, P1, P2 and P3-1 are done (P3-1 partially — see its row).
   Remaining: **P3-3** (adversarial analyst, needs a live model) and P4.

5. ✅ **Qdrant entity-overwrite bug FIXED.** `QdrantVectorStore.upsert()` now
   reads the stored `entity_ids` for each point and unions them before writing.
   Qdrant replaces a point's payload wholesale, so re-ingesting a page under a
   different entity used to erase its attribution — **live, not latent, for any
   Qdrant deployment.** Covered by five tests using a fake client (no
   credentials needed), verified to fail when the merge is removed. The read is
   non-fatal on error: losing attribution is recoverable on a later run, losing
   the ingestion is not.

   **Azure AI Search (`search.py`) still has the same bug and is not fixed** —
   see the open question about whether Azure should be supported at all.
