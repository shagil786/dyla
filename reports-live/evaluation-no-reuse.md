# Evaluation

- Total: 8
- Passed: 4
- Failed: 4

## Questions

- **complete** — What is the current goods and services tax (GST) rate applied to restaurant services in India?
- **complete** — Who is the current chief executive officer of Zerodha, and in which year did they take the role?
- **incomplete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each.
- **unaudited** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors?
- **complete** — Who is the chief technology officer of Zerodha, and what is their academic background?
- **complete** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure.
- **incomplete** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round?
- **incomplete** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each.

## Verdict detail

### 1. What is the current goods and services tax (GST) rate applied to restaurant services in India? — complete
Run: `a5e65bc090a34d1aaac2921613d111ab`

| Claim | Verdict | Cited sources |
|---|---|---|
| claim_1 | supported | https://busy.in/gst-rates/restaurant/ |

### 2. Who is the current chief executive officer of Zerodha, and in which year did they take the role? — complete
Run: `c848a204b9e142809dffdf843ed71db1`

| Claim | Verdict | Cited sources |
|---|---|---|
| 0 | supported | https://zerodha.com/about/ |

### 3. List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. — incomplete
Run: `726469b656424ffdbdb7318685fa7bf0`

| Claim | Verdict | Cited sources |
|---|---|---|
| claim_1 | supported | https://stpi.in/en/news/software-export-boom |
| claim_2 | supported | https://stpi.in/en/news/software-export-boom |
| claim_3 | unsupported | https://stpi.in/en/news/software-export-boom |

### 4. Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? — unaudited
Run: `7b8ada2aee234841ac5f6b7a69271581`
_No claims were audited for this question._
### 5. Who is the chief technology officer of Zerodha, and what is their academic background? — complete
Run: `4a02894c6b294156951a9a589251e205`

| Claim | Verdict | Cited sources |
|---|---|---|
| 1 | supported | https://en.wikipedia.org/wiki/Zerodha |
| 2 | supported | https://en.wikipedia.org/wiki/Zerodha |
| 3 | supported | https://me.sh/profile/kailash-nadh |
| 4 | supported | https://www.instagram.com/p/DC_XjcfTRCW/ |

### 6. Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. — complete
Run: `36d7b9e980244556bd498c53775f905d`

| Claim | Verdict | Cited sources |
|---|---|---|
| claim_1 | supported | https://ticker.finology.in/discover/market-update/wipro-vs-Infosys-comparison |

### 7. How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? — incomplete
Run: `ee2fb3e3ac3246218009a4357d13165d`

| Claim | Verdict | Cited sources |
|---|---|---|
| 1 | supported | https://tracxn.com/d/companies/zepto/__vOTzafGt-8S4kwYniiZ_yRogd6c_Jsw_vRD0gckHtfE/funding-and-investors; https://www.clay.com/dossier/zepto-funding |
| 2 | unsupported | https://www.clay.com/dossier/zepto-funding |

### 8. State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. — incomplete
Run: `a13ad13f6daf47e5add34903e6a9f953`

| Claim | Verdict | Cited sources |
|---|---|---|
| Zerodha | unsupported | https://www.ndtv.com/business-news/zepto-ipo-revenue-losses-quick-commerce-share-sale-sebi-investors-11610419 |
| Infosys | unsupported | https://www.ndtv.com/business-news/zepto-ipo-revenue-losses-quick-commerce-share-sale-sebi-investors-11610419 |
| Wipro | unsupported | https://www.ndtv.com/business-news/zepto-ipo-revenue-losses-quick-commerce-share-sale-sebi-investors-11610419 |
| Zepto | supported | https://www.ndtv.com/business-news/zepto-ipo-revenue-losses-quick-commerce-share-sale-sebi-investors-11610419 |

## Cost per question

| # | Question | Status | Input tok | Output tok | Embed tok | Searches | Fetches | Skipped | Duration (ms) | Cost (rupees) | Projected ₹ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | What is the current goods and services tax (GST) rate applied to restaurant services in India? | complete | 2381 | 351 | 18079 | 1 | 6 | 0 | 24386 | unpriced | 0.0537 |
| 2 | Who is the current chief executive officer of Zerodha, and in which year did they take the role? | complete | 2324 | 258 | 33062 | 2 | 6 | 0 | 27198 | unpriced | 0.0476 |
| 3 | List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. | incomplete | 4451 | 751 | 75559 | 2 | 9 | 0 | 64203 | unpriced | 0.1057 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? | unaudited | 2392 | 201 | 11745 | 1 | 5 | 0 | 14976 | unpriced | 0.0453 |
| 5 | Who is the chief technology officer of Zerodha, and what is their academic background? | complete | 2703 | 1031 | 33543 | 2 | 11 | 0 | 31589 | unpriced | 0.0968 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. | complete | 3632 | 305 | 98885 | 2 | 11 | 0 | 43222 | unpriced | 0.0688 |
| 7 | How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? | incomplete | 2910 | 1075 | 32800 | 1 | 8 | 0 | 57688 | unpriced | 0.1022 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. | incomplete | 3149 | 1200 | 166930 | 4 | 17 | 0 | 81815 | unpriced | 0.1127 |
| | **Total** | | 23942 | 5172 | 470603 | 15 | 73 | 0 | 345077 | unpriced | 0.6326 |

**Cost (rupees) is unavailable.** No price known for model 'nvidia/nemotron-3.5-lightning-30b-a3b'. Set DYLA_PRICE_INPUT_PER_MTOK_USD and DYLA_PRICE_OUTPUT_PER_MTOK_USD (USD per 1M tokens), or add the model to dyla.pricing.KNOWN_MODEL_PRICING.

**Projected ₹** is not a measurement. It is what these exact token counts would have cost on `gpt-4o-mini` at $0.15/1M input and $0.6/1M output, converted at 94.5 INR/USD. The tokens are real; the model that would have charged for them did not run. Override the reference with `DYLA_COUNTERFACTUAL_MODEL`.

## Cost trend

- Total tokens: 29114 (input 23942, output 5172)
- Total estimated_cost (adapter units): 0.0
- Total duration: 345077 ms
- Memory hits by question: [0, 1, 1, 0, 2, 5, 0, 18] (first-question baseline: 0; later questions total: 27)

**Wall-clock trend** (analyst plus auditor, per question):

- Per question: 24386 ms, 27198 ms, 64203 ms, 14976 ms, 31589 ms, 43222 ms, 57688 ms, 81815 ms
- First to last: 24386 ms -> 81815 ms (+235.5%)
- Questions 5-8 (the memory-reusing half): 214314 ms total, 53578.5 ms mean
- These are fixture replays measured in milliseconds, not live latency. The ordering is meaningful; the magnitudes are not evidence about a networked run.

**Projected rupee trend on `gpt-4o-mini`** (a projection over real token counts, not a measured charge):

- Per question: ₹0.0537, ₹0.0476, ₹0.1057, ₹0.0453, ₹0.0968, ₹0.0688, ₹0.1022, ₹0.1127
- Q1 ₹0.0537 → Q8 ₹0.1127 (+110.0%)
- Most expensive: Q8 at ₹0.1127 (2.10× Q1)
- Suite total: ₹0.6326

## Answer completeness (recall)

Every other quality number here grades the claims that *were* made. This
one grades what was left out: for each question, the facts the fixture
corpus supports and the question asks for, scored against what the answer
actually asserted. See `src/dyla/recall.py` for the key and its limits.

| # | Question | Covered | Expected | Recall | Missing |
|---|---|---|---|---|---|
| 1 | What is the current goods and services tax (GST) rate applied to restaurant services in India? | 1 | 2 | 50% | restaurants in high-tariff hotels are taxed at 18% |
| 2 | Who is the current chief executive officer of Zerodha, and in which year did they take the role? | 1 | 2 | 50% | Nithin Kamath is the CEO of Zerodha |
| 3 | List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. | 2 | 3 | 67% | Mphasis is named |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? | 0 | 2 | 0% | Zepto raised 350 million led by General Catalyst; Swiggy Instamart's parent raised 200 million led by Prosus |
| 5 | Who is the chief technology officer of Zerodha, and what is their academic background? | 1 | 2 | 50% | he holds a PhD in computer science / AI |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. | 0 | 2 | 0% | Infosys revenue of 1,62,990 crore; Wipro revenue of 89,088 crore |
| 7 | How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? | 0 | 4 | 0% | valued at 1.4 billion in 2023; valued at 3.6 billion in 2024; valued at 5 billion in the latest round; the latest round was led by General Catalyst |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. | 3 | 4 | 75% | Zepto is not profitable / made a loss |
| | **Total** | **8** | **21** | **38%** | |

## Run history

Most recent 2 full-suite runs recorded.

**Verdict trend, oldest run on the left:**

Cell = supported/total claims audited; ✓ = passed, ✗ = not passed; — = question absent from that run.

| # | Question | Pass rate | | 09-06 07:11 | 09-06 07:29 |
|---|---|---|---|---|
| 1 | What is the current goods and services tax (GST) rate applied to restaurant services in India? | 2/2 | ✓ 2/2 | ✓ 1/1 |
| 2 | Who is the current chief executive officer of Zerodha, and in which year did they take the role? | 2/2 | ✓ 1/1 | ✓ 1/1 |
| 3 | List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. | 1/2 | ✓ 3/3 | ✗ 2/3 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? | 0/2 | unaudited | unaudited |
| 5 | Who is the chief technology officer of Zerodha, and what is their academic background? | 2/2 | ✓ 2/2 | ✓ 4/4 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. | 2/2 | ✓ 1/1 | ✓ 1/1 |
| 7 | How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? | 0/2 | ✗ 0/1 | ✗ 1/2 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. | 0/2 | ✗ 1/4 | ✗ 1/4 |

**Run details (newest first):**

### 2026-09-06T07:29:21.386546+00:00 — 4/8 passed
- **complete** — What is the current goods and services tax (GST) rate applied to restaurant services in India? · 1/1 claims supported · `a5e65bc090a34d1aaac2921613d111ab`
- **complete** — Who is the current chief executive officer of Zerodha, and in which year did they take the role? · 1/1 claims supported · `c848a204b9e142809dffdf843ed71db1`
- **incomplete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. · 2/3 claims supported · `726469b656424ffdbdb7318685fa7bf0`
- **unaudited** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? · `7b8ada2aee234841ac5f6b7a69271581`
- **complete** — Who is the chief technology officer of Zerodha, and what is their academic background? · 4/4 claims supported · `4a02894c6b294156951a9a589251e205`
- **complete** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. · 1/1 claims supported · `36d7b9e980244556bd498c53775f905d`
- **incomplete** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? · 1/2 claims supported · `ee2fb3e3ac3246218009a4357d13165d`
- **incomplete** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. · 1/4 claims supported · `a13ad13f6daf47e5add34903e6a9f953`

### 2026-09-06T07:11:54.316793+00:00 — 5/8 passed
- **complete** — What is the current goods and services tax (GST) rate applied to restaurant services in India? · 2/2 claims supported · `f8f58d7f92724e68ba5bf7e6e092a8ad`
- **complete** — Who is the current chief executive officer of Zerodha, and in which year did they take the role? · 1/1 claims supported · `93a6f6af1d194f37ae063851a5e9319b`
- **complete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. · 3/3 claims supported · `78dcadc029c344188327b01cb7c51be9`
- **unaudited** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? · `6186ff29bc4d4edca3c1b841784797ea`
- **complete** — Who is the chief technology officer of Zerodha, and what is their academic background? · 2/2 claims supported · `2df954bb2fe9447ca26a1305d8ba4860`
- **complete** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. · 1/1 claims supported · `47b17c2d14794934813bbaf244e833c8`
- **incomplete** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? · 0/1 claims supported · `2bdb33bd052345428da80d51485d7a7b`
- **incomplete** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. · 1/4 claims supported · `e9f3ad59b0ce4338b12f73d0a942cf55`

