# Analyst and Auditor — write-up

This document is the honest account of what was built, what was measured, what
broke, and what still does not work. Numbers in it come from committed
artifacts (`reports/`, `runs/`) and can be regenerated with one command.

---

## 0. The thing you should know before anything else

**Every number about answer quality in this repository comes from a recorded
fixture corpus, not from a live LLM.** Rather than fake a run, the suite ships
an offline harness: 14 recorded pages, a hashed bag-of-words embedder, and an
*extractive* model that answers by quoting source sentences verbatim.

**Why there is no live run — the accurate version.** I previously wrote "no API
keys were available", which was true but incomplete, and incomplete in the
direction that flatters me: it implies a key is the only thing standing between
this repo and live results. It is not. The build environment has **no general
outbound internet**. Measured, not assumed:

| Target | Result |
|---|---|
| `files.pythonhosted.org`, `pypi.org` | HTTP 200 |
| `en.wikipedia.org`, `example.com`, `google.com` | connection closed at TLS |
| `api.openai.com`, `api.you.com` | connection closed at TLS |

DNS resolves and `validate_external_url` passes; the TLS handshake is then
terminated. Egress is allowlisted to the package index. So a You.com key would
authenticate against a host this sandbox cannot reach, and **the missing
ingredient is network egress, not a credential**. Both are needed; only one was
named before.

**Update: live mode has since been run once, off this machine.** The project
owner executed `dyla ask "Who is the current CEO of Microsoft?"` in an
environment with both keys and egress. It returned *Satya Nadella* with one
citation and one supported verdict, against real You.com search, a real
Wikipedia and microsoft.com fetch, NVIDIA `nemotron-3-embed-1b` embeddings and
Qdrant Cloud. The plumbing described in this section is therefore no longer
only *argued* to be real — it has carried one real question end to end.

Three qualifications, because one question is one question:

- **The suite has still never run live.** There are no live cost, recall or
  auditor-accuracy numbers, and every measurement below remains an
  offline-fixture measurement. Nothing in §2, §3 or §4 changes.
- **It immediately found a bug that only live mode could expose.**
  `_build_orchestrator` took no reuse flag, so `run_suite.py --live --no-reuse`
  would have built a reuse-enabled analyst, written the result to
  `evaluation-no-reuse.*` and compared it against an identical configuration —
  reporting a fabricated saving near zero in the one table §3 is built on. The
  offline builder had always threaded `reuse` through; the live one silently
  did not, and no test covered the live path because the live path had never
  been run. Fixed, with a regression test.
- **That bug is the argument for the rest.** The single most valuable thing one
  live execution produced was not the answer; it was the discovery that a
  documented flag did nothing. Anything still unexercised should be assumed to
  contain something similar.

This matters for reading §4: the analyst's own cross-check and the auditor's
independent re-fetch both do real HTTP through the same `PageFetcher` in live
mode. They are exercised here against the fixture provider, which implements
the identical `SearchProvider` interface. The plumbing is real and the wire is
not.

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

8 of 8 pass — but "pass" means every asserted claim was supported, not that the
question was fully answered. Measured separately, answer completeness is
**15/21 (71%)**, with Q7 and Q8 still at 1/4 each. §3 has the table, §3.1 the
three defects that took it from 13/21, and §3.2 why the rest is unfixed. Read the two numbers together; the
pass rate alone overstates this suite considerably.

(Q1 used to fail on an auditor false positive — the scope bug
dissected in section 4.2. It is fixed, and the committed traces now show the
fixed behaviour; the pre-fix trace is preserved in git history, not in the
working tree.)

Two things about how to read the Searches/Fetches columns, because both changed
while this project was measured. First, the Fetches column counts evidence
fetches **plus** the auditor's independent re-fetches of every cited URL: on
Q5–Q8 the analyst fetches nothing (0 evidence fetches — pure reuse) and all
3–4 fetches are the auditor doing its job. Second, neither column counts the
cross-check: corroboration adds its own searches and fetches across the suite
(analyst metrics `corroboration_searches`/`corroboration_fetches`), and every
one of those decisions is a `claim_corroborated` trace event naming the
confirming source or the reason there wasn't one — 14 in the committed traces,
against 4 `claim_rejected`. Section 4.7 has the detail.

The cross-check now reads *every* candidate rather than stopping at the first
agreeing one, which costs more fetches and is the only way a disagreement
ranked below a corroboration can be seen at all (§4.10). One
`disagreement_resolved` event appears in the committed traces: the planted
Infosys revenue conflict, resolved in favour of the filing over the summary.

Full logs, one file per question, with the plan, every tool call, every result
and every course correction: `runs/reuse/qNN-*.jsonl`. The `--no-reuse` baseline
is in `runs/no-reuse/`. Cost tables: `reports/evaluation.md`. Auditor findings:
`reports/auditor-findings.md`.

---

## 2. Cost per question, and the trend

Cost is reported in tokens, in rupees, and — because the model that ran has no
published price — in a clearly-labelled **projection** onto a model that does.
See 2.2 and 2.3.

### 2.1 The trend

Total tokens per question (input + output + **embedding**), reuse vs baseline:

| Q | Baseline | With memory | Change | Searches | Fetches | Projected ₹ |
|---|---|---|---|---|---|---|
| 1 | 910 | 910 | — | 1→1 | 8→8 | ₹0.0126 |
| 2 | 1014 | 1014 | — | 1→1 | 9→9 | ₹0.0138 |
| 3 | 1427 | 1427 | — | 3→3 | 9→9 | ₹0.0190 |
| 4 | 1200 | 1200 | — | 1→1 | 8→8 | ₹0.0172 |
| 5 | 981 | 828 | −16% | 3→**0** | 7→4 | ₹0.0151 |
| 6 | 1132 | 686 | −39% | 4→**0** | 8→3 | ₹0.0133 |
| 7 | 924 | 534 | −42% | 2→**0** | 8→3 | ₹0.0115 |
| 8 | 1522 | 1290 | −15% | 4→**0** | 8→3 | ₹0.0227 |
| **All 8** | **8987** | **7868** | **−12.5%** | 18→5 (−72%) | 63→48 (−24%) |
| **Q5–8 only** | **4471** | **3352** | **−25.0%** | 13→0 (−100%) | 29→14 (−52%) |

The trend is flat for the first four questions and then steps down, which is
what transferable memory should look like: nothing to transfer until something
has been learned.

These numbers moved twice, and both moves are behaviour changes rather than
measurement changes.

**First move (13.5% → 12.7%, 27.8% → 24.1%): memory started remembering.**
Durable memory used to hold only the previous run's claims — every run
overwrote the last run's rows under the same bare `c1`..`cN` IDs — and now it
holds all of them (`memory_hits` 7 → 61 per suite). The planner reads that
memory and expands entity-prefixed subqueries from it, so both modes plan more
searches than before (Q3: 1 → 3) while reuse still skips every search from Q5
on. Memory that actually remembers costs a little more to consult and saves a
little less in net terms. That is the honest direction for a memory feature to
move the numbers: the old saving was measured against a memory that forgot.

**Second move (12.7% → 12.5%, 24.1% → 25.0%): the prompt stopped growing with
memory.** See §3.

A correction to the baseline itself, which moved these figures again. The
`--no-reuse` run wrote its results to `evaluation.json` — the *reuse* filename —
so `evaluation-no-reuse.*` was only ever produced by copying by hand afterwards,
and the committed copy had gone stale. Every baseline number I quoted before
this was from that stale file (9612 total, 5061 for Q5–8). `run_suite.py` now
renames the baseline output itself, so the two files cannot drift again. The
true baseline is 8987 / 4471, which makes the saving *smaller* than I had been
reporting. (These are the post-fix figures; see §3.1.)

### 2.2 Q8, and the cost of remembering everything

Q8 is the most expensive question in the suite, and until this session it was
the one question where **reuse made things worse**: 1,534 input tokens with
memory against a 1,485-token no-memory baseline. A feature sold as a cost
reduction was, on the single most expensive question, a cost increase.

The cause was that every retrieved memory record was pasted into the prompt
verbatim. Q8 asks about four companies at once, so it retrieved 20–30 records
and paid input tokens for all of them — including records about entities the
question does not ask about. The saving on searches was real and was being
eaten by the prompt.

This is the shape of bug that hides inside a favourable average. The suite-wide
figure was a respectable −12.7% while the most expensive question was
regressing, and no unit test could see it: each component behaved correctly,
and only the end-to-end token count across a *sequence* of questions showed the
interaction. It is the same failure mode as the three bugs in §3, and the same
thing found it — running all eight questions in order and reading the numbers
per question rather than in aggregate.

The fix is in §3. Q8 is now −15% against baseline, and its projected cost fell
from **2.24× Q1 to 1.79× Q1**. It is still the most expensive question, which
is correct: it is a four-entity question and should cost more than a
one-entity question.

### 2.3 Why the measured rupee column says `unpriced`

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

### 2.4 The counterfactual column

Refusing to invent a price is right. But a rupee column reading `unpriced` in
all eight rows answers the brief's "report your cost per question in tokens and
rupees, and show the trend" with silence, and silence is not the same as
honesty. The gap was real: there was no rupee trend at all.

So the report now carries a second column, **Projected ₹**: what these exact
token counts would have cost on `gpt-4o-mini` at its published rate
($0.15/$0.60 per 1M, 94.5 INR/USD).

The distinction is enforced in code, not just in prose. `cost_in_rupees` is
only ever populated from the model that actually ran; `counterfactual_inr` is
arithmetic on real token counts at a real published rate for a model that did
not run. They are separate keys with separate names, and every renderer prints
the reference model's name beside the projection. `DYLA_PRICE_*` deliberately
does *not* feed the projection — letting it would silently reprice the
reference and make the two columns compare a model against itself.

The whole suite projects to **₹0.1252**, and the reference model is the
cheapest widely-used hosted option in the table on purpose: the projection
should read as a floor, not a flattering mid-range guess.

What this column is not: evidence about what a live run would cost. The token
counts come from an extractive model that quotes evidence rather than reasoning
over it. A real model on these questions would emit more output tokens and
probably take more turns. The arithmetic is exact; the input to it is a
harness. Both halves of that need saying together.

---

## 3. The extra credit: halve cost per question via transferable memory

**I did not achieve it as specified, and I am not going to round up to it.**

Target: 50% reduction in cost per question. Measured: **12.5% across all eight
questions, 25.0% across the four that could reuse anything.** Searches fell 72%.

Those figures were 12.7% and 24.1% before this session, measured against a
baseline file that had gone stale (see §2.1). What moved them is
described in "the prompt budget" below, and it is worth reading as a method
rather than a number: the gain came from noticing that the feature was
*spending* on the question where it should have saved most.

### Why it falls short, precisely

Reuse engages when an earlier question caused pages to be *attributed to the
entity a later question asks about*. Four of the eight questions could never
qualify:

- Q1 (GST) shares no entity with anything.
- Q2, Q3, Q4 are the *first* questions about their entities. There is nothing
  to transfer to them by construction.

So the honest denominator is Q5–Q8, where the reduction is 25.0%.

### Why not 50%: the arithmetic, not a vibe

"Memory removes the search step, not the grounding step" is the one-line
version and it is true, but it is not a measurement. Here is the measurement.
Q5–Q8, by token type:

| Token type | Baseline | With memory | Removed | Share of what remains |
|---|---|---|---|---|
| Embedding | 970 | 117 | **−87.9%** | 3.5% |
| Input (prompt) | 3,137 | 2,826 | −9.9% | **84.3%** |
| Output | 364 | 409 | +12.4% | 12.2% |
| **Total** | **4,471** | **3,352** | **−25.0%** | |

Embedding tokens are the thing memory is *designed* to eliminate, and they are
essentially gone — 87.9% removed, down to 3.5% of what is left. That part
worked. The problem is that it was never the big number.

The binding constraint is arithmetic and worth stating precisely. A 50% cut
means getting Q5–Q8 to **2,236** tokens. Input alone is **2,826** — already
63.2% of the baseline on its own. So even if embedding went to *exactly zero*
and output never changed, the target would still be missed. **50% is
unreachable without cutting the evidence block itself**, which is the prompt.
No amount of memory cleverness gets there, because memory's savings live almost
entirely in a category that is now 3.5% of the total.

### The `evidence_limit` sweep, and a conclusion I got wrong

The evidence block is `evidence_limit` items. I swept it, with a clean memory
database and cleared bytecode per run (the first attempt at this table did
neither, and reported figures that did not reproduce):

| `evidence_limit` | Q5–8 tokens | vs baseline | Questions | Claims | Seeded defects | **Recall** |
|---|---|---|---|---|---|---|
| 3 | 2,494 | **−44.2%** | 8/8 | 28/28 | 20/20 | **15/21** |
| 4 | 2,747 | −38.6% | 8/8 | 29/29 | 20/20 | **15/21** |
| 5 | 3,019 | −32.5% | 8/8 | 29/29 | 20/20 | **15/21** |
| 6 | 3,121 | −30.2% | 8/8 | 29/29 | 20/20 | **15/21** |
| **8 (shipped)** | 3,352 | −25.0% | 8/8 | 29/29 | 20/20 | **15/21** |

These percentages are against the corrected baseline (4,471 — see §2.1), and
re-measured after the §3.1 fixes. Against
the stale one I had been using, the cheapest row read **−51.2%**, and the
previous revision of this document was built around that: it announced that the
brief's 50% target was reachable and then explained at length why taking it
would be dishonest, because claims fall from 28 to 24 and the quality gate is
blind to the loss.

**Both halves of that were wrong.** The target was never reached — 44.2% is the
best this sweep offers, and the 50% figure was an artifact of a stale baseline
file. And the dishonesty argument does not hold either.

**That reasoning was wrong, and the recall metric I built to prove it is what
disproved it.** Recall is *flat at 15/21 across every setting from 3 to 8*. The
claims lost at `evidence_limit=3` are duplicates and off-topic extras — not
facts the question asked for. On this corpus the cheap setting is not less
complete. It is merely less repetitive.

I have left `evidence_limit` at 8 anyway, and the reason is now different and
weaker than the one I gave before: the claim-count drop is not evidence of harm,
but a 21-fact key over 14 fixture pages is thin evidence of *no* harm either,
and the extractive model makes context cheap in a way a real model would not.
That is a judgement call about an unmeasured risk, not a finding. Reported as
such.

The honest summary of this sweep is that **it cost me a conclusion**. I asserted
a causal story — "cost fell because the agent answered less thoroughly" — that
sounded careful, matched the numbers I had, and was false. It survived a full
turn and a commit message before the metric caught it.

### The recall metric: what it did catch

Building it was still the right call, because it found something worse than the
thing it was built to check. Scored against a hand-written key of the facts each
question demands (`src/dyla/recall.py`):

| # | Question | Recall | Missing |
|---|---|---|---|
| 1 | GST on restaurants | 1/2 | the 18% rate for hotel restaurants |
| 2 | Zerodha CEO | 2/2 | — |
| 3 | Bengaluru exporters | 3/3 | — |
| 4 | Quick-commerce rounds | 2/2 | — |
| 5 | Zerodha CTO | 2/2 | — |
| 6 | Infosys vs Wipro revenue | 2/2 | — |
| 7 | Zepto valuation trajectory | 1/4 | all three valuations (1.4bn, 3.6bn, 5bn) |
| 8 | Profitability of four companies | **0/4** | all four profitability facts |
| | **Total** | **13/21 (62%)** | |

That was the state when the metric landed. §3.1 fixes three of these; the table
above is the diagnosis, not the current score, which is **15/21**.

**Q8 asks whether four companies are profitable and returns zero claims about
profitability.** It answers with revenue and funding figures instead, and scores
**4/4 supported**. Q7 asks how a valuation changed across rounds and returns no
valuation. The corpus supports every one of these facts — they are sitting in
the fixture pages, unfetched or unselected.

So the suite's headline quality number, *28/28 claims supported*, was measuring
the wrong thing all along. Not by a little: on the hardest question in the suite
it is 100% precision on 0% of what was asked. That is what a purely
precision-shaped scoreboard buys you, and no amount of care in reading it would
have surfaced this — the number has to exist.

Recall is now computed on every run and written to `reports/evaluation.md` and
`reports/evaluation.json`. **It is scored only for the default eight questions**,
because the key is hand-written against them and the fixture corpus; a custom
`--questions-file` reports no recall rather than a fabricated one.

Two limits worth stating. The key encodes *my* judgement of what each question
demands, so a reviewer may reasonably disagree with individual entries; it is
external and legible in `ANSWER_KEY` precisely so that disagreement is possible.
And it does not generalise to live runs, where the set of supportable facts is
not enumerable. The tempting fix — infer expected facts from whatever the agent
retrieved — is circular, and circularity is exactly what let an answer omitting
all four profitability facts score 100%.

The other route to 50% is to have memory serve the *answer* rather than the
*retrieval* — answer from stored claims without re-reading sources. That is a
different and much less safe design, because it means trusting a prior
conclusion rather than the evidence under it. I did not build it, and I would
argue against building it for a system whose entire point is being auditable.
Note that it is also the route the brief explicitly rules out: "caching an
answer you have already seen does not count".

### 3.1 Fixing what recall exposed

The metric named three gaps. Two are now fixed, one is partly fixed, and the
residue turned out to be a *different* defect from the one I assumed.

**Fix 1 - the selector ranked by popularity, not by coverage.** `OfflineModel`
scored each candidate sentence by raw token overlap with the question and took
the top four. For Q8 that is a contest one sentence naming two asked-about
companies always wins: "Infosys reported revenue ... while Wipro reported ..."
scored 2, every profitability sentence scored 1, and the top four were all
revenue. Selection is now greedy on *newly covered* question terms, so a term
already spoken for stops earning credit and the uncovered ones pull their own
sentences in.

**Fix 2 - the question's own vocabulary did not match the evidence.**
`profitable` never matched `profit`, and `zepto's` never matched `zepto`, under
exact token equality. A four-line suffix strip closes that. It is deliberately
not a real stemmer.

**Fix 3 - `on_topic` accepted boilerplate as subject matter.** This was the
serious one, and it lives in the agent rather than the fixture model.
`on_topic` returned `max(word_overlap, entity_overlap)`, and financial
sentences are near-identical once the company name is removed. Infosys's filing
scored **0.88 word overlap against a Zerodha claim with 0.0 entity overlap**,
was accepted as an independent source "on this claim's subject", was found not
to state Zerodha's profit, and that silence was used to **reject a true,
correctly cited claim** for insufficient corroboration. A claim naming entities
now requires sharing one before word overlap counts at all.

Combined effect: **13/21 to 15/21.** Q1 and Q8's Zerodha fact recovered; 8/8
still complete, 20/20 seeded defects still caught, 363 tests pass.

**A false positive in my own metric.** Q1's miss was partly the metric's fault:
`must_include=("hotel",)` did not match a claim saying "restaurants located
within *hotels*". The key now matches on stems. I had reported Q1 as a genuine
1/2 gap in the previous revision; one half of it was never real. A recall number
that cries wolf gets switched off, taking its true findings with it, so this
matters more than the single point it moved.

### 3.2 What is still broken, and two wrong explanations for it

**Q7 is 1/4 and Q8 is 1/4.** The previous revision of this section gave two
causes. I then measured both, and **both were wrong**. Recording that, because
the wrong versions were stated with the same confidence as the right one.

**Wrong explanation 1: "four profitability facts do not fit under
`max_claims=4`."** Plausible, and false. Sweeping the cap:

| `max_claims` | Tokens | Claims | Supported | Recall |
|---|---|---|---|---|
| **4 (shipped)** | 7,868 | 29 | 29 | **15/21** |
| 5 | 8,115 | 34 | 34 | **15/21** |
| 6 | 8,285 | 40 | 40 | **15/21** |
| 8 | 8,586 | 49 | 49 | **15/21** |

Recall is flat while claim count grows to 49 and cost rises 9%. The extra slots
fill with *more Infosys revenue*, not the missing facts. This is the second time
on this project a claim-count intuition has failed the same way, and the second
time the recall metric caught it.

**Wrong explanation 2: "co-reference is the blocker."** The right facts are
phrased "**The company** reported a net profit of 26,713 crore rupees" — the
sentence answering the question never names Infosys. That is a real defect
(§4.6 lists it), so I built a narrow resolver: rewrite a leading generic subject
to the document's subject, only when the first sentence or title supplies
exactly one candidate.

It resolved correctly and **made things worse**: 8/8 became 7/8, with
"Zerodha is headquartered in Bengaluru" marked *unsupported*. The reason is the
point. **The auditor re-fetches the cited page and checks the claim against
it.** A rewritten sentence is no longer literally in the source, so a true claim
becomes unverifiable — precisely the property that makes this system auditable
turning against a well-meant fix. Restricting the resolver to *scoring* while
citing the original wording restored 8/8 and moved recall **not at all** (15/21
either way). Reverted: it was complexity with no measured benefit.

The real remaining causes, now actually established:

1. **Q7 — corroboration rejects single-sourced figures.** "The round valued
   Zepto at 5 billion dollars" appears on one fixture page. The cross-check
   finds no second source and rejects it. Working as designed; loosening it
   trades away what catches fabricated figures.
2. **Q7 — the two earlier valuations are in a sentence the selector never
   reaches**, because "Zepto had previously been valued at 1.4 billion dollars
   in 2023 and at 3.6 billion in 2024" shares almost no vocabulary with the
   question beyond the entity.
3. **Q8 — the profitability sentences are unattributed.** Fixable only by
   rewriting evidence, which costs verifiability (above), or by a synthesis
   model that can paraphrase-with-attribution. The extractive fixture model
   cannot, and that is a limit of the harness rather than of the design.

All three are stated rather than fixed, and the cheap fixes for each damage
something the project claims.

### 3.3 Memory reuse costs one fact, and only recall could see it

The sharpest result of this whole exercise. With the fixes in place:

| | Total tokens | Q5-8 tokens | Recall |
|---|---|---|---|
| Baseline (`--no-reuse`) | 8,987 | 4,471 | **16/21** |
| Memory reuse (shipped) | 7,868 | 3,352 | **15/21** |

**The saving is not free.** Reuse judged Q8's four entities already covered and
skipped all four searches; those searches are what would have retrieved
`zepto-fy25-financials`, so the Zepto loss fact is reachable in the baseline and
unreachable with memory on. Reuse serves stale-but-relevant evidence and never
learns what it did not fetch.

For most of this project's life the honest summary of memory reuse was "-13%
tokens, all metrics unchanged". The true summary is **"-12.5% tokens, and it
costs one fact out of twenty-one."** That is a defensible trade, but it is a
trade, and every number this repo reported before today was structurally
incapable of showing it.

### The prompt budget: 24.1% → 25.0%

The three bugs below explain how the saving got off the floor. This one
explains why it was capped, and it is the most recent thing I found.

Every memory record the store returned was pasted into the prompt as its own
`Memory: ...` line. That is fine while memory is small and quietly
self-defeating once it is not. Memory grows monotonically across runs, so the
prompt grew with it — and the questions with the most memory to draw on are
exactly the multi-entity ones that were already the most expensive. On Q8 it
crossed over: 30 records, 1,534 input tokens, against a 1,485-token no-memory
baseline (§2.2).

Two rules, both cheap, in `AnalystAgent._memory_context`:

* **Relevance.** Keep only records sharing a content word with the question. A
  stored claim about Zepto's valuation cannot help answer a question about
  Infosys's revenue, and paying input tokens to include it is pure waste.
* **A budget.** Keep at most six records, ranked by overlap. This is what stops
  prompt size tracking memory size.

Records still reach corroboration and the audit-feedback filter — this trims
only what is *quoted to the model*. Dropped records are counted into a
`memory_context_trimmed` trace event, so the saving reads as a decision with a
number attached rather than a figure that improved for unstated reasons.

Result: Q5–8 from −24.1% to −25.0%, Q8 from +3% to −12%, with 8/8 complete,
every asserted claim supported and 20/20 seeded defects caught — unchanged.

**And the part I want to be explicit about.** I swept the limit over 3, 4, 6, 8
and 12. Accuracy was *identical* at every setting; only cost moved (−36.9% at a
limit of 3, −31.1% at 12). The cheapest measured value is 3. **I kept 6.**

Tuning to 3 would be overfitting to a fixture corpus that cannot tell these
settings apart. The offline model is extractive: it quotes evidence and barely
uses memory as context, so this sweep does not measure what a real model would
lose when starved of it. A flat accuracy curve across a 4× range of context
budgets is not evidence that context is free — it is evidence that *this
harness cannot see the cost of removing it*. So the extra ~3 points are left
on the table and named here rather than banked. Had accuracy varied, the
cheapest non-degrading value would have been the honest pick.

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

**A second Qdrant bug, found by asking whether embedding-model changes are
safe.** They were not. `ensure_collection` sized a *new* collection from
`QDRANT_VECTOR_DIMENSIONS`, but on the path where the collection already exists
it never compared the stored size against the configured one. Switching
embedding models against a live Qdrant Cloud collection was therefore accepted
silently at startup and failed later, at write time, with "vector dimension
does not match index configuration" — a message that reads like a bug in this
code rather than a configuration mismatch. This is not hypothetical for anyone
running the shipped defaults: `.env.example` pins 1536, and the one real live
run of this project used `nemotron-3-embed-1b`, which is 2048.

The startup check now names both numbers and points at
`DYLA_EMBEDDING_MODEL`. But the dimension check alone is a half-fix, and the
half it misses is the dangerous one: **two different models can emit vectors of
the same width into unrelated spaces.** Cosine similarity across them returns a
perfectly plausible number that means nothing, memory reuse then serves
confidently-scored nonsense, and *nothing downstream can detect it* — a float
comes back and it looks like a distance. Note that
`CompatibleEmbeddingProvider` already namespaces its own embedding *cache* on
endpoint plus model for exactly this reason; the vector store had no
equivalent, so the same swap that correctly invalidated the cache silently
poisoned the index. The fix stamps that same fingerprint into the collection on
first write and refuses to start on a mismatch. Collections predating the stamp
carry none and are left alone, because refusing to open every pre-existing
collection is a worse failure than the one being prevented.

**Neither fix has been exercised against real Qdrant Cloud**, and the two
halves deserve different levels of confidence. The dimension check is a
comparison of two integers against a value the client reports; a fake client
models that faithfully and I would be surprised if it behaved differently live.
The sentinel point is a different matter, because it is the one part that
*writes* something new into a real collection.

Taking that caveat seriously turned up two things worth fixing rather than
restating:

- **It stored a zero vector.** Collections are created with `Distance.COSINE`,
  whose denominator is `||a|| * ||b||`. A zero vector makes that zero, so cosine
  against it is undefined, and an engine is entitled to reject the insert rather
  than silently special-case it. Now a unit vector: still meaningless as
  content, but well-formed for the metric the collection actually uses.
- **The filter keeping it out of results was untested.** The sentinel is a real
  point and a query can return it like any other; letting it through would
  produce a junk citation or crash `_to_evidence`. The filter was written but no
  test exercised `hybrid_search` at all, so it was one careless edit from
  silently regressing. Now covered.

What remains genuinely unknown is behaviour I cannot simulate: whether a real
Qdrant Cloud instance accepts the reserved point exactly as this code writes it,
and whether one extra point per collection interacts with anything at scale. One
live run settles it. Until then the honest status is "designed carefully, tested
against a fake, unproven on the wire".

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
  entity. The disagreement resolver (§4.10) hits the same limit from the other
  side: a sentence naming two companies satisfies the subject gate for both, so
  a figure belonging to one can be paired with a claim about the other.
- **Authority tiers are substring matches on URLs** (§4.10). A URL that merely
  contains a marker word is misgraded, and the tier table is hand-built and
  specific to Indian filings and press. It encodes my judgement about which
  sources outrank which; that judgement is visible in
  `resolution.AUTHORITY_TIERS` and is meant to be argued with, but it is not
  derived from anything.
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

### 4.10 Sources that disagree: resolved on provenance, not dropped (P3-2)

This was previously **deferred**, and deferring it was hiding a defect rather
than scoping one out.

**What the agent used to do.** The cross-check had two outcomes: a second source
restated the figure (accept), or it did not (reject). A source that addressed
the claim and stated a *different* number fell into the second bucket. So the
agent's response to genuine disagreement was to drop the claim and report that
"independent sources … none states the claim's figure".

That is worse than the "reports both figures and shrugs" failure the brief
names. It does not report both — it silently discards the better-sourced figure
because a worse-sourced one exists. A regulatory filing loses to a blog post
that contradicts it. Phrased as caution, it is a bug with good manners.

**The policy: authority first, recency within a tier.** In
`src/dyla/resolution.py`:

1. **Authority wins outright.** Sources grade into four tiers — primary
   filing/regulator, exchange disclosure, established press, aggregator or
   summary. A higher tier beats a lower one *regardless of date*, because a
   preliminary summary does not overturn an audited annual report by being
   published later.
2. **Recency breaks ties within a tier.** Same authority usually means one
   source is a restatement of the other, so the later one wins. Undated loses
   to dated: an undated page cannot be shown to be the newer one, and treating
   it as newest would let any unstamped page overturn a dated peer.
3. **Neither: say so.** Same tier, same date is a real standoff. The resolver
   returns `unresolved` and the figure is not asserted. This case is
   deliberately reachable and directly tested — a resolver that always produces
   a winner is exactly as uninformative as an auditor that approves everything.

It ranks *provenance*, not plausibility. It never reads the figures to decide
which looks more reasonable and never averages them; both would be inventing a
fact. Every resolution emits a `disagreement_resolved` trace event naming the
winner, the rule that fired, both tiers, both dates and both values, so the
choice is arguable rather than a black box.

**On the corpus.** The planted conflict is two sources on Infosys FY2025
revenue: the annual report (₹1,62,990 crore, tier 4, 2025-04-17) and a
"preliminary summary" note (₹1,53,670 crore, tier 1, 2024-12-30). The agent now
keeps the filing's figure and records why:

> Authority: `…/exchange/infosys-annual-report-fy25` is a primary filing or
> regulator (tier 4) while `…/quick-summaries/infosys-revenue-note` is an
> aggregator, summary or unclassified (tier 1), so the higher-authority figure
> is preferred regardless of publication date.

**Two things I got wrong on the way, both caught by reading the trace.**

*First: the detector was far too loose.* The initial version gated only on word
overlap and reported **six** disagreements across the suite — of which exactly
**one** was real. The other five paired a company's profit against a different
company's revenue: both large rupee figures, neither in conflict with the
other. Three gates now apply, and each one exists because of a specific false
positive: the rival sentence must restate a third of the claim, must name every
subject the claim names, and must discuss the same *measured quantity*
(revenue ≠ profit ≠ valuation ≠ raise amount).

*Second, and worse: a correct claim got rejected.* Adding the subject gate made
the true Infosys claim fail. The subject of "Infosys Limited reported…"
extracted as `{"limited"}` — the existing `named_entities` drops
sentence-initial capitals (right for misattribution checking, where
"Restaurant services…" must not read as an entity) leaving only the corporate
suffix. And "Wipro Limited" satisfies `{"limited"}`. So a fix aimed at removing
false conflicts introduced a false rejection of the one true positive.
`claim_subjects` now handles this case separately and strips corporate
suffixes. Both behaviours are pinned in `tests/unit/test_rival_figure.py`,
where every negative case is a false positive the first implementation actually
produced.

**A structural fix this exposed.** The cross-check used to `return` at the first
corroborating source. That means a source flatly contradicting the claim went
unexamined purely because an agreeing one ranked above it — the agent could not
resolve a disagreement it never looked at. All candidates are now scanned,
disagreements are adjudicated *before* corroboration is credited, and "one
source agreed" is no longer treated as an answer to "another disagreed". Where
provenance genuinely ties, an independent third source stating the figure
carries the claim 2–1, reported as weight of agreement rather than as clean
confirmation.

**Limits.** Tiering is substring matching on URLs, so a URL merely containing a
marker word is misgraded; the tier table is hand-built and Indian-market
specific. A claim naming no subject at all ("The company reported…") is never
adjudicated — the co-reference limit in §4.6, failing safe, since a
disagreement that cannot be attributed cannot be resolved. And on this corpus
the policy fires exactly once, so it is demonstrated, not validated at scale.

---

### 4.11 The auditor -> analyst feedback loop, and why it reads zero

The brief calls this "the closest thing on this page to what we actually
build", so it deserves a number rather than a description.

The loop is real: rejected claims are read back out of memory by verdict
status, named in the next run's system prompt, and blocked if the model
restates one anyway (`claims_blocked_by_audit_feedback`).

**It has never fired in the evaluation suite, and I nearly reported that
number without checking why.** The metric appears in all eight question
traces, which is easy to misread as eight blocks. It is the key appearing in
the `completed` payload with a value of **0**. Summed across every run in both
modes: zero.

That is not a broken feature, it is an unexercised one, and the distinction is
the whole point. The fixture corpus is clean and the extractive model quotes
verbatim, so all 29 claims are supported, nothing is ever *stored* with a
rejected verdict, and the list the loop reads is always empty. The seeded-defect
audit cannot feed it either — it runs `persist=False` on purpose, because
planting lies in `dyla.db` for the next run would be a worse bug than the one
being tested.

Publishing `claims_blocked_by_audit_feedback: 0` in `reports/evaluation.md`
would therefore be a true number that misleads: it reads as a dead feature. So
the mechanism is measured where it can actually fire —
`scripts/experiment_audit_feedback.py` records a rejected verdict, asks the
same question again, and compares against a control:

| | Control | After a recorded rejection |
|---|---|---|
| Warning present in prompt | no | **yes** |
| Claim asserted in the answer | **yes** | no |
| Claims blocked | 0 | **2** |

Both halves are checked deliberately. A harness that asserted only the first
row would pass while the analyst restated the claim anyway — the *block* is the
feature, the warning is just the mechanism. Pinned by a test so it cannot rot
into a script nobody runs.

The honest limit: this proves the wiring end to end against a planted verdict.
It does not prove the loop improves answers on a corpus where the auditor
rejects claims organically, because this corpus never does.

### 4.12 What the first live suite run exposed

The owner ran the suite live (NVIDIA Nemotron + You.com + Qdrant Cloud) and it
scored **4/8 questions and 15/20 on the seeded-defect audit**, against 8/8 and
20/20 offline. I have no egress, so I cannot reproduce that run; what follows
is one defect I could isolate from the reported symptom and reproduce locally,
plus an honest note on what I could not.

**The parser threw away good answers.** `Claim.citations` is required with no
default, so a response where *one* claim omits the field fails
`model_validate` for the whole object, the adapter raises, and the question
fails outright. Reproduced exactly:

```
claims.1.citations  Field required
```

Three perfectly cited claims discarded because of a fourth. **That is a parser
failure being reported as a research failure**, and on the strictest reading it
is the worst kind of bug this project can have: the system said "I could not
answer" when it had the answer.

The fix salvages the well-formed claims — and the *interesting* part is what it
deliberately does not do. The obvious repair is to give `citations` a default of
`[]` in the schema. That parses identically and is much worse: an uncited
assertion becomes a **valid** claim object, and manufacturing provenance is the
one thing this system exists to prevent. Instead the salvage recovers the claim
*with an empty citation list*, which routes it into the analyst's existing
`no_citations` gate, rejects it, and traces the rejection. Verified end to end:
the good claim survives, the malformed one is rejected with
`"Claim c2 was rejected because it had no citations."`

Two constraints fell out of building it, both found by the existing suite
rather than by me:

- **Salvage must run last.** Attempting it inline with the validation loop
  regressed the truncation repair: for a response cut off mid-claim the first
  candidate is the raw truncated parse and a later one is the cleanly
  drop-repaired version, so salvaging the first kept a half-written claim in
  preference to the repair that correctly discards it. Two existing tests
  caught this immediately. Salvage now runs only after every candidate has
  failed outright.
- **An unsalvageable response still raises.** Returning an empty answer would
  read as "the model found nothing" rather than "the response could not be
  parsed". Different failures, and conflating them is how a parsing bug hides.

**What I have not fixed, and will not claim to have fixed.** The live report
lists two other causes: evidence selection retrieving irrelevant sources, and
the seeded audit dropping to 15/20. Both are plausible and neither is
diagnosable from here — the seeded audit uses a real model as comparator live,
where offline it uses `_TextComparator`, so 15/20 may be a comparator-quality
result rather than a defect in the audit logic. Guessing at a fix for a failure
I cannot reproduce would be worse than leaving it named. **The live suite
numbers (4/8, 15/20) are not superseded by this fix**; they were measured
before it and have not been re-measured since.

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
| Counterfactual rupee column (§2.4) | The rupee half of the brief's cost question had no answer at all — eight rows of `unpriced`. Real token counts are now projected onto `gpt-4o-mini` list rates in a separately-named column, with the measured column left empty rather than backfilled |
| Memory context budgeted and relevance-filtered (§3) | Every retrieved record used to be pasted into the prompt, so prompt size grew with memory. On Q8 that made reuse a net *cost*: 1,534 input tokens vs a 1,485 baseline. Now ≤6 relevant records: Q5–8 savings 24.1% → **25.0%**, Q8 +3% → −12%, accuracy unchanged at 8/8, 28/28, 20/20 |
| Source disagreement resolved instead of dropped (P3-2, §4.10) | A source stating a *different* figure and a source saying nothing used to be handled identically — both "no corroboration", claim dropped. A tier-1 summary could veto a tier-4 filing. Now adjudicated on authority-then-recency with a traced justification, and the standoff case stays reachable |
| Wall-clock trend added to `reports/evaluation.md` | The brief asks for an agent that gets "cheaper **and faster**". `duration_ms` was already in the per-question table, but only the cost trend was summarised, so half the sentence had no answer. The trend is now rendered and explicitly labelled as fixture-replay milliseconds, not live latency |
| Auditor→analyst feedback loop measured (§4.11) | The loop was implemented and unit-tested but had **never fired in the suite** — the metric reads 0 in all eight traces because the clean corpus never stores a rejected verdict. Rather than publish a 0 that looks like a dead feature, `scripts/experiment_audit_feedback.py` drives it where it can fire: 2 restatements blocked against a control of 0 |
| Answer-completeness (recall) metric added, and three defects it found fixed (§3, §3.1) | Every prior quality number graded the claims that *were* made. The new key scores what was omitted: it opened at **13/21**, with **Q8 at 0/4** — answering a profitability question with revenue figures while scoring 4/4 supported. Fixing the selector's coverage blindness, its exact-token matching, and an `on_topic` bug that let Infosys boilerplate veto a Zerodha claim took it to **15/21**. It also showed memory reuse costs one fact (§3.3), and retracted two of my own conclusions |
| Cross-check scans all candidates before deciding (§4.10) | It used to `return` at the first corroborating source, so a contradicting source ranked below it was never read. A disagreement the agent never saw cannot be resolved |

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
   every artifact header. The blocker is **network egress, not just a missing
   key** — the sandbox reaches the package index and nothing else, so even a
   valid You.com key would authenticate against an unreachable host (§0 has the
   measurements). I stated the key-only version for several sessions, which
   understated the problem in the direction that flattered the work.
2. **No session logs.** The brief weighs three things: *"The session logs tell
   us how you work. The write-up tells us how you think. The code tells us what
   you can build. We weigh all three."* One of those three axes is not
   represented in this repository. What is committed under that name is not it:
   `runs/*.jsonl` are **agent** traces — the program's own tool calls — and
   `.superpowers/sdd/` holds 11 implementation reports (`task-1`…`task-8` plus
   three investigations) recording files changed and TDD history. Neither is a
   record of the human↔AI working session, and no transcript is committed
   anywhere. `grep -ril "overruled\|I disagreed\|the tool suggested"
   .superpowers/ docs/superpowers/` returns nothing — this file is deliberately
   outside that scope, because the sentence you are reading quotes all three
   phrases and would otherwise be its own only hit.

   The distinction is easy to blur, and blurring it flatters this
   submission — a `claim_rejected` event shows the *analyst* overruling its
   *model*, which is a runtime behaviour the brief asks for in Part A, not
   evidence about how the candidate worked with a tool. What the brief wants
   on this axis is the other thing: where the obvious approach was tried,
   measured and rejected, and where the tool was overruled and was right to
   be. The closest in-repo substitute is this document —
   §4.5's three rejections with their measurements, and `FIX_BACKLOG.md` Part 1,
   which records four features that had been committed and described as working
   and were not — but those are the *decisions*, not the *session*, so a reader
   has to take the write-up's word for how they were reached. Exporting and
   committing the transcripts would close this; it has not been done.

3. **Auditor scope reasoning is heuristic.** The §4.2 false positive that
   failed Q1 is fixed (scope gate + per-word negation parity, seeded audit
   20/20), but scope is measured by word overlap, not semantics — §4.6 lists
   what that still cannot see.
4. **Removing Azure is a breaking change** for anyone who was using those
   adapters. Nobody here was, and the alternative was carrying ~830 lines of
   knowingly-broken, untestable, credential-gated code — but it is a break and
   it belongs on this list rather than in a footnote.
5. **Extra credit not achieved** — 25.0%, not 50% (§3). The gap is now
   arithmetic rather than mystery: input tokens are 84.6% of what remains and
   2,826 of them alone exceed the 2,236 a 50% cut allows, so the target cannot
   be reached without cutting the evidence block. The cheapest sweep setting
   (`evidence_limit=3`) reaches **−44.2%**, still short. I previously reported
   that same row as −51.2% and framed the shortfall as a deliberate refusal;
   both statements were wrong — the 50% figure came from a stale baseline file
   (§2.1), and the completeness loss I cited as the reason for refusing does
   not exist (recall is flat at 15/21 across the sweep). What actually keeps
   `evidence_limit` at 8 is an unmeasured risk, argued in §3, not a measured
   harm. Two smaller amounts were also measured and left: ~3 points from the
   memory-budget sweep.
6. **Offline retrieval scores carry no quality signal — and the memory-reuse
   gate sits on top of them.** The default `LocalEmbeddingProvider` maps text to
   a two-dimensional hash (`[sum(bytes) mod 997, length]`), so offline cosine
   similarity between two chunks is structurally meaningless: it measures byte
   sums, not semantic proximity. The offline suite is a deterministic replay,
   so this is fine for what it claims — but two things downstream of the scores
   deserve the sharper statement. First, "hybrid search" was, until this
   session, dense-only despite its name; a token-overlap lexical channel now
   exists in `LocalVectorStore` (blended at 0.3, dense dominant) precisely so
   retrieval is not solely a function of a noise embedding — and its rescue
   behaviour is pinned by a test that flips a ranking dense-only scoring gets
   wrong. Second, memory-reuse coverage decisions are gated on
   `reuse_min_score`, which offline compares against noise; the gate is saved
   by its other condition — two *distinct sources* — but a reader should know
   that offline, the score half of that comparison filters nothing. A live run
   with a real embedding model is the only setting in which retrieval-quality
   numbers from this harness would mean anything (weakness 1's caveat, one level
   deeper).
7. **Answer completeness is 71%, and that is now measured rather than
   assumed.** `src/dyla/recall.py` scores each answer against a hand-written
   key of the facts its question demands. It started at 13/21; three defects it
   exposed are fixed (§3.1) and it now reads **15/21, with Q7 and Q8 still at
   1/4 each**. The residue is diagnosed (§3.2): single-sourced figures are
   rejected by the corroboration rule, and Q8's profitability sentences are
   unattributed ("The company reported ..."). I published two *other*
   explanations for this gap before measuring them, and both were wrong — the
   `max_claims` cap makes no difference (recall is flat while claim count grows
   to 49), and resolving the co-reference actively broke the suite by making a
   true claim unverifiable. Both are written up as failed attempts.
8. **The recall key is mine, and it does not generalise.** 21 facts,
   hand-written against eight questions and 14 fixture pages. A reviewer may
   disagree with individual entries — it lives in `ANSWER_KEY` so that
   disagreement is cheap. It cannot score a live run, where supportable facts
   are not enumerable, and the obvious workaround (derive expectations from
   what was retrieved) is circular in exactly the way that hid Q8.
9. **The suite seeds four entities before running.** `scripts/run_suite.py::seed_entities`
   pre-registers Zerodha, Infosys, Wipro and Zepto, because entity resolution is
   deterministic and does not invent entities from free text. Without it the
   resolver returns "unknown" and reuse can never engage. A real deployment
   accumulates these over time; doing it up front keeps the harness honest about
   what it measures rather than silently measuring nothing. But it *is* a
   thumb on the scale and it belongs in this list.
10. **The cross-check's notion of corroboration is lexical** (§4.7). The old
   high-confidence bypass is closed — the gate is now model-independent — but
   "independently states the figure" is decided by numeric-fact and overlap
   matching, and the offline corpus is single-source-per-fact, so the cross-check
   rejects genuine single-source claims it cannot confirm. Live search is the
   real test and remains unavailable.
11. **`search_memory` full-scans in Python.** Fine at 14 pages, not at 14,000.
   The scan is now documented as deliberate (the dead `memory_records_text`
   index was removed rather than kept as decoration); the replacement is FTS5
   or the embedding store when the corpus outgrows it.
12. **The disagreement resolver fires exactly once on this corpus** (§4.10). One
   planted conflict, correctly resolved on authority. That demonstrates the
   mechanism; it does not validate the tier table, and a single positive is not
   a measurement. The two false-positive classes I found and fixed on the way
   are pinned as tests, but I found them by reading a trace, not by having a
   labelled disagreement set to score against. Its authority ordering is my
   judgement written down (`resolution.AUTHORITY_TIERS`) — legible and
   arguable, but not derived from anything.
13. **The counterfactual column prices a harness, not a run** (§2.4). The
   arithmetic is exact and the rates are real, but the token counts come from
   an extractive model that quotes rather than reasons. A live model would emit
   more output tokens and likely take more turns, so ₹0.1252 is a floor on a
   floor. It answers "show the trend in rupees"; it does not answer "what does
   this agent cost".
14. **Memory that remembers makes the planner thirstier.** Fixing the claim-ID
   overwrite (memory now holds all eight answers, not one) raised retrieval
   searches in *both* modes — Q3 plans 3 subqueries where it planned 1 —
   because the planner expands entity-prefixed subqueries from everything it
   remembers. Reuse still skips every Q5–Q8 search, so the net effect is a
   smaller saving than the pre-fix illusion suggested, but the coupling is
   one-directional:
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
