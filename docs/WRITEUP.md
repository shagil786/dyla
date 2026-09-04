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
| 1 | GST rate on restaurant services | incomplete | 1 | 8 |
| 2 | Zerodha CEO and year | complete | 1 | 9 |
| 3 | Three largest Bengaluru software exporters | complete | 1 | 9 |
| 4 | Quick-commerce rounds above $100M in 2025 | complete | 1 | 9 |
| 5 | Zerodha CTO and academic background | complete | **0** | 4 |
| 6 | Infosys vs Wipro full-year revenue | complete | **0** | 4 |
| 7 | Zepto valuation across rounds | complete | **0** | 4 |
| 8 | Profitability of all four companies | complete | **0** | 4 |

7 of 8 pass. Q1 is `incomplete` because the auditor rejected one of its claims —
covered in section 4.2, and it is an auditor false positive, not an analyst
error.

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
| 3 | 1333 | 1333 | — | 1→1 | 9→9 |
| 4 | 1200 | 1200 | — | 1→1 | 9→9 |
| 5 | 885 | 732 | −17% | 1→**0** | 7→4 |
| 6 | 997 | 551 | −45% | 1→**0** | 9→4 |
| 7 | 920 | 558 | −39% | 1→**0** | 7→4 |
| 8 | 1445 | 1227 | −15% | 2→**0** | 9→4 |
| **All 8** | **8704** | **7525** | **−13.5%** | 9→4 (−56%) | 67→51 (−24%) |
| **Q5–8 only** | **4247** | **3068** | **−27.8%** | 5→0 (−100%) | 32→16 (−50%) |

The trend is flat for the first four questions and then steps down, which is
what transferable memory should look like: nothing to transfer until something
has been learned.

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

Target: 50% reduction in cost per question. Measured: **13.5% across all eight
questions, 27.8% across the four that could reuse anything.** Searches fell 56%.

### Why it falls short, precisely

Reuse engages when an earlier question caused pages to be *attributed to the
entity a later question asks about*. Four of the eight questions could never
qualify:

- Q1 (GST) shares no entity with anything.
- Q2, Q3, Q4 are the *first* questions about their entities. There is nothing
  to transfer to them by construction.

So the honest denominator is Q5–Q8, where the reduction is 27.8%. Even there,
50% is out of reach because **the analyst still fetches the cited sources to
answer**. Memory removes the *search* step entirely (5→0) and halves fetches
(32→16), but the answer still has to be grounded in retrieved text, and that
text still has to be embedded and put in a prompt.

To halve total cost, memory would need to serve the *answer*, not just the
*retrieval* — i.e. answer from stored claims without re-reading sources. That is
a different and much less safe design, because it means trusting a prior
conclusion rather than the evidence under it. I did not build it, and I would
argue against building it for a system whose entire point is being auditable.

### What made the difference between 0% and 27.8%

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

32 claims. **31 supported, 1 contradicted, 0 uncited.**

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

This is a false positive with a clear cause: **the auditor has no notion of
scope.** It compares a claim to the highest-overlap sentence in a document
without checking that the sentence is about the same subset. It is the single
biggest weakness in the component and it is unfixed.

I am leaving Q1 failing rather than tuning the threshold until it passes. A
threshold tuned against one known case is a hardcoded answer wearing a
statistic's clothes.

### 4.3 Measuring the auditor properly: seeded defects

Since the analyst cannot produce bad claims, I planted them. `src/dyla/findings.py`
takes the real answers, mutates one claim at a time into a known-bad claim, and
audits each **alone** — batching would let a healthy neighbour's sources vouch
for the defective one, which is the cross-source masking bug that made this
auditor useless in the first place.

This is mutation testing pointed at a verifier instead of a test suite. The
detection rate is a property of the auditor, and is meaningful even though the
run that produced the answers is a replay.

| Defect class | First measurement | After fixes |
|---|---|---|
| `inflated_figure` — a number multiplied by 10 | 4/4 | 4/4 |
| `dropped_citation` — sources stripped off | 4/4 | 4/4 |
| `fabricated_claim` — plausible sentence, no support | 4/4 | 4/4 |
| `negated_claim` — polarity reversed | 3/4 | 3/4 |
| `swapped_entity` — true statement, wrong company | **0/4** | **4/4** |
| **Total** | **15/20 (75%)** | **19/20 (95%)** |

The remaining miss is the negation of the Q1 claim the auditor *already*
considers contradicted. Calling its negation "supported" is internally
consistent, so it is a symptom of 4.2, not an independent bug.

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

- **No scope reasoning.** Section 4.2. The largest known defect.
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
2. **The auditor has no scope reasoning** (4.2) and currently fails Q1 because
   of it.
3. **Removing Azure is a breaking change** for anyone who was using those
   adapters. Nobody here was, and the alternative was carrying ~830 lines of
   knowingly-broken, untestable, credential-gated code — but it is a break and
   it belongs on this list rather than in a footnote.
4. **Extra credit not achieved** — 27.8%, not 50% (§3).
5. **The suite seeds four entities before running.** `scripts/run_suite.py::seed_entities`
   pre-registers Zerodha, Infosys, Wipro and Zepto, because entity resolution is
   deterministic and does not invent entities from free text. Without it the
   resolver returns "unknown" and reuse can never engage. A real deployment
   accumulates these over time; doing it up front keeps the harness honest about
   what it measures rather than silently measuring nothing. But it *is* a
   thumb on the scale and it belongs in this list.
6. **Single-source cross-checking is bypassed** when the model self-labels a
   claim "high confidence" — i.e. the check is skipped exactly when the model is
   most sure, which is when overconfidence lives.
7. **`search_memory` full-scans in Python.** Fine at 14 pages, not at 14,000.

---

## 7. The strongest evidence in this project

Three of the bugs above — entity overwrite, planner blindness, and the empty
comparator snapshot — were invisible to a fully green test suite. All three were
found by running eight questions in order and looking at what the numbers did.

A shorter repro did not reproduce them. An isolated Q2→Q5 script **passed** while
the full suite failed, because the corruption required a third question in
between to trigger it.

> Sequence-dependent state corruption is structurally invisible to unit tests
> and to short repros. The only thing that finds it is the whole run.

That is also why `logs/` is scratch and `runs/` is committed: the trace of the
full sequence is the artifact that has repeatedly been worth more than the
assertions.
