# Analyst and Auditor — write-up

This document is the honest account of what was built, what was measured, what
broke, and what still does not work. Numbers in it come from committed
artifacts (`reports/`, `runs/`) and can be regenerated with one command.

---

## 0. The thing you should know before anything else

**Every number about answer quality in this repository comes from a recorded
fixture corpus, not from a live LLM.** No API keys were available for this work.
Rather than fake a run, the suite ships an offline harness: 14 recorded pages, a
hashed bag-of-words embedder, and an *extractive* model that answers by quoting
source sentences verbatim.

That choice has a consequence I want stated before the good numbers, not after:

> The offline model **cannot hallucinate**. It quotes. So a 97% "supported" rate
> from the auditor measures the model's inability to lie, not the auditor's
> ability to detect lying.

Everything in this write-up is scoped accordingly. Claims about *plumbing* —
planning, parallelism, memory transfer, deadline enforcement, cost accounting,
auditor logic — are backed by the harness and are real. Claims about *model
honesty* are not made, because the harness cannot test them. Section 4 explains
what was done instead to get a real measurement of the auditor.

Run it yourself:

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/run_suite.py            # 8 questions, ~0.3s, no keys
.venv/bin/python scripts/run_suite.py --no-reuse # the baseline it is compared to
```

---

## 1. What the run actually did

Eight questions of increasing difficulty, run in order, sharing one memory.
Questions 5–8 deliberately revisit entities from questions 2–4.

| # | Question | Result | Searches | Fetches |
|---|---|---|---|---|
| 1 | GST rate on restaurant services | complete | 1 | 8 |
| 2 | Zerodha CEO and year | complete | 1 | 9 |
| 3 | Three largest Bengaluru software exporters | complete | 3 | 9 |
| 4 | Quick-commerce rounds above $100M in 2025 | complete | 1 | 8 |
| 5 | Zerodha CTO and academic background | complete | **0** | 4 |
| 6 | Infosys vs Wipro full-year revenue | complete | **0** | 3 |
| 7 | Zepto valuation across rounds | complete | **0** | 3 |
| 8 | Profitability of all four companies | complete | **0** | 3 |

8 of 8 pass. (Q1 used to fail on an auditor false positive — the scope bug
dissected in section 4.2. It is fixed, and the committed traces now show the
fixed behaviour; the pre-fix trace is preserved in git history, not in the
working tree.)

Two things about how to read the Searches/Fetches columns, because both changed
while this project was measured. First, the Fetches column counts evidence
fetches **plus** the auditor's independent re-fetches of every cited URL: on
Q5–Q8 the analyst fetches nothing (0 evidence fetches — pure reuse) and all
3–4 fetches are the auditor doing its job. Second, neither column counts the
cross-check: corroboration adds 14 searches and 24 fetches across the suite
(analyst metrics `corroboration_searches`/`corroboration_fetches`), accepting
10 claims and rejecting 4, and every one of those decisions is now a
`claim_corroborated` trace event naming the confirming source or the reason
there wasn't one. Section 4.7 has the detail.

Full logs, one file per question, with the plan, every tool call, every result
and every course correction: `runs/reuse/qNN-*.jsonl`. The `--no-reuse` baseline
is in `runs/no-reuse/`. Cost tables: `reports/evaluation.md`. Auditor findings:
`reports/auditor-findings.md`.

---

## 2. Cost per question, and the trend

Cost is reported in tokens and in rupees. It is reported here as `unpriced`,
and that is deliberate — see 2.2.

### 2.1 The trend

Total tokens per question (input + output + **embedding**), reuse vs baseline:

| Q | Baseline | With memory | Change | Searches | Fetches |
|---|---|---|---|---|---|
| 1 | 910 | 910 | — | 1→1 | 8→8 |
| 2 | 1014 | 1014 | — | 1→1 | 9→9 |
| 3 | 1427 | 1427 | — | 3→3 | 9→9 |
| 4 | 1200 | 1200 | — | 1→1 | 8→8 |
| 5 | 981 | 828 | −16% | 3→**0** | 7→4 |
| 6 | 1132 | 686 | −39% | 4→**0** | 8→3 |
| 7 | 1032 | 641 | −38% | 2→**0** | 8→3 |
| 8 | 1916 | 1684 | −12% | 4→**0** | 8→3 |
| **All 8** | **9612** | **8390** | **−12.7%** | 19→6 (−68%) | 65→47 (−28%) |
| **Q5–8 only** | **5061** | **3839** | **−24.1%** | 13→0 (−100%) | 31→13 (−58%) |

The trend is flat for the first four questions and then steps down, which is
what transferable memory should look like: nothing to transfer until something
has been learned.

These numbers moved since the last write-up (13.5% → 12.7%, 27.8% → 24.1%),
and the reason is worth stating because it is a behaviour change, not a
measurement change: durable memory used to hold only the previous run's claims
— every run overwrote the last run's rows under the same bare `c1`..`cN` IDs —
and now it holds all of them (`memory_hits` 7 → 61 per suite). The planner
reads that memory and expands entity-prefixed subqueries from it, so both
modes plan more searches than before (Q3: 1 → 3) while reuse still skips every
search from Q5 on. Memory that actually remembers costs a little more to
consult and saves a little less in net terms. That is the honest direction for
a memory feature to move the numbers: the old saving was measured against a
memory that forgot.

### 2.2 Why rupees says `unpriced`

The repository previously multiplied an internal "adapter unit" by a constant
`0.8` and printed the product as rupees. That constant was invented. It was not
a price of anything.

Inventing a cost figure is precisely the failure the auditor exists to catch,
so it is deleted. `src/dyla/pricing.py` now holds real published per-token
prices (gpt-4o-mini at $0.15/$0.60 per 1M, gpt-4o at $2.50/$10.00, and others,
each with the date checked) and a USD/INR rate of 94.5 checked on 2026-09-05
and overridable via `DYLA_USD_TO_INR`.

If the model is unknown, the report says **`unpriced`** and tells you exactly
which two environment variables to set. It never prints `0`. A zero would be a
lie that looks like a measurement; `unpriced` is a gap that looks like a gap.

Set a real model and the rupee column populates:

```bash
DYLA_PRICE_INPUT_PER_MTOK_USD=0.15 DYLA_PRICE_OUTPUT_PER_MTOK_USD=0.60 \
  .venv/bin/python scripts/run_suite.py --live
```

---

## 3. The extra credit: halve cost per question via transferable memory

**I did not achieve it as specified, and I am not going to round up to it.**

Target: 50% reduction in cost per question. Measured: **12.7% across all eight
questions, 24.1% across the four that could reuse anything.** Searches fell 68%.

### Why it falls short, precisely

Reuse engages when an earlier question caused pages to be *attributed to the
entity a later question asks about*. Four of the eight questions could never
qualify:

- Q1 (GST) shares no entity with anything.
- Q2, Q3, Q4 are the *first* questions about their entities. There is nothing
  to transfer to them by construction.

So the honest denominator is Q5–Q8, where the reduction is 24.1%. Even there,
50% is out of reach because **the analyst still fetches the cited sources to
answer**. Memory removes the *search* step entirely (13→0) and more than halves
fetches (31→13), but the answer still has to be grounded in retrieved text, and
that text still has to be embedded and put in a prompt.

To halve total cost, memory would need to serve the *answer*, not just the
*retrieval* — i.e. answer from stored claims without re-reading sources. That is
a different and much less safe design, because it means trusting a prior
conclusion rather than the evidence under it. I did not build it, and I would
argue against building it for a system whose entire point is being auditable.

### What made the difference between 0% and 24.1%

The first measurement of the reuse feature showed **exactly 0% token savings**.
Two separate silent bugs, both invisible to 267 passing unit tests, and both
found only by running the full eight-question sequence in order:

**Bug 1 — entity attribution was destroyed on re-ingest.** A chunk's ID is
`sha256(source_id:position:content_hash)` — a pure content hash carrying no
entity information. Re-ingesting a page while researching a *different* entity
overwrote its `entity_ids` instead of merging them. Q3 (which never names
Infosys) re-ingested the Infosys pages with an empty entity list and silently
un-tagged them. No error, no failing test — just memory reuse quietly never
engaging. `LocalVectorStore.upsert()` now unions.

**Bug 2 — the planner could not see the entity store.** It derived entities only
from the text of retrieved memory *records*, so a question whose wording didn't
overlap a stored record produced zero entities, no filter, and no reuse.
Knowledge transferred across paraphrases but not across questions.

**And then a third, which is the interesting one.** After fixing both, only Q5
and Q8 reused anything. Q6 (Infosys vs Wipro) still hit the web, even though Q3
had already fetched exactly the right pages. Because pages were tagged with the
entities *the question named*, and Q3's question is "the three largest software
services exporters headquartered in Bengaluru" — it names no company at all. The
pages were about Infosys; the query was not.

Attribution now follows **page content**, not the query that found the page
(`AnalystAgent._entity_ids_from_content`). Q6 and Q7 dropped to zero searches.
That single change took the saving from 19% to 38% of embedding tokens.

### The honest caveat

The entity-merge fix originally landed in `LocalVectorStore` only. **Qdrant has
since been fixed too** — and it mattered more there: Qdrant replaces a point's
payload wholesale on upsert, so for anyone actually running Qdrant this was
live data corruption, not a latent risk. The fix reads the stored `entity_ids`
and unions them before writing, and the read is deliberately non-fatal: losing
attribution is recoverable on a later run, losing the ingestion is not. Five
tests cover it with a fake client, and I checked they fail when the merge is
removed rather than assuming they would.

**Azure AI Search had the bug too, and was deleted rather than fixed.** It was
unused, it was the *default* for three of the five provider roles despite
needing credentials nobody had, and shipping a knowingly-broken adapter to
support a provider no one runs is worse than not shipping one. That removal
also fixed a quieter problem: a fresh checkout used to default to Azure, so the
configuration a new reader got was one that could not possibly work. Every role
now defaults to `local`, which is the configuration the tests actually
exercise.

---

## 4. The auditor — Part B

A second agent independently re-fetches every cited URL (it never sees the
analyst's evidence) and marks each claim supported / unsupported / contradicted,
flagging uncited claims.

### 4.1 What it caught on the analyst's own answers

28 claims. **28 supported, 0 objected, 0 uncited.** (No-reuse mode: 29 claims,
also all supported — the one-claim difference is a fourth corroboration
rejection in reuse mode, section 4.7.)

That is a bad result to present, because as section 0 said, it measures nothing.
An extractive model that quotes verbatim will pass any verifier.

### 4.2 The one real objection — and it is the auditor's fault

> **Q1 · contradicted** — "Restaurant services in India are taxed at 5% GST
> without input tax credit for standalone restaurants."
>
> Auditor: *"the source states the opposite polarity of the claim. Source text:
> 'Restaurants located within hotels where the declared room tariff exceeds
> 7,500 rupees per night are taxed at 18% GST **with** input tax credit.'"*

The claim is correct. The source is correct. They describe **different cases** —
standalone restaurants versus restaurants inside expensive hotels. The auditor's
polarity check found "with input tax credit" against the claim's "without",
matched on topical overlap, and called it a contradiction.

This is a false positive with a clear cause: **the auditor had no notion of
scope.** It compared a claim to a high-overlap sentence in a document without
checking that the sentence is about the same subset.

**Fixed.** Polarity contradiction is now scope-gated and negation parity is
judged per shared word:

1. **Scope gate.** A sentence may contradict a claim only when no
   *better-matching* sentence stays silent. Here the source's first sentence
   restates the claim verbatim and stays silent; the weaker hotel sentence
   therefore cannot veto it. Contradiction by polarity is legitimate only when
   the conflicting sentence is the best available statement about the claim —
   or every better statement conflicts too.
2. **Per-word negation parity.** A negation clause both sides share (the
   "without input tax credit" in the claim *and* in its source) cancels before
   polarity is decided. This is what lets the auditor call the *negation* of
   the Q1 claim — "…are **not** taxed at 5% GST without input tax credit…" —
   contradicted while calling the claim itself supported: the shared "without"
   clause no longer masks the real "not".

Both rules are general — no fixture wording appears in the discriminator — and
the seeded-defect audit still holds at 20/20. The full suite now runs **8/8**,
and the committed traces show the fixed behaviour. This section keeps dissecting
the false positive because the failure is more instructive than the fix; the
pre-fix Q1 trace is preserved in git history
(`a7a32eb:runs/reuse/q01-…jsonl`, `claim_audited` with `c1` → `contradicted`),
not in the working tree. The run-history trend table in `reports/evaluation.md`
shows the same landing: sixteen 7/8 runs, then 8/8 from the fix on.

### 4.3 Measuring the auditor properly: seeded defects

Since the analyst cannot produce bad claims, I planted them. `src/dyla/findings.py`
takes the real answers, mutates one claim at a time into a known-bad claim, and
audits each **alone** — batching would let a healthy neighbour's sources vouch
for the defective one, which is the cross-source masking bug that made this
auditor useless in the first place.

This is mutation testing pointed at a verifier instead of a test suite. The
detection rate is a property of the auditor, and is meaningful even though the
run that produced the answers is a replay.

| Defect class | First measurement | After fixes | Final (post 4.2 fix) |
|---|---|---|---|
| `inflated_figure` — a number multiplied by 10 | 4/4 | 4/4 | 4/4 |
| `dropped_citation` — sources stripped off | 4/4 | 4/4 | 4/4 |
| `fabricated_claim` — plausible sentence, no support | 4/4 | 4/4 | 4/4 |
| `negated_claim` — polarity reversed | 3/4 | 3/4 | **4/4** |
| `swapped_entity` — true statement, wrong company | **0/4** | **4/4** | 4/4 |
| **Total** | **15/20 (75%)** | **19/20 (95%)** | **20/20 (100%)** |

The one miss was the negation of the Q1 claim the auditor *already* considered
contradicted. Calling its negation "supported" was internally consistent —
exactly why it was a symptom of 4.2, not an independent bug, and why the 4.2
fix closes it: with the healthy claim now correctly supported, the polarity
check is free to read "are **not** taxed at 5% GST" as the reversal it is.
Per-word negation parity is the specific change that catches it: the "without
input tax credit" clause appears on both sides and cancels, leaving the
claim-side "not" with no counterpart. Measured after the fix: **20/20**.

### 4.4 `swapped_entity` 0/4 — the unexpected result

The auditor marked **"Nithin Kamath is the chief executive officer of Infosys"**
as *supported*, against a page about Zerodha.

It matched on wording. It matched on numbers. The only thing wrong with the
sentence was the name — and the name was the one thing nothing checked. A
verifier that checks facts but not *who the facts are about* will approve a
citation-shaped lie every time.

`verification.unmentioned_entities` closes it: if a claim is attributed to an
entity that **no cited source mentions at all**, that finding invalidates every
other check, because matching numbers and matching wording are then evidence
about something else. It is reported as `unsupported`, never `contradicted` — a
page that doesn't mention Infosys is not a page denying the sentence. Silence is
not denial.

### 4.5 Two obvious approaches, tried, measured, rejected

**Substring matching.** The original auditor asked `claim_text in source_text`.
Real sources paraphrase, so this marked *every* claim unsupported — an auditor
that rejects everything carries exactly as much information as one that approves
everything. Replaced by slot-based verification over numeric facts, years and
content words.

**Treating every capitalised token as an entity.** The first version of the
misattribution check did this and immediately flagged `FY2024` as an
"unmentioned entity" against a source reading "financial year 2024" — turning
**five correct verdicts wrong**. Digit-bearing tokens are period labels, already
checked by the year extractor; checking them again as entities only adds a
spelling requirement the sources never agreed to. Excluded.

**Snapshotting known entity names at construction.** Looked equivalent to reading
them live. It is not: the auditor is built *before* the first question runs, so
the snapshot was always empty, and every entity discovered during the run was
invisible to the misattribution check. This silently held detection at 50% when
it should have been 100%. The comparator now reads memory per comparison.

### 4.6 The auditor's limits, stated plainly

- **Scope reasoning is heuristic, not semantic.** Section 4.2's false positive
  is fixed by a rank-ordered scope gate (a sentence contradicts only when no
  better-matching sentence stays silent), but scope is measured by word
  overlap, not by understanding which subset a sentence describes. A source
  that restates the claim better in *wording* while meaning something narrower
  can still suppress a genuine contradiction.
- **No co-reference.** "The company reported X" is matched by topical word
  overlap, not by knowing which company "the company" is.
- **Regex sentence segmentation**, which mis-splits on abbreviations.
- **A fixed antonym/negation table.** Paraphrased reversals are missed.
- **Two-entity sentences can false-positive** when a number belongs to the other
  entity.
- **A deliberate blind zone**: numeric differences between 1% and 5% are
  reported as unverified, neither confirmed nor contradicted. An auditor that
  cries contradiction over rounding is useless; one that forgives 5% is
  negligent. The gap is honest about not knowing.
- **Misattribution detection is weaker without memory.** Mid-sentence names are
  always checked, but distinguishing a sentence-initial *company name* from a
  sentence-initial *ordinary word* requires knowing which names are entities.
  With no memory attached the auditor is weaker here — never wrong in a new way,
  but blinder.
- **And the harness cannot test model honesty at all.** Section 0.

### 4.7 The cross-check is not keyed on self-reported confidence (P4-2)

The analyst's pre-synthesis rejection loop originally cross-checked a claim
only when the model labelled it `low`/`medium`/`weak` **and** it rested on one
source. That is backwards in exactly the way overconfidence is backwards: a
model that labels every claim "high" bypasses corroboration entirely, and
confidence is a model output, so the check is keyed to the thing being
checked.

The gate now runs on properties the model does not control. A single-source
claim is cross-checked when it carries a figure or a year, or when the model
flagged low confidence — unless a prior run's *supported* verdict already
covers it (the auditor's independent fetch is stronger evidence than a fresh
cross-check; the stored wording must also agree on the figure, since the
restatement fingerprint ignores numbers by construction). The cross-check
re-fetches candidate pages through the search provider, skips the claim's own
citations, and accepts only when an independently fetched, on-topic page
states the claim's facts (`verification.corroborates` — topical overlap plus a
matching numeric fact or year, falling back to restatement overlap for
figure-free claims). New metrics `corroboration_searches` and
`corroboration_fetches` count the work; `claim_rejected` now records
`corroboration_sources_checked` alongside its reason.

**The corroborating page is deliberately never attached to the claim.** It is
not added to `claim.citations` and is never returned as a `Citation`. The
auditor re-fetches exactly the sources a claim cites; making it verify against
a paraphrased page it was never asked about would manufacture the §4.2 class
of false contradiction in a new place. This diverges from the design spec's
evidence-gate sketch (which contemplated the auditor itself re-checking from
the run's gathered evidence); the divergence is the point — the auditor must
judge claims against their citations, and the analyst must not widen them
after the fact.

Measured on the deterministic suite (fresh DB, committed runs): the
seeded-defect audit holds at **20/20** and the suite at **8/8** in both modes;
and the planted second source that states Infosys revenue as 1,53,670 crore
(the corpus's `quick-summaries/infosys-revenue-note`) is rejected in no-reuse
runs where the pre-P4-2 baseline carried it as a supported claim.
Corroboration cost the no-reuse run 13 searches and 24 fetches; it rejected
three claims — the two restatements of the planted wrong figure and one
genuine-but-single-source valuation sentence ("The round valued Zepto at 5
billion dollars", which no other corpus page states). Reuse mode cost 14
searches and 24 fetches and rejected four: the $5B sentence twice, the Wipro
net-profit figure (13,135 crore, single source), and "He joined Zerodha in
2013." Every cross-check, accepted or not, is a `claim_corroborated` trace
event naming the confirming source or the count checked (14 events in the
reuse traces, 13 in no-reuse — exactly the `corroboration_searches` metrics);
rejections additionally carry `claim_rejected` with reason
`insufficient_corroboration`. Nothing is deleted from the trace. The offline
corpus is small and deliberately single-source-per-fact, so this is the honest
upper bound of what the cross-check can confirm offline; a live run would be
the real test, and that remains unavailable (Section 0).

### 4.8 The adversarial-analyst experiment (P3-3) — a negative result, honestly bounded

The brief's "take it further" asks what happens when the analyst is told an
auditor will check every claim: does citation quality improve, or does it
start citing authoritative-looking sources that don't support the claim? The
experiment is cheap to run — same suite, two system prompts, diff the verdict
distribution — so it was run, and the offline result is exactly nothing:
**all eight questions byte-identical** (answers, claims, citations, verdicts)
in both reuse and no-reuse modes (`runlogs/P3-3-result-*.txt`,
`scripts/experiment_adversarial_analyst.py`).

That nothing is the *expected* negative result, and claiming it as evidence
about model honesty would be dishonest. `OfflineModel` is an extractive
stand-in: it answers by quoting supplied evidence sentences verbatim, recovers
the question and evidence blocks by marker, and never reads the system
message. An extractive model structurally cannot hallucinate a citation, so it
also cannot *choose* better ones under threat — the system prompt is inert to
it by construction. The invariance is pinned in `tests/unit/test_offline.py`
so the harness cannot silently start pretending otherwise. P3-3 therefore
remains a live-key experiment: the recorded-fixture harness can demonstrate
plumbing (claims are rejected, traces record why) but not model honesty, and
no live key was available (Section 0).

---

### 4.9 Declining to answer — three routes, only two of them traced

The brief requires that the agent *"state plainly when it cannot find something
rather than filling the gap with a plausible guess."* This section is the
account of how that is implemented, and of an asymmetry in it that was found
while writing tests rather than while writing the feature.

There are **three** routes to `"Insufficient evidence."`, and they are not
equivalent:

| Route | Trigger | Model consulted? | `answer_withheld` | Limitation, and who wrote it |
|---|---|---|---|---|
| **1** | No evidence retrieved — `_synthesize` returns early (`analyst.py:371`) | **No** | **not emitted** | `No retrieved evidence was available.` — the analyst's |
| **2** | Evidence retrieved, model proposes zero claims (`analyst.py:504`) | Yes | `model_proposed_no_claims` | `No supplied evidence answered the question.` — the **model's**, passed through |
| **3** | Model proposes claims, validation strikes all of them (`analyst.py:504`) | Yes | `no_claim_survived_validation` | per-claim rejection notes |

Route 1's trace ends at retrieval:

```text
started -> memory_retrieved -> query_expanded -> plan_created -> web_searched
        -> evidence_selected (count: 0) -> completed
        -> started -> completed -> memory_saved
        -> quality_completed (status: unaudited)
```

No `answer_synthesized`, no `answer_withheld`, no `claim_rejected`. Routes 2 and
3 both emit the decision; they differ in `claims_proposed` (0 vs >0) and in
whether a `claim_rejected` precedes it:

```text
Route 2: ... evidence_selected (count: 1)
             -> answer_synthesized {"claims_proposed": 0, "claims_kept": 0,
                                    "claims_rejected": 0, "bailed_out": true}
             -> answer_withheld    {"reason": "model_proposed_no_claims"}

Route 3: ... evidence_selected (count: 1) -> claim_rejected
             -> answer_synthesized {"claims_proposed": 1, "claims_kept": 0,
                                    "claims_rejected": 1, "bailed_out": true}
             -> answer_withheld    {"reason": "no_claim_survived_validation"}
```

**Why Route 1 is silent, deliberately.** There was no answer to decline, because
there was nothing to answer from — `_synthesize` returns before the model is
called at all. Four pre-existing tests prove it by supplying a model whose
`complete()` raises `AssertionError("empty evidence must not synthesize")` —
covering no evidence at all, and all searches, all fetches and all ingestions
failing — and the new Route 1 trace test reuses the same device. Emitting `answer_withheld` there would record a decision the
agent never made.

**Why the distinction earns its keep.** Route 1 means *retrieval* found nothing;
Route 2 means retrieval worked and *extraction* failed. Those have different
fixes — widen the search, or lower the extractive floor — and a trace that
collapsed them would send you to the wrong one. Note that the discriminator is
not only the event: Route 1's limitation is written by the analyst and Route 2's
by the model, so the two are separable from the answer alone.

Route 2 is also the route this harness actually hits. The extractive model
quotes a sentence only if it is at least 25 characters **and** shares a
non-stopword token with the question (`offline.py::_claims`), so a page that is
retrieved but does not lexically overlap the question is a likelier failure than
retrieving no pages at all.

Route 2 had no test coverage until this branch. `grep -rn
model_proposed_no_claims src/ tests/` matched exactly one line — its own
emission site — which means one branch of a two-way ternary was unpinned, and a
ternary is where two reason strings get swapped without anything else changing.
Two tests now cover it
(`test_a_model_that_proposes_nothing_is_traced_as_withheld`,
`test_the_empty_evidence_shortcut_is_not_traced_as_a_withheld_answer`), both
red-proven: flipping the ternary fails the new Route 2 test *and* the
pre-existing Route 3 test; deleting the `if not evidence` early return fails the
Route 1 test. Suite 319 → **321 passed**.

**Where the gate leaves all three.** The auditor iterates `answer.claims`, so an
empty list yields no verdicts, and `reliability.py` returns
`QualityResult("unaudited", ["no audit verdicts were produced"])`.
`evaluation.py:336` counts only `complete` and `passed`, so a correctly declined
question **does not** count as passed. That is the right call for a scored
suite — not answering is not an answer — but it does mean the gate cannot
distinguish a principled refusal from a pipeline that failed to retrieve
anything. The trace can, and that is where the distinction belongs; the score
should not reward declining.

None of the eight committed questions reaches any of these routes in either
mode: `grep -rl answer_withheld runs/` returns nothing, because every question
retrieves evidence and produces claims. So this is not a live defect. It is a
branch that was untested and undocumented, and the offline harness's most
likely real-world failure mode.

---

## 5. What changed between runs, and why

Committed run history is in `reports/evaluation.json` (`history`), which renders
a per-question verdict trend across the last 16 full-suite runs.

| Change | Effect |
|---|---|
| Default comparator replaced (substring → slot-based) | Verdicts went from all-`unsupported` to discriminating between paraphrase, rounding, contradiction and off-topic |
| Per-document evaluation instead of concatenated sources | Source disagreement became visible instead of masked |
| Feedback loop un-inverted | It had been collecting `verified == True` — it would have suppressed the auditor's *approved* claims |
| 120s ceiling enforced, not just measured | `asyncio.wait_for` + a cooperative deadline the auditor checks between claims |
| Entity merge on re-upsert | Q5 went 1 search → 0 |
| Content-based entity attribution | Q6, Q7 went 1 search → 0; embedding savings 19% → 38% |
| `embedding_tokens` added to cost fields | Measured savings went from a flat 0% to 13.5% — the saving had been real all along and invisible |
| Misattribution check | Seeded-defect detection 75% → 95% |
| Plan, rejections and retries traced | The four ways the analyst overrules its own model became machine-readable instead of prose buried in `limitations` |
| Redactor exemption for token counts | Every token count had been replaced with `[REDACTED]` in every trace |
| Scope-gated polarity (auditor, §4.2) | Seeded-defect audit 19/20 → 20/20; suite 8/8 |
| Real-run trace tests for the two silent reason codes | `insufficient_corroboration` had no trace-level assertion at all and `blocked_by_audit_feedback` was metric-only; both are now driven through genuine two-run traces and their emitted `reason` strings asserted |
| `DYLA_MEMORY_DB_PATH` (P4-1) | Memory location was hardcoded to `dyla.db` in the CWD and unconfigurable; the path now threads from settings through the CLI memory store and embedding cache, so two invocations from different working directories reach the same memory |
| Cross-check not keyed on self-reported confidence (P4-2, §4.7) | A model that labels every claim "high" used to bypass corroboration entirely; the cross-check now gates on properties the model does not control and re-fetches an independent source |
| Adversarial-analyst experiment (P3-3, §4.8) | Measured negative result: baseline and audit-threat prompts produce byte-identical outputs offline, as they must — the extractive stand-in never reads the system message. Needs a live key to mean anything |
| Dead `memory_records_text` index removed (P4-4) | Search never used it; the linear scan is now documented as deliberate |
| Spec text aligned with the shipped CLI (P4-3/P4-5) | `dyla audit` documented as reading saved traces (never re-auditing); spec examples match the real `runs/<mode>/qNN-*.jsonl` artifacts |
| Claim IDs run-namespaced in SQLite (P5-3) | Bare `c1`..`cN` IDs let every run overwrite the last run's rows — durable memory held one answer, not eight. `memory_hits` 7 → 61/suite; savings re-measured at 12.7% / 24.1% |
| Seeded probes made read-only (P5-4) | The defect audit used to persist its planted lies into `dyla.db`, overwriting real claims. `persist=False`; post-suite DB now holds 28 real claims, 0 fabricated |
| Accepted cross-checks traced (P5-5) | New `claim_corroborated` event; 24 confirming fetches per run previously left no record |
| Committed artifacts regenerated (P5-2) | `runs/` and `reports/` predated the §4.2 and P4-2 fixes (7/8, 19/20); now 8/8 + 20/20 both modes, reproducible with one command again |
| Provider-independence pins (P5-1) | 10 test functions / 16 collected cases: fresh-checkout local defaults, no-secret builds, any-URL `compatible` adapter, vendor names rejected |
| Dead `add_memory` API removed (P5-6) | Zero production callers; `save_claim` is now the store's only writer and all fixtures seed through it. Same precedent as the Azure and P4-4 deletions |

Two rows are worth pausing on.

**The redactor was eating the deliverable.** The credential filter matched the
substring `token`, so `model_tokens` — and any other `*_tokens` field routed
through it — was written to every trace as `[REDACTED]`. The cost report is
built from those numbers. A redactor careful enough to destroy the thing it was
protecting is not being careful. Credentials are singular (`access_token`);
counts are plural and suffixed, and that is what the exemption keys on.

**Adding trace events silently failed the entire suite.** The trace validator
holds an allowlist of event names, and an unrecognised event is treated as a
corrupt trace. Adding four events took the suite from 7/8 to **0/8** — with
every unit test still green, because no unit test ran a question end to end and
then validated the resulting trace. `tests/integration/test_trace_completeness.py`
now does, and I checked it fails when an event is removed from the allowlist
rather than assuming it would. The first version of that guard only exercised
the happy path, so deleting `claim_rejected` from the allowlist left it green —
a guard that only covers the path where nothing goes wrong does not cover the
events that exist for when something does.

That row about `embedding_tokens` is worth pausing on too. For one full measurement cycle the reuse
feature *appeared* to save nothing, and the reason was that the cost report did
not count the token type reuse actually saves. **The metric, not the feature,
was broken.** If I had trusted the report I would have reverted working code.

---

## 6. Self-identified weaknesses

Ranked by how much they would bother me in review.

1. **No live run.** Everything is a replay. Stated in section 0 and repeated in
   every artifact header.
2. **Auditor scope reasoning is heuristic.** The §4.2 false positive that
   failed Q1 is fixed (scope gate + per-word negation parity, seeded audit
   20/20), but scope is measured by word overlap, not semantics — §4.6 lists
   what that still cannot see.
3. **Removing Azure is a breaking change** for anyone who was using those
   adapters. Nobody here was, and the alternative was carrying ~830 lines of
   knowingly-broken, untestable, credential-gated code — but it is a break and
   it belongs on this list rather than in a footnote.
4. **Extra credit not achieved** — 24.1%, not 50% (§3).
5. **The suite seeds four entities before running.** `scripts/run_suite.py::seed_entities`
   pre-registers Zerodha, Infosys, Wipro and Zepto, because entity resolution is
   deterministic and does not invent entities from free text. Without it the
   resolver returns "unknown" and reuse can never engage. A real deployment
   accumulates these over time; doing it up front keeps the harness honest about
   what it measures rather than silently measuring nothing. But it *is* a
   thumb on the scale and it belongs in this list.
6. **The cross-check's notion of corroboration is lexical** (§4.7). The old
   high-confidence bypass is closed — the gate is now model-independent — but
   "independently states the figure" is decided by numeric-fact and overlap
   matching, and the offline corpus is single-source-per-fact, so the cross-check
   rejects genuine single-source claims it cannot confirm. Live search is the
   real test and remains unavailable.
7. **`search_memory` full-scans in Python.** Fine at 14 pages, not at 14,000.
   The scan is now documented as deliberate (the dead `memory_records_text`
   index was removed rather than kept as decoration); the replacement is FTS5
   or the embedding store when the corpus outgrows it.
8. **Memory that remembers makes the planner thirstier.** Fixing the claim-ID
   overwrite (memory now holds all eight answers, not one) raised retrieval
   searches in *both* modes — Q3 plans 3 subqueries where it planned 1 —
   because the planner expands entity-prefixed subqueries from everything it
   remembers. Reuse still skips every Q5–Q8 search, so the net effect is a
   smaller saving (24.1%, not 27.8%), but the coupling is one-directional:
   nothing tells the planner when extra breadth stops paying. A subquery
   budget, or reuse assessment *before* expansion rather than after, is the
   obvious next control.

---

## 7. The strongest evidence in this project

Three of the bugs above — entity overwrite, planner blindness, and the empty
comparator snapshot — were invisible to a fully green test suite. All three were
found by running eight questions in order and looking at what the numbers did.
Two more joined them this session: the claim-ID overwrite that left durable
memory holding one answer instead of eight, and the seeded-defect probes that
persisted their planted lies into `dyla.db`. Both were found by inspecting the
database after a full run; both were invisible to 302 passing tests.

A shorter repro did not reproduce them. An isolated Q2→Q5 script **passed** while
the full suite failed, because the corruption required a third question in
between to trigger it.

> Sequence-dependent state corruption is structurally invisible to unit tests
> and to short repros. The only thing that finds it is the whole run.

That is also why `logs/` is scratch and `runs/` is committed: the trace of the
full sequence is the artifact that has repeatedly been worth more than the
assertions.
