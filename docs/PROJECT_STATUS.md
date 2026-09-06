# Dyla — Project Status Report

**Date:** 2026-09-04
**Branch:** `arena/01a06e12-dyla` (from `main` @ `95584a7`)
**Assessed against:** Problem 3 — Analyst and Auditor
**Environment:** Python 3.11.2 (the only interpreter available; `pyproject.toml` declares `requires-python = ">=3.11"`)

---

## 1. Verdict in one line

The architecture is genuinely good and 195 tests pass — but **the shipped CLI does not start on the declared Python version**, and **all four features in the most recent commit are non-functional**. Against the brief's own gate ("does it run from a clean checkout using only your README, and are the logs and write-up there?"), this submission currently fails on both halves.

---

## 2. Gate check — does it run from a clean checkout?

| Gate requirement | Result |
|---|---|
| `pip install -e '.[dev]'` per README | Passes |
| `pytest -q` per README | **Interrupted — 3 collection errors, 0 tests run** |
| `dyla ask "..."` (the documented main command) | **`SyntaxError` before any code executes** |
| Run logs present in repo | `logs/` is gitignored and absent |
| Write-up present in repo | Does not exist |

### 2.1 The blocker

`src/dyla/evaluation.py` uses backslashes inside f-string expressions at lines **129, 141, 316**:

```python
lines = [f"### {index}. {item['question'].replace('|', '\\|')} — {item['status']}"]
```

This is PEP 701 syntax, legal only on **Python 3.12+**. The project declares `>=3.11`. On 3.11 the module fails to parse.

Because `cli.py` line 16 does `from .evaluation import DEFAULT_QUESTIONS, run_evaluation`, the parse failure propagates to the entire CLI. Verified:

```
$ .venv/bin/dyla --help
  File "/home/user/dyla/src/dyla/cli.py", line 16, in <module>
    from .evaluation import DEFAULT_QUESTIONS, run_evaluation
  File "/home/user/dyla/src/dyla/evaluation.py", line 129
SyntaxError: f-string expression part cannot include a backslash
```

**Every documented command is unreachable**: `ask`, `analyst`, `audit`, `evaluate`, `memory list`, `replay`.

It also silently deletes 15 tests from the suite (4 in `test_evaluation.py`, 9 in `test_cli.py`, 2 in `test_cli.py` integration) and, because pytest aborts on collection error, the other 195 never run either.

**Fix:** hoist the replacement out of the f-string, or set `requires-python = ">=3.12"`. Roughly a five-minute change; it is the single highest-value thing to do.

### 2.2 State once the blocker is bypassed

```
$ pytest -q --ignore=tests/unit/test_evaluation.py --ignore=tests/unit/test_cli.py \
           --ignore=tests/integration/test_cli.py
195 passed, 1 skipped in 3.00s
```

So the underlying library is healthy. This is a packaging/release failure, not a rotten codebase.

---

## 3. The last commit is almost entirely non-functional

Commit `95584a7` ("Problem 3: Analyst and Auditor enhancements") claims four features. I tested each. **All four are broken.** This matters more than any single bug, because these four are precisely the "take it further" items the brief rewards.

### 3.1 Auditor→analyst feedback loop — dead code, and inverted

Claimed: *"`_synthesize()` checks memory for previously audited claims; `_was_previously_rejected()` rejects new claims containing key phrases from prior rejected claims."*

Two independent defects in `analyst.py:146-160`:

```python
prior_rejected_claims: list[str] = []
for record in memories:
    if record.kind == "claim" and record.text:
        if record.verified:                       # (1) verified=True means SUPPORTED
            prior_rejected_claims.append(record.text)

def _was_previously_rejected(claim_text: str) -> bool:   # (2) never called anywhere
    ...
```

1. **The condition is inverted.** In `memory.py:save_claim`, `verified` is set to `int(verdict.status == "supported")`. The list named `prior_rejected_claims` is therefore populated with claims the auditor *approved*.
2. **`_was_previously_rejected` is never invoked.** Confirmed by grep — the only references are its own definition and body.

So the feedback loop does nothing at all, and if it were wired up it would suppress the analyst's *best* claims. This is the "closest thing to what we actually build" item on the brief; right now it is decoration.

### 3.2 Two-minute wall clock ceiling — observed, not enforced

Claimed: *"Two-minute wall clock ceiling (120s) enforced after analyst and auditor stages."*

`orchestrator.py` checks `time.monotonic() - started > 120` *after* each stage has already returned, and appends a string to `_run_issues`. Nothing is cancelled. A 10-minute analyst stage runs for 10 minutes and then gets a note saying it was too slow.

The brief's point is that the ceiling "forces genuine parallelism in your orchestration and exposes any agent that is really a long sequential chain" — a post-hoc note exposes nothing. Real enforcement needs `asyncio.wait_for` with a shrinking budget passed into each stage.

Ironically, `agent_runtime.py:156` already does this correctly:

```python
result = await asyncio.wait_for(agent.run(input, tools), budget.deadline_seconds)
```

...but see §4.1 — that module is never used.

### 3.3 Source-disagreement detection — the auditor cannot say "supported"

Claimed: *"Source disagreement detection — when claim appears in only some fetched sources, status is 'unsupported'."*

The default auditor (`DYLA_AUDITOR_PROVIDER=local`, the value in `.env.example`) is `_TextComparator`. It decides support by **exact normalised substring match** of the entire claim inside the document:

```python
claim_present_in_all = all(claim_text in text for text in normalized_texts)
```

A synthesised claim essentially never appears verbatim in a source page. Demonstrated:

```
claim:  "Infosys reported revenue of 1,53,670 crore rupees in FY2024."
source: "Infosys Limited reported consolidated revenue of Rs 1,53,670 crore
         for the financial year 2024, up 4.7% year on year."
verdict → ('unsupported', 'The claim text was not found in any independently fetched sources.')
```

A source that plainly supports the claim is marked unsupported. Only a source that copies the claim word-for-word passes.

The brief warns "an auditor that approves everything is telling us nothing." The mirror image is equally uninformative: **this auditor rejects everything**, so its verdicts carry no signal, and every run is driven to `incomplete` by the quality gate. It also means the "disagreement" branch is unreachable in practice — you cannot detect partial agreement with a matcher that never matches.

**Why the tests didn't catch it:** `tests/unit/test_auditor.py` uses toy fixtures where the claim text is literally `"supported"` and the document text is literally `"source"`. The fixtures are constructed so verbatim matching is trivially correct. The tests pass and prove nothing about real prose.

### 3.4 Cost-in-rupees tracking — unreachable, and the rate is invented

Two problems:

1. It lives in `evaluation.py`, which does not compile (§2.1). The feature cannot be executed.
2. The conversion rate is a placeholder:
   ```python
   RUPEES_PER_ADAPTER_UNIT = 0.8  # Conversion rate; adjust based on actual adapter pricing
   ```
   The brief asks for "cost per question in tokens and rupees." Multiplying an internal unit by a made-up 0.8 is not a rupee figure. This needs real per-1K-token pricing for the configured model, from the provider's price list.

---

## 4. Structural gaps against the brief

### 4.1 The agent runtime is orphaned

`agent_runtime.py` (185 lines) implements `AgentRuntime`, `ToolRegistry`, `BudgetLedger`, `BudgetedModel` — budget enforcement, tool registration, deadline handling, trace events. The design spec presents it as the shared substrate: *"The analyst and auditor share a small agent runtime that owns system instructions, input/output schemas, tool registration, memory access, budgets, retries, and trace events."*

Grep says otherwise. Nothing outside the module imports it. `AnalystAgent` and `AuditorAgent` call providers directly. `Budget`, `AgentInput`, `AgentResult` are defined in `domain.py` and used only by the orphan module and its own tests.

Consequences: no token budget enforcement, no cost ceiling, no request cap, no deadline — the very machinery the brief asks for exists and is disconnected. It is 224 lines of tests validating code that never runs in production. **The write-up must either wire it in or delete it**; leaving it looks like the architecture diagram was implemented but never connected.

### 4.2 Missing deliverables

| Brief requirement | Status |
|---|---|
| Eight questions of increasing difficulty | Well designed in `DEFAULT_QUESTIONS`, with an explicit difficulty/reuse map |
| ≥2 questions reusing earlier entities | Q5–Q8 reuse Zerodha / Infosys / Wipro / Zepto |
| **Actually run them and publish the trace** | No `logs/`, no `reports/`, both gitignored |
| Full per-question trace (plan, every tool call, course corrections) | Tracing code is solid; no captured output committed |
| Cost per question in tokens and rupees + trend | Table generator exists but cannot run; no data |
| "What you changed between runs and why" | Absent |
| Auditor run across analyst answers + "what it caught" | Absent |
| Honest account of auditor limits | Absent |
| Adversarial-analyst experiment | No such prompt anywhere (`grep -i adversarial` → nothing) |
| Write-up | Absent |

The brief states plainly that the write-up carries more weight than most candidates assume, and that missing logs stop the read. This is the largest scoring gap in the project and it is not a coding problem.

### 4.3 Cross-checking is weaker than advertised

The brief asks the agent to "cross-check claims that appear in only one source." `analyst.py:186` only requires two independent sources when the model self-reports `low`/`medium`/`weak` confidence:

```python
if claim.confidence.casefold() in {"low", "medium", "weak"} and len({...}) < 2:
```

A model that labels everything `high` — the common failure mode at `temperature=0` — bypasses corroboration entirely. The gate depends on the honesty of the component being gated.

### 4.4 Smaller issues

- `cli.py:_build_memory` takes `settings`, immediately does `del settings`, and hardcodes `MemoryStore()` → `dyla.db` in the CWD. Database location is unconfigurable, and the working directory silently determines which memory you get.
- `dyla audit <run-id>` does not audit. It greps `claim_audited` events out of an existing trace. The README's framing ("show audit verdicts for a past run") is accurate; the design spec's `dyla audit runs/run-001.json  # audit a saved answer` is not.
- `memory.search_memory` does `SELECT rowid, * FROM memory_records ORDER BY rowid` and scores every row in Python. Fine at current scale, but it is a full table scan per query, and the schema creates `memory_records_text` — an index on a free-text column that no query can use.
- Design spec references `runs/` for replayable artifacts; only `logs/` is implemented.

---

## 5. What is genuinely good

Worth stating plainly, because the defects above are concentrated in one commit and shouldn't obscure the foundation:

- **Provider neutrality is real.** `ports.py` protocols, `provider_factory.py` with `module:function` plugin support, adapters for compatible/Azure/Qdrant/local. Swapping providers is configuration, not code.
- **SSRF defence in `web.py`** is better than most production code: HTTPS-only, DNS pre-resolution, rejection of private/loopback/link-local/reserved/multicast ranges — *and* an honest module docstring admitting the residual TOCTOU/DNS-rebinding window it cannot close. That kind of self-reported limitation is exactly what the brief's "Yes" pile rewards.
- **Citation integrity.** `_citation_maps` rejects any claim whose citation doesn't map back to actually-retrieved evidence, which structurally prevents the model from inventing plausible-looking URLs.
- **Fail-closed quality gate.** `reliability.py` validates the trace file itself — unknown event types, cross-run contamination, unreadable traces all become issues.
- **Parallelism is real.** `asyncio.gather` over subqueries and over page fetches, with `return_exceptions=True` and per-failure limitations recorded rather than swallowed.
- **Failures surface as limitations, not silence.** Failed search, failed fetch, failed ingest, unapplied date constraints each append a human-readable limitation to the answer. This directly serves "state plainly when it cannot find something."
- **The question suite is thoughtfully constructed**, with the difficulty ladder and entity-reuse map documented in the source.

---

## 6. Recommended order of work

**P0 — restores the gate (hours)**
1. Fix the three f-strings in `evaluation.py`; confirm `pytest -q` runs all 210 tests and `dyla --help` works.
2. Add a CI job pinned to Python 3.11 so a version-specific syntax error can never ship again.

**P1 — makes the auditor mean something (days)**
3. Replace `_TextComparator`'s substring match with numeric/entity/date overlap scoring, or make the model comparator the default and treat `local` as a clearly-labelled offline stub. Add fixtures with *real* paraphrased prose, not `"supported"`/`"source"`.
4. Wire `_was_previously_rejected` in, and fix the inverted `verified` condition.
5. Enforce the 120s ceiling with `asyncio.wait_for` and a shrinking budget — reuse `AgentRuntime`, or delete it and enforce in the orchestrator.

**P2 — the deliverables that are actually scored (days)**
6. Run the eight questions live. Commit `logs/` and `reports/` (un-ignore them, or add a `reports/committed/` path).
7. Replace `RUPEES_PER_ADAPTER_UNIT = 0.8` with real provider pricing.
8. Run the auditor over the analyst's answers and write up **what it caught**, including its limits.
9. Add the adversarial-analyst variant and measure the behaviour delta.
10. Write the write-up: why the architecture is shaped this way, what was tried and rejected with evidence, and the known weaknesses — §3 and §4 of this document are a starting draft.

---

## 7. Evidence index

| Finding | How it was verified |
|---|---|
| CLI fails to start | `.venv/bin/dyla --help` → `SyntaxError` |
| 3 collection errors, 0 tests run | `.venv/bin/pytest -q` |
| 195 pass without the broken files | `pytest -q --ignore=...` ×3 |
| Auditor rejects a supporting source | Direct `_TextComparator().compare()` call with paraphrased prose |
| `_was_previously_rejected` never called | `grep -n` across `src/` |
| `verified` means "supported" | `memory.py:save_claim` → `int(verdict.status == "supported")` |
| `AgentRuntime` unused | `grep -rn "AgentRuntime\|ToolRegistry\|BudgetLedger"` outside its module → empty |
| No adversarial prompt | `grep -rin "adversarial\|auditor will" src/` → empty |
| No logs/reports/write-up | `git ls-files`; `ls logs reports` → no such directory |
| No GitHub issues or PRs | `gh issue list --state all`; `gh pr list --state all` → both empty |
