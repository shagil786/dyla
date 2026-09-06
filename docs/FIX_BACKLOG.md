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
| **P0-3** | CI on a 3.11 + 3.12 matrix, asserting module imports, `dyla --help`, and `pytest`. The workflow is written and correct, but it **has never executed**. | ⚠️ **REOPENED 2026-09-05 — not DONE** |
| **P0-3a** | *Why P0-3 was reopened, and the evidence.* **Every workflow run this repo has ever created concluded `startup_failure` in 0s**, and the ratio only moves one way, since each push adds another 0s failure — `33966149644` is the commit that recorded this, `33967859296` is PR #5 opening, and both are themselves failures. The count is deliberately not written down: it was 25 when first measured, 26 one commit later and 29 by the time PR #5 opened, so any figure here would be stale before it was read. Run the command below instead — on every branch, including four pushes to `main` (`33961584942`, `33959453438`, `33927164507`, `33919754186`) and this branch's `33965683073`. `gh api "repos/shagil786/dyla/actions/runs?per_page=100" --jq '[.workflow_runs[].conclusion]|group_by(.)|map({(.[0]):length})|add'` → a single-key object whose only key is `startup_failure` — the value is the total run count, and no other conclusion has ever appeared in the history. `--jq '[.workflow_runs[].conclusion]|unique'` returns `["startup_failure"]`, which is the same fact without a number to go stale. Each run created **0 jobs** (`.../runs/<id>/jobs` → `total_count: 0`), produced **no log** (`gh run view --log` → `log not found`) and **no check-run** (`total_count: 0` on the head commit), so GitHub rejected the run before scheduling anything and left no diagnostic. The workflow file is not the cause: it is `state=active` at `.github/workflows/ci.yml`, parses as valid YAML, and has the expected `on:`/`jobs:` shape, 6 steps, and the `["3.11", "3.12"]` matrix; the bytes are plain ASCII with LF endings, no BOM and no tabs. That points above the file — Actions disabled for the repo, a billing/spending cap, or a policy blocking `actions/checkout@v4` and `actions/setup-python@v5`. Not inspectable from here: `GET /repos/shagil786/dyla/actions/permissions` → `403 Resource not accessible by integration`. **Consequence: the declared 3.11 floor is currently guaranteed by manual local runs and by nothing automated.** P0-1 and P0-2 are unaffected and stay DONE — P0-2's `test_every_module_imports_on_this_interpreter` passes on Python 3.11.2 locally, so the regression guard does exist, it just only runs on a machine someone sat down at. That is precisely the gap P0-3 was written to close: PEP 701 syntax parsed on 3.12 and not on the declared floor, and a matrix that never executes cannot catch the next one. **How this was missed:** P0-3 was recorded DONE on reading `.github/workflows/ci.yml` and confirming its contents, not on watching a run go green — file presence verified, execution never verified. Same shape as Part 1's four "committed and described as working, but not functioning" features, one level up. **To close:** Settings → Actions → General (enabled?) and Settings → Billing → Actions (minutes/spending limit), then re-run on this branch and confirm both matrix legs green before marking DONE again. No repo-side change is needed, and none should be made until the setting is seen — editing a valid workflow to fix an account-level block would be guessing. | **TODO (blocked on a repo/account setting I cannot read or change)** |

Result: `pytest -q` → **210 passed, 1 skipped, 0 failed**. `dyla --help` lists all six commands.
After P1 the suite stands at **251 passed, 1 skipped, 0 failed**.
At this HEAD: **321 passed, 0 skipped, 0 failed** on Python 3.11.2, and `dyla --help` lists all six commands. All three were re-verified locally; **only the first two are verified anywhere** — see P0-3a.

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
| **P2-4** | ✅ **DONE.** Report what the auditor caught | `reports/auditor-findings.md`. Because the extractive offline model cannot hallucinate, real verdicts alone prove nothing, so `dyla.findings` also plants known-bad claims and measures detection: **19/20**, up from 15/20 before misattribution checking. **Now 20/20** — the last miss (the negation of the Q1 GST claim) was a symptom of the auditor's missing scope reasoning (see WRITEUP §4.2); the scope-gated polarity fix closed it without touching a seeded fixture. | M |
| **P2-5** | ✅ **DONE.** Promote the plan, retries and bail-outs to first-class trace events | New events: `plan_created`, `claim_rejected` (4 stable reason codes), `answer_synthesized`, `answer_withheld`, `source_fetch_retried`, `source_fetch_recovered`. `evidence_selected` now names its sources and its reuse provenance. Fixed two things found while doing it: the redactor was scrubbing every token count out of the log (`model_tokens` matched the credential pattern), and per-stage `completed` reported only ledger totals, so a stage that spent 426 tokens logged `model_tokens: 0`. Guarded by `tests/integration/test_trace_completeness.py`, which now also drives `insufficient_corroboration` and `blocked_by_audit_feedback` through **real two-run traces** and asserts the emitted `reason` string (both were previously unasserted at trace level — one had no test at all, the other was metric-only). | S |
| **P2-6** | ✅ **DONE** — `docs/WRITEUP.md`. **The write-up.** Why the architecture is shaped this way; what was tried, measured and rejected; named weaknesses | The brief says it carries more weight than most candidates assume. Part 1 of this document is a first draft of the "named weaknesses" section. | L |

### P3 — "Take it further" (the brief says solve *one* properly)

| ID | Item | Notes |
|---|---|---|
| **P3-1** | ⚠️ **PARTIAL — 25.0%, not 50%.** Measured and reported as a shortfall in `docs/WRITEUP.md` §3, not rounded up. (Was 27.8% / 13.5% before the P5-3 memory fix; memory that actually accumulates feeds the planner more subqueries, so both modes cost more and the net saving re-measured at 24.1% / 12.7%.) Searches fall 68% (19→6) and four of eight questions do zero searches; total tokens fall **17.9%** over all eight and **34.0%** over the four that can reuse anything. The move from 24.1% to 34.0% came from budgeting the memory *prompt context*: every retrieved record used to be quoted to the model, so prompt size grew with memory and Q8 — the most expensive question — was a net cost under reuse (1,534 input tokens vs a 1,485 no-memory baseline). At most 6 question-relevant records are now quoted, Q8 went +3% → −33%, and accuracy is unchanged at 8/8, 28/28 and 20/20. Memory removes the search step, not the grounding step. **Cost falls by half with accuracy held.** Make `memory_hits` actually suppress redundant search/fetch: before dispatching a subquery, check whether resolved entities already have verified claims covering it, and skip the web round-trip | This is the strongest candidate. It is the one the brief describes most concretely, memory infrastructure already exists, and "memory that transfers to an unseen question" is exactly what Q5–Q8 were designed to demonstrate. `memory_hits` now changes behaviour (reuse skips), and since P5-3 the hits themselves are real history rather than one overwritten run. |
| **P3-2** | ✅ **DONE — the deferral was wrong, and re-reading it is what reopened this.** The deferral argued a resolution rule "could only be exercised against fixtures that assume the conclusion". That reasoning covered a real defect it never named: the shipped behaviour did not merely decline to *pick* between conflicting figures, it **actively discarded the better-sourced one**. A source stating a different figure and a source saying nothing were the same branch — both fell through to `insufficient_corroboration` — so a tier-1 summary vetoed a tier-4 filing by disagreeing with it. "Conservative resolution" was the wrong name for it. Now `src/dyla/resolution.py` grades provenance into four tiers and resolves authority-first, recency-within-tier, emitting a `disagreement_resolved` trace event carrying the rule that fired, both tiers, both dates and both values. The unresolved standoff is reachable and directly tested, because a resolver that always produces a winner is as uninformative as an auditor that approves everything. The old objection stands where it is true and is now recorded as a limit rather than a reason not to build: tiering is substring matching on URLs, the table is hand-built for Indian filings and press, and the corpus exercises it exactly once. Two defects found while building it are pinned as tests — the first detector reported 6 conflicts of which 1 was real, and the fix for that then rejected the one true positive because "Infosys Limited" extracted as `{'limited'}`, which "Wipro Limited" satisfies. See WRITEUP §4.10. | **DONE** |
| **P3-3** | ✅ **DONE — negative result, measured and pinned.** Adversarial analyst — tell it an auditor will check every claim, measure whether citation quality improves or whether it starts citing authoritative-looking sources that don't support the claim. `scripts/experiment_adversarial_analyst.py` runs the full suite twice (baseline vs an audit-threat system prompt) and diffs answers, claims, citations and verdicts: **8/8 questions byte-identical** in reuse and no-reuse modes (`runlogs/P3-3-result-*.txt`). That is the expected offline result: `OfflineModel` is extractive — it recovers the `Question:` line and evidence blocks by marker and ignores the system message, so it structurally cannot change its citations under threat. The invariance is pinned by `tests/unit/test_offline.py`. Offline, the experiment cannot demonstrate model honesty either way; the real run needs a live key, which remains unavailable (see WRITEUP §4.8). |  |
| **P3-4** | ✅ **DONE.** Auditor findings feed back automatically into the next run | P1-5 is the completed form, and the tests prove the loop rather than asserting its parts: `test_claim_rejected_by_a_previous_audit_is_blocked_on_the_next_run`, `test_a_paraphrase_of_a_rejected_claim_is_also_blocked` (fingerprint, not substring), `test_rejected_claims_are_named_in_the_system_prompt`, plus `test_audit_feedback_blocking_is_traced_with_its_reason_code` driving `blocked_by_audit_feedback` through a real two-run trace. Caveat closed this session: the loop used to see only the previous run, because every run overwrote the last run's claim rows (see Part 4, P5-3); feedback now reads the full run history. |

**Recommendation:** commit to **P3-1** and treat P3-3 as a bonus, since P3-3 is
nearly free once the suite runs live. The brief is explicit: *"Solve one properly
rather than four loosely."*

### P4 — Minor correctness

| ID | Item |
|---|---|
| P4-1 | ✅ **FIXED.** `cli._build_memory` accepts `settings`, does `del settings`, hardcodes `dyla.db` in CWD — DB location unconfigurable and CWD-dependent New `DYLA_MEMORY_DB_PATH` (default `dyla.db`) threads through `_build_memory` and `_build_analyst`'s embedding cache; parent directories are created so a fixed path like `~/.dyla/memory.db` works, and two invocations from different CWDs now reach the same memory. Tests: config alias, CLI wiring, cross-CWD sharing.|
| P4-2 | ✅ **FIXED.** Cross-check only triggered on self-reported `low`/`medium`/`weak` confidence — a model that labels everything `high` bypassed corroboration entirely. The gate is now model-independent: a single-source claim is cross-checked when it carries a figure or year, or when the model flagged low confidence, unless a prior run's *supported* verdict already covers it. `_corroborate` re-fetches independent candidates (own citations skipped), accepting only when an on-topic page independently states the claim's facts (`verification.corroborates`: topical overlap + matching numeric fact or year; restatement floor for figure-free claims). The corroborating page is use-once — never added to `claim.citations`, never returned as a `Citation`. New metrics `corroboration_searches`/`corroboration_fetches`; `claim_rejected` now carries `corroboration_sources_checked`. Verified: seeded-defect audit 20/20 before and after, suite 8/8; the planted 1,53,670-crore second source is now rejected where baseline carried it as supported (see `runlogs/P4-2-proof.md`, WRITEUP §4.7). |
| P4-3 | ✅ **FIXED.** Design spec documented `dyla audit runs/run-001.json # audit a saved answer`; the command only greps `claim_audited` events out of an existing trace. Spec text now says so — including a note that re-auditing a past answer is a deliberate non-goal (verdicts are meaningful only against the sources cited at run time). The feature was not built; no code changed. | 
| P4-4 | ✅ **FIXED.** `memory_records_text` indexed a free-text column no query can use: `search_memory` full-scans and scores in Python (normalized substring counts a B-tree cannot serve). Index removed from the schema and dropped by the migration for older databases; the linear scan is now documented on `search_memory` as deliberate at this scale, with FTS5/the embedding store named as the replacement. Pinned by `test_memory_records_carry_no_free_text_index` (verified red with the index present, green without, including the migrate-and-drop path). |
| P4-5 | ✅ **FIXED.** Spec referenced a `runs/` artifact directory that was never implemented (example `runs/run-001.json`). Real replayable artifacts live at `runs/<mode>/qNN-<slug>.jsonl` with `index.json` (see `runs/reuse/`, `runs/no-reuse/`); the spec's example now matches that naming |

---

## Part 4 — Session 2026-09-05: provider independence, local execution, memory durability

**Branch:** `arena/01a070ee-dyla` (from `arena/01a0701c-dyla` @ `a7a32eb`)
**Suite:** `uv run pytest -q` → **319 passed** (was 302). `uv` itself was
installed into the sandbox (`pip install --user uv`); the repo has no `uv`
dependency — plain `pytest` from a venv runs the same suite.
**Evaluation:** `scripts/run_suite.py` in both modes, fully local (SQLite,
in-memory vector store, JSONL logs, recorded fixtures — `dyla.offline`
imports stdlib only, and the offline path never touches the provider factory):
**8/8 complete, seeded-defect audit 20/20, both modes.**

Status key: `DONE` · `TODO` · `DECIDE` · `DEFERRED` · `OPEN` (newly found,
needs a call)

| ID | Item | Status |
|---|---|---|
| **P5-1** | Provider-independence pins: 10 test functions in `tests/unit/test_provider_factory.py`, expanding to **16 collected cases** (the vendor-rejection test is parametrised across five vendor names). A fresh checkout (no env, no `.env`) defaults every model role to `local` and builds all four local providers with zero secrets set; the `compatible` adapter posts the standard OpenAI shape to an arbitrary localhost runner URL (no vendor-specific path/header/payload key); vendor names (`groq`, `azure`, `openai`, `anthropic`, `together`) are rejected as unknown for the model role, and unknown values are rejected for every other role (web fails fast at settings validation, since it has no local adapter). `grep -rin groq src/ scripts/ .env.example` → empty. **Scope note (corrected 2026-09-05):** this row previously asserted `grep -rin groq src/ tests/ scripts/ docs/ .env.example` → empty. That was true when written but is now false, and the two forms are not interchangeable — `tests/` deliberately names the vendor strings at `test_provider_factory.py:165,175` because asserting that `groq` is *rejected* requires spelling it. The property being protected (no vendor hardcoded in shipped code) holds and is narrower than the old grep implied: it is `src/`, `scripts/` and `.env.example` that must be empty. `docs/` is likewise out of scope, since this backlog discusses the vendors by name. | **DONE** |
| **P5-2** | Committed artifacts were stale: `reports/` and `runs/` predated both the §4.2 scope-gate fix (committed Q1 `incomplete`, seeded 19/20) and P4-2 corroboration, so the write-up's "regenerate with one command" claim was false — regeneration produced 8/8 + 20/20. Regenerated in the established order (no-reuse first, copied to `evaluation-no-reuse.*`, then reuse; history now 19/20 entries, showing the fix landing). The pre-fix Q1 trace survives at `a7a32eb:runs/reuse/q01-…jsonl` for the §4.2 dissection. | **DONE** |
| **P5-3** | ✅ **FIXED.** Claim-ID collision across runs. Claim IDs are per-answer (`c1`..`cN`), and `save_claim` upserted by bare ID — every run overwrote the previous run's rows, so durable memory held only the latest answer and audit feedback could never see back more than one run. Storage keys are now run-namespaced via `memory.memory_claim_id` at both write sites (auditor + orchestrator); answers/traces keep bare IDs; no production reader SELECTs by ID so nothing else changed. Post-fix `dyla.db`: 28 claims, 8 run prefixes, all supported. Behaviour delta, measured: `memory_hits` 7 → 61/suite, planner expands more subqueries (retrieval searches 9 → 19 baseline, 4 → 6 reuse), savings move to 12.7% / 24.1% (see WRITEUP §2–§3). | **DONE** |
| **P5-4** | ✅ **FIXED.** Seeded-defect probes polluted `dyla.db`. The audit called the real `AuditorAgent.run`, which persisted every planted lie — the post-suite database held "Nithin Kamath is the CEO of Infosys" and the Singapore-Exchange fabrication *instead of* the real Q8 claims. `AuditorAgent.run` takes `persist=False` for read-only probes (still reads live memory, writes nothing); `run_suite.py` passes it. Post-fix: 0 fabricated rows, 0 warnings. | **DONE** |
| **P5-5** | ✅ **FIXED.** Accepted cross-checks left no trace event. Rejections surfaced via `claim_rejected`, but the 24 corroboration fetches per run that *confirmed* a claim were metrics-only — "every tool call and what came back" had a hole. New `claim_corroborated` event (accepted/source/checked/detail), added to the validator allowlist; committed traces carry 14 (reuse) / 13 (no-reuse), matching `corroboration_searches` exactly. | **DONE** |
| **P5-6** | ✅ **DONE — removed.** `MemoryStore.add_memory` had no production callers (definition + tests only). Call made: remove, not wire — evidence already lives in the vector store, claims flow through `save_claim`, and wiring a second writer would duplicate state and reintroduce the content-hash overwrite shape (`sha256(kind + text)` IDs collide across runs with different entity lists). Deleted the method, its now-unused `hashlib` import, and re-seeded all `test_memory.py` fixtures through `save_claim` (the store's single real writer); the stable-order test additionally asserts the `source_ids` round-trip it previously seeded-but-never-checked. Suite holds at 319 passed. Same precedent as the Azure removal and the P4-4 index removal: dead code deleted, not carried. | **DONE** |
| **P5-7** | P3-3 re-confirmation after the memory fix: `scripts/experiment_adversarial_analyst.py` both modes → still byte-identical 8/8; `runlogs/P3-3-result-*.txt` unchanged. | **DONE** |
| **P5-8** | Local completion receipt incorporated as `docs/RECEIPT.md` — verified against this HEAD by execution (319 passed, 8/8 + 20/20 both modes as committed), not pasted raw: stale counts refreshed, the false no-timeout claim struck with code cites, the padded 22-item failure list de-duplicated to ~15 with each item kept/corrected/rejected, and the production verdict re-scoped to what the brief actually grades. | **DONE** |

Red proof for the P5-3–P5-5 tests (fix stashed, tests kept): the two auditor
persistence tests fail (overwrite returns; probe rows persist), the two
`claim_corroborated` tests fail (no event), the orchestrator namespacing test
fails; restored → 319 passed. Full record: `runlogs/P5-memory-proof.md`.

---

## Part 3 — Decisions needed before P1/P2 start

1. **Live API access — and egress.** P2-1 through P2-4 and all of P3 need
   working keys for the model, embedding and You.com search providers. They
   also need something this backlog previously failed to name: **outbound
   network access**. Measured on this environment — `pypi.org` and
   `files.pythonhosted.org` return 200; `en.wikipedia.org`, `example.com`,
   `google.com`, `api.openai.com` and `api.you.com` all have the TLS
   connection closed. DNS resolves and `validate_external_url` passes, so the
   failure surfaces late, at handshake. A key alone therefore unblocks
   nothing. Without both, the ceiling is a recorded-fixture harness —
   defensible, but it must be stated plainly in the write-up rather than
   presented as a live run.
2. ~~**P1-4** — is `local` a credible default auditor, or an offline stub?~~
   **Resolved:** it stays the default, now that it is credible.
3. ~~**P1-7** — wire in `agent_runtime.py`, or delete it?~~ **Resolved:** wired in.
4. **Scope.** P0, P1, P2, P3-1 (partial — see its row), P3-3 (negative result,
   measured and pinned), P3-4 (closed — P1-5 is the completed form, see its
   row) and all of P4 are done. P3-2 is **DONE** — it had been deferred, and
   revisiting the stated reason showed the deferral was masking a defect
   rather than scoping out a feature; see its row. This session (Part 4) closed P5-1
   through P5-8, including P5-6 (dead `add_memory` API removed per explicit
   call) and P5-8 (verified completion receipt). No code items remain open:
   the only outstanding prerequisite is a live key for P3-3's real
   experiment and P2's live mode.

5. ✅ **Qdrant entity-overwrite bug FIXED.** `QdrantVectorStore.upsert()` now
   reads the stored `entity_ids` for each point and unions them before writing.
   Qdrant replaces a point's payload wholesale, so re-ingesting a page under a
   different entity used to erase its attribution — **live, not latent, for any
   Qdrant deployment.** Covered by five tests using a fake client (no
   credentials needed), verified to fail when the merge is removed. The read is
   non-fatal on error: losing attribution is recoverable on a later run, losing
   the ingestion is not.

   ✅ **Azure was removed instead of fixed.** Nothing used it, it was the
   *default* for three provider roles despite requiring credentials nobody had,
   and its vector store carried the same overwrite bug. Deleted:
   `azure_models.py`, `search.py` (that file was the Azure AI Search adapter
   despite the generic name), their tests, 9 config settings and 4 factory
   branches — about 830 lines. Defaults for every role are now `local`, so a
   fresh checkout runs with no credentials. Azure endpoints that speak the
   standard OpenAI API still work through the `compatible` adapter.

---

## Part 5 — Session 2026-09-06: independent code review (architecture · agentic-AI · RAG lenses)

**Baseline:** `main` @ `67b9d44`. Suite at review time: **321 passed, 0 failed**.
Two sources merged here: an independent agent review and a full read of the core
pipeline (`orchestrator`, `agent_runtime`, `analyst`, `auditor`, `memory`,
`reliability`, `local_vector`, `qdrant_vector`, `compatible`, `chunking`,
`config`, `web`). Every code item below was verified by reading the cited lines,
not taken from the review on faith.

### Reconciling the independent review's claims

Following Part 1's precedent — claims checked, not merged:

| # | Claim in the review | Measured reality |
|---|---|---|
| 1 | "Some circular dependencies between components (analyst ↔ memory ↔ entity resolver)" | **Rejected.** `memory.py` imports only `domain`; `analyst.py` imports `ingest`, `models`, `ports`, `query_planner`, `verification`. The analyst *receives* memory and the resolver through its constructor — dependency injection, the opposite of a cycle. No import cycle exists (`grep` over all `from .` imports confirms; the P0-2 sweep-import test would also fail on one). |
| 2 | "hybrid_search combining vector similarity with metadata filters" listed as a strength | **Mislabelled.** Both adapters' `hybrid_search` is dense similarity + metadata filtering only; there is no keyword/BM25 channel anywhere in the retrieval path (the only lexical scorer is `memory.search_memory`'s substring count). See P6-4. |
| 3 | "Add A/B testing framework for retrieval strategies" | **Deferred with reason** (same shape as P3-2): the offline model is extractive and provably byte-invariant across prompts (P3-3 measured 8/8 identical), so offline A/B would measure noise. Meaningful policy comparison needs the live key that P2/P3-3 already wait on. Recorded here so it is decided, not forgotten. |
| 4 | "Add circuit breaker pattern for failing providers" | **DECLINED 2026-09-06** — decided, not forgotten. The `compatible` client already retries timeouts and (since P6-6) all transient transport errors with backoff, and the orchestrator's budget and deadline machinery bounds runaway stages. A circuit breaker adds persistent state and a second failure surface to a single-tenant CLI that runs one question at a time, with no deployment to protect. Revisit only if a long-lived multi-provider deployment exists and shows repeat provider outages degrading runs. |
| 5 | "AnalystAgent has 7+ dependencies — builder pattern" | Noted, **low priority**. The constructor takes collaborators, which is what makes the test suite able to fake every provider; a builder would add indirection without changing any behaviour the brief grades. |
| 6 | Adaptive-architecture direction (policy layer, learning layer, dynamic tool discovery) | **DECIDED 2026-09-06 — `docs/ADR-0001-adaptive-architecture.md`.** Strangler-fig, not a redesign: the four-layer proposal is decomposed into three gated increments — (1) policy extraction (behaviour-preserving, tracked below as P7-1), (2) shadow mode, (3) policy selection from effectiveness — with 2 and 3 explicitly gated on the live key that P2/P3-3 already wait on, because offline the model is prompt-invariant (P3-3: byte-identical 8/8) and the embedding is a 2-dim hash (P6-9), so there is no signal to adapt to. A learning layer and dynamic tool discovery are out of scope until increment 3 has data. |

### P6 — Review backlog

Status key as before.

| ID | Item | Status |
|---|---|---|
| **P6-1** | **`max_web_requests` is decorative on the analyst path.** The orchestrator configures `DEFAULT_MAX_WEB_REQUESTS = 200` and `BudgetLedger.before_web_request` enforces it — but only for tools invoked through `ToolRegistry`, and `AnalystAgent` holds its own `searcher`/`fetcher` and never touches the registry (its corroborations fetch directly too). The stage that makes the most web calls is the one budget the ledger does not see. Tokens got a deliberate fix (`_attach_ledger` swaps in `BudgetedModel`); web requests get the same treatment: the orchestrator wraps each stage's `searcher`/`fetcher` in a counting proxy for the stage's duration, so `before_web_request` fires on every search and fetch including corroboration. | **DONE** |
| **P6-2** | **"The analyst is genuinely async and is cancelled properly" is false.** Every blocking call in `AnalystAgent.run` goes through `asyncio.to_thread`, which `wait_for` cannot stop — cancelling the task abandons the thread, and `asyncio.run` joins the default executor at shutdown, so a timed-out analyst still blocks process exit. This is exactly the failure `_run_on_daemon_thread` was built for (Part 1, P1-6 bug 4) but only the auditor was routed through it. The analyst stage now runs the same way: `asyncio.run(self.analyst.run(...))` on a daemon thread, so the caller-visible ceiling holds and process exit is never blocked; the module docstring states the shared honest limitation for both stages instead of claiming an exemption the code does not have. | **DONE** |
| **P6-3** | **`RunOrchestrator` is not safe to reuse concurrently** (latent): `_run_issues` is reset inside `ask()` on shared state, and `_attach_ledger` monkey-patches the shared agent's `.model` for a stage's duration — two concurrent `ask()` calls would cross-contaminate issues and route both stages through one ledger. Today the CLI builds one orchestrator per invocation, so this is documented, not guarded: the class docstring now states the single-flight constraint. | **DONE** |
| **P6-4** | **`hybrid_search` does no keyword retrieval.** Both vector adapters are dense-only; for factual recall, hybrid retrieval (vector + lexical, merged) consistently outperforms dense-only, and the method name promises what is not there. Decision recorded: rename is rejected (the call sites and the brief's vocabulary use "hybrid" for vector+filter, and renaming is churn), implementation is taken: `LocalVectorStore.hybrid_search` now blends a token-overlap lexical score with the dense score, so the offline path has a real second channel; Qdrant keeps provider-side dense search (its payload indexes serve the metadata filters, and a lexical channel there needs Qdrant's full-text index — noted as a live-mode follow-up, not silently dropped). | **DONE** |
| **P6-5** | **Cosine silently truncated on dimension mismatch in `LocalVectorStore.hybrid_search`.** `upsert` validates every vector, but search `zip`s the query vector against stored vectors — `zip` truncates to the shorter side, so a mismatched query embedding yields a plausible-looking garbage score instead of an error. `QdrantVectorStore` raises in the same situation; the local store now matches. | **DONE** |
| **P6-6** | **Retries do not cover connection errors.** `compatible.post` retries only `httpx.TimeoutException` and 429/5xx; transient `httpx.TransportError` subclasses (`ConnectError`, `ReadError` — a DNS blip, a dropped connection) raise straight out with `max_retries=3` unused. Transport errors now retry with the same backoff. | **DONE** |
| **P6-7** | **Multi-year date filter admits unrequested intermediate years while the limitation text overstates what was enforced.** Years `[2022, 2024]` become the continuous range Jan-2022..Jan-2025 (2023 sources admitted), yet the limitation says "applied for 2022, 2024". Honest fix chosen over a `SearchFilters` schema change: the limitation text now states the actual range ("between 2022 and 2024, sources without a published date included"), matching what the filters do. Per-year OR filtering is a schema change across both adapters — worth it only with a live corpus that exercises it. | **DONE** |
| **P6-8** | **`CompatibleEmbeddingProvider.embed` can silently return fewer vectors than inputs** — the final comprehension drops `None` slots, and both stores then raise a confusing count-mismatch error pointing at the store, not the cause. `embed` now raises inside itself when any slot is unfilled. | **DONE** |
| **P6-9** | **Offline retrieval scores are structurally noise** (noted, no code change): the default `LocalEmbeddingProvider` is a 2-dim hash, so offline dense scores — and reuse-coverage decisions gated on `reuse_min_score` — carry no retrieval-quality signal. Fine for the deterministic replay (WRITEUP already covers determinism), but any offline citation of retrieval *quality* metrics needs the same honesty caveat. **DONE — WRITEUP §6, weakness 6** (the offline 2-dim hash embedding, the lexical channel added in P6-4, and the `reuse_min_score` half of the reuse gate, all stated as one weakness). |
| **P6-10** | `.github/github-app.yml` (untracked): nothing in the repo reads it — config is env-var-based, CI doesn't reference it. **DECIDED 2026-09-06: left untracked, deliberately not committed and not deleted.** Committing an unparsed config would imply a guarantee no code or workflow honours; deleting it would destroy a file the owner may have created for an external GitHub App (the flags read like "auto-start sessions on issues, remote control off"). To land it: verify the consuming app's expected filename and schema, then commit with a README note naming the consumer. | **DECIDED (untracked pending consumer verification)** |
| **P7-1** | ADR-0001 increment 1: extract the hardcoded behaviour constants (`reuse_min_sources`, `reuse_min_score`, `min_evidence`, `max_subqueries`, `search_limit`, `evidence_limit`, `verification.py` tolerance floors) into a single typed `Policies` object passed through the agents. Behaviour-preserving: all tests stay green and the suite must regenerate byte-identical in searches/fetches/verdicts. Do not worsen `AnalystAgent`'s constructor surface without a builder (ADR-0001 consequences). **DONE.** New `dyla/policies.py`: frozen `Policies` dataclass owning every threshold (planning, reuse, retrieval, the rejected-claim overlap, all five verification tolerances, the lexical blend weight) with structural validation — including `match_tolerance < conflict_tolerance`, the invariant that keeps the auditor's unverified band open. `verification.py` and `local_vector.py` alias their public constants from `DEFAULT_POLICIES`; `AnalystAgent` takes `policies=` with the pre-existing per-knob kwargs kept as explicit overrides (constructor surface grew by one parameter, not seven). Environment variables deliberately not wired: changing policy is a tested code change, not a flag. Scope correction made during review: per-run injection is implemented for the analyst's knobs only — the verification tolerances and lexical weight bind from `DEFAULT_POLICIES` at import (changing them is a code change to the defaults), and the corroboration gates own no policy knob at all (P7-2 and ADR-0001 say the same; this row originally listed them in error). 8 new tests (`tests/unit/test_policies.py`) pin every default to the literal it replaced and assert the override rules; the suite regenerated byte-identical in both modes — tokens, searches, fetches, `searches_skipped`, verdicts and the 20/20 seeded-defect audit unchanged, only wall-clock moved. | **DONE** |
| **P7-2** | ADR-0001 increment 2: shadow mode. `AnalystAgent(shadow_policies=...)` runs a candidate policy alongside the live one at the reuse decision — the one behaviour increment 3 would select on: the same probe results are re-classified under the shadow policy (no extra retrievals, no metric moves, behaviour follows the live policy only) and the comparison is traced as `reuse_shadow_evaluated` (live vs shadow covered entities and skipped queries, plus a `divergent` flag; emitted even on agreement so a live run can measure agreement rates). Stated limits, in the code docstring and the ADR: the shadow decision reuses probes fetched under the live `evidence_limit`, so a shadow policy changing that knob is approximated, and the shadow covers the reuse decision only. `reuse_shadow_evaluated` was added to the quality-gate allowlist, and a test runs the gate itself against a shadow trace so the manual-sync coupling cannot regress silently. Four tests: no behaviour change, divergence traced, agreement traced, allowlist in sync. Suite regenerated: byte-identical behaviour, 20/20 audit both modes. | **DONE** |

Note on the review's `valid_events` allowlist concern: already documented as a
deliberate manual-sync coupling in `reliability.py` itself — intentional, not a
defect, no action.

**Two bugs the P6 tests caught during the work**, same tradition as the P1 list:

1. `_run_on_daemon_thread`'s exception relay referenced `exc` from inside the
   `except BaseException as exc:` block, but the relay lambda runs *after* the
   block exits — and Python deletes the except-variable at block end — so the
   relay itself raised `NameError` and the awaited future never resolved. Any
   stage exception (a budget breach, a crash) made the orchestrator hang until
   the full wall-clock ceiling instead of failing fast. The exception is now
   bound to a name that outlives the block. Found by
   `test_the_web_request_budget_counts_the_analyst_own_providers`, which hung
   120s on first run.
2. `_run_stage` treated **every** `ValueError` from a stage as a wall-clock
   overrun — `BudgetLedger` also raises `ValueError` ("web request budget
   exceeded", "cost budget exceeded"), so a budget breach was reported as a
   false timeout. `_run_stage` now discriminates on the runtime's
   deadline-specific message.

Artifact note: because P6-4 changed `LocalVectorStore.hybrid_search` scoring,
both suite modes were regenerated (established order: no-reuse first, then
reuse). Searches, fetches, verdicts and the seeded-defect audit (20/20 both
modes) are unchanged — only run IDs and wall-clock times moved — so every
figure cited in WRITEUP §2–§3 still holds.

**Review-pipeline follow-ups (same session):** the /code-review pipeline (five
independent reviewers, confidence-scored) surfaced four findings at 75
confidence, all fixed here:

1. **Budget wrappers were swapped out from under a timed-out stage.** The
   `finally: restore()` in `_run_stage` fired while the abandoned daemon
   thread still ran, so its remaining model/web calls bypassed the budget
   wrappers entirely. Restore is now skipped on a deadline timeout — the
   wrappers stay attached and the abandoned work keeps counting against the
   run's ledger — and `_attach_ledger` unwraps any leftover wrapper and
   rewraps it against the next stage's ledger. The wrapper `setattr`s are
   also guarded (degrade, don't crash).
2. **A web-budget breach in the gather path was misattributed as a search
   outage.** `_collect_from_web` now recognises the ledger's ValueError and
   records "the run's web-request budget was exhausted" instead of "Web
   search failed", without counting it in `failed_searches`.
3. **The fallback answer still claimed a wall-clock timeout for every failed
   stage.** `_run_stage` now returns the failure reason, and `ask()` uses it
   as the limitation — the answer and the run issues tell the same story.
4. **Shadow mode ignored `shadow.reuse_enabled=False`.** A candidate that
   disables reuse is now classified as never skipping anything, matching what
   that policy would actually decide.

**Found by running the suite live (2026-09-06, the first full live run):**
the Qdrant adapter indexed `published_at` but never `entity_ids`, and Qdrant
rejects an unindexed field in a filtered query with a 400 — so the reuse
probe's entity filter killed the analyst stage on five of eight questions.
No offline test could see it: the offline suite runs `LocalVectorStore`.
Fixed in `ensure_collection` (keyword index created on fresh and existing
collections, missing fields only); three adapter tests pin it. Post-fix live
run: 2/8 complete, 4 `incomplete` (the live auditor honestly rejecting real
claims), 2 `unaudited` (the analyst declined to answer — the audit-feedback
loop blocked a restated claim from the previous run, which is the loop
working), searches_skipped 0→16 across the suite as reuse engaged,
seeded-defect audit 18/20 live. Model: nemotron-3.5-lightning via the
compatible adapter; stack: You.com search, real embeddings, Qdrant Cloud.

Doc corrections from the same review: the dangling "§6.1's caveat" reference
in WRITEUP §6 (an earlier automated fix had silently failed on a line-wrap
mismatch — lesson recorded: assert your replacements), the P7-1 claim that
"corroboration gates" were extracted into Policies (they are not; P7-2 and
ADR-0001 say so too), and the `policies.py` docstring now states the per-run
injection scope honestly (analyst knobs only; verification/lexical values
bind at import). Five regression tests pin all of it; suite 346 passed;
artifacts regenerated byte-identical, 20/20 audit both modes.
