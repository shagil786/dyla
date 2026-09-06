# Evaluation

- Total: 8
- Passed: 5
- Failed: 3

## Questions

- **complete** — What is the current goods and services tax (GST) rate applied to restaurant services in India?
- **complete** — Who is the current chief executive officer of Zerodha, and in which year did they take the role?
- **complete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each.
- **unaudited** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors?
- **complete** — Who is the chief technology officer of Zerodha, and what is their academic background?
- **complete** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure.
- **incomplete** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round?
- **unaudited** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each.

## Verdict detail

### 1. What is the current goods and services tax (GST) rate applied to restaurant services in India? — complete
Run: `291fa4a01f514da7a19fd1a82d6085e5`

| Claim | Verdict | Cited sources |
|---|---|---|
| 1 | supported | https://busy.in/gst-rates/restaurant/; https://busy.in/gst-rates/restaurant/ |

### 2. Who is the current chief executive officer of Zerodha, and in which year did they take the role? — complete
Run: `2e0d62497a3d4e6fa2c33f6d604ac39d`

| Claim | Verdict | Cited sources |
|---|---|---|
| ceo_name | supported | https://zerodha.com/about/ |
| ceo_start_year | supported | https://zerodha.com/about/ |

### 3. List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. — complete
Run: `21509cdc91bb42a3a041adc98e6c48cb`

| Claim | Verdict | Cited sources |
|---|---|---|
| claim_1 | supported | https://en.wikipedia.org/wiki/Software_industry_in_Karnataka |
| claim_2 | supported | https://en.wikipedia.org/wiki/Software_industry_in_Karnataka |

### 4. Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? — unaudited
Run: `0a668c1adce5439b9b9f074eb10febb2`
_No claims were audited for this question._
### 5. Who is the chief technology officer of Zerodha, and what is their academic background? — complete
Run: `0a569fd9be494dc6934e4b5f7b72f2cb`

| Claim | Verdict | Cited sources |
|---|---|---|
| 1 | supported | https://techstory.in/zerodha-cto-kailash-nadh-reveals-only-5-were-hired-for-tech-team-in-last-4-years/; https://en.wikipedia.org/wiki/Zerodha |
| 2 | supported | https://en.wikipedia.org/wiki/Zerodha |
| 3 | supported | https://zerodha.com/about/ |
| 4 | supported | https://zerodha.com/about/ |

### 6. Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. — complete
Run: `b8851af7399c43e682c7556528ffa4a5`

| Claim | Verdict | Cited sources |
|---|---|---|
| 1 | supported | https://ticker.finology.in/discover/market-update/wipro-vs-Infosys-comparison |

### 7. How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? — incomplete
Run: `4bdacc5ab4bd48f3bf7594a4675de198`

| Claim | Verdict | Cited sources |
|---|---|---|
| 1 | unsupported | https://www.clay.com/dossier/zepto-funding |

### 8. State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. — unaudited
Run: `7a6ccc90430c440aa4eac61eeec0fd33`
_No claims were audited for this question._
## Cost per question

| # | Question | Status | Input tok | Output tok | Embed tok | Searches | Fetches | Skipped | Duration (ms) | Cost (rupees) | Projected ₹ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | What is the current goods and services tax (GST) rate applied to restaurant services in India? | complete | 2540 | 468 | 30781 | 4 | 8 | 0 | 68664 | unpriced | 0.0625 |
| 2 | Who is the current chief executive officer of Zerodha, and in which year did they take the role? | complete | 2604 | 466 | 24 | 0 | 2 | 4 | 50776 | unpriced | 0.0633 |
| 3 | List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. | complete | 4669 | 675 | 81232 | 4 | 10 | 0 | 35097 | unpriced | 0.1045 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? | unaudited | 2443 | 177 | 11745 | 1 | 5 | 0 | 11841 | unpriced | 0.0447 |
| 5 | Who is the chief technology officer of Zerodha, and what is their academic background? | complete | 2855 | 1200 | 21 | 0 | 5 | 4 | 46663 | unpriced | 0.1085 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. | complete | 3814 | 249 | 31 | 0 | 1 | 4 | 16845 | unpriced | 0.0682 |
| 7 | How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? | incomplete | 3067 | 625 | 30 | 0 | 1 | 2 | 16181 | unpriced | 0.0789 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. | unaudited | 3155 | 1176 | 35 | 0 | 0 | 4 | 28959 | unpriced | 0.1114 |
| | **Total** | | 25147 | 5036 | 123899 | 9 | 32 | 18 | 275026 | unpriced | 0.6420 |

**Cost (rupees) is unavailable.** No price known for model 'nvidia/nemotron-3.5-lightning-30b-a3b'. Set DYLA_PRICE_INPUT_PER_MTOK_USD and DYLA_PRICE_OUTPUT_PER_MTOK_USD (USD per 1M tokens), or add the model to dyla.pricing.KNOWN_MODEL_PRICING.

**Projected ₹** is not a measurement. It is what these exact token counts would have cost on `gpt-4o-mini` at $0.15/1M input and $0.6/1M output, converted at 94.5 INR/USD. The tokens are real; the model that would have charged for them did not run. Override the reference with `DYLA_COUNTERFACTUAL_MODEL`.

## Cost trend

- Total tokens: 30183 (input 25147, output 5036)
- Total estimated_cost (adapter units): 0.0
- Total duration: 275026 ms
- Memory hits by question: [5, 11, 8, 1, 15, 18, 4, 33] (first-question baseline: 5; later questions total: 90)

**Wall-clock trend** (analyst plus auditor, per question):

- Per question: 68664 ms, 50776 ms, 35097 ms, 11841 ms, 46663 ms, 16845 ms, 16181 ms, 28959 ms
- First to last: 68664 ms -> 28959 ms (-57.8%)
- Questions 5-8 (the memory-reusing half): 108648 ms total, 27162.0 ms mean
- These are fixture replays measured in milliseconds, not live latency. The ordering is meaningful; the magnitudes are not evidence about a networked run.

**Projected rupee trend on `gpt-4o-mini`** (a projection over real token counts, not a measured charge):

- Per question: ₹0.0625, ₹0.0633, ₹0.1045, ₹0.0447, ₹0.1085, ₹0.0682, ₹0.0789, ₹0.1114
- Q1 ₹0.0625 → Q8 ₹0.1114 (+78.1%)
- Most expensive: Q8 at ₹0.1114 (1.78× Q1)
- Suite total: ₹0.6420

## Answer completeness (recall)

Every other quality number here grades the claims that *were* made. This
one grades what was left out: for each question, the facts the fixture
corpus supports and the question asks for, scored against what the answer
actually asserted. See `src/dyla/recall.py` for the key and its limits.

| # | Question | Covered | Expected | Recall | Missing |
|---|---|---|---|---|---|
| 1 | What is the current goods and services tax (GST) rate applied to restaurant services in India? | 1 | 2 | 50% | restaurants in high-tariff hotels are taxed at 18% |
| 2 | Who is the current chief executive officer of Zerodha, and in which year did they take the role? | 2 | 2 | 100% | — |
| 3 | List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. | 2 | 3 | 67% | Mphasis is named |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? | 0 | 2 | 0% | Zepto raised 350 million led by General Catalyst; Swiggy Instamart's parent raised 200 million led by Prosus |
| 5 | Who is the chief technology officer of Zerodha, and what is their academic background? | 1 | 2 | 50% | he holds a PhD in computer science / AI |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. | 0 | 2 | 0% | Infosys revenue of 1,62,990 crore; Wipro revenue of 89,088 crore |
| 7 | How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? | 0 | 4 | 0% | valued at 1.4 billion in 2023; valued at 3.6 billion in 2024; valued at 5 billion in the latest round; the latest round was led by General Catalyst |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. | 0 | 4 | 0% | Zerodha is profitable; Infosys is profitable; Wipro is profitable; Zepto is not profitable / made a loss |
| | **Total** | **6** | **21** | **29%** | |

## Run history

Most recent 4 full-suite runs recorded.

**Verdict trend, oldest run on the left:**

Cell = supported/total claims audited; ✓ = passed, ✗ = not passed; — = question absent from that run.

| # | Question | Pass rate | | 09-06 06:38 | 09-06 06:47 | 09-06 07:19 | 09-06 07:34 |
|---|---|---|---|---|---|---|
| 1 | What is the current goods and services tax (GST) rate applied to restaurant services in India? | 3/4 | ✗ 1/2 | ✓ 1/1 | ✓ 2/2 | ✓ 1/1 |
| 2 | Who is the current chief executive officer of Zerodha, and in which year did they take the role? | 2/4 | unaudited | ✓ 1/1 | ✗ 1/2 | ✓ 2/2 |
| 3 | List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. | 2/4 | ✗ 2/3 | ✗ 1/2 | ✓ 3/3 | ✓ 2/2 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? | 0/4 | ✗ 0/2 | unaudited | unaudited | unaudited |
| 5 | Who is the chief technology officer of Zerodha, and what is their academic background? | 2/4 | unaudited | ✗ 0/1 | ✓ 2/2 | ✓ 4/4 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. | 2/4 | unaudited | ✗ 0/1 | ✓ 1/1 | ✓ 1/1 |
| 7 | How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? | 0/4 | unaudited | unaudited | unaudited | ✗ 0/1 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. | 1/4 | unaudited | ✗ 0/1 | ✓ 1/1 | unaudited |

**Run details (newest first):**

### 2026-09-06T07:34:49.523136+00:00 — 5/8 passed
- **complete** — What is the current goods and services tax (GST) rate applied to restaurant services in India? · 1/1 claims supported · `291fa4a01f514da7a19fd1a82d6085e5`
- **complete** — Who is the current chief executive officer of Zerodha, and in which year did they take the role? · 2/2 claims supported · `2e0d62497a3d4e6fa2c33f6d604ac39d`
- **complete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. · 2/2 claims supported · `21509cdc91bb42a3a041adc98e6c48cb`
- **unaudited** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? · `0a668c1adce5439b9b9f074eb10febb2`
- **complete** — Who is the chief technology officer of Zerodha, and what is their academic background? · 4/4 claims supported · `0a569fd9be494dc6934e4b5f7b72f2cb`
- **complete** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. · 1/1 claims supported · `b8851af7399c43e682c7556528ffa4a5`
- **incomplete** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? · 0/1 claims supported · `4bdacc5ab4bd48f3bf7594a4675de198`
- **unaudited** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. · `7a6ccc90430c440aa4eac61eeec0fd33`

### 2026-09-06T07:19:48.879285+00:00 — 5/8 passed
- **complete** — What is the current goods and services tax (GST) rate applied to restaurant services in India? · 2/2 claims supported · `7447f0f79878414cae87124235e89969`
- **incomplete** — Who is the current chief executive officer of Zerodha, and in which year did they take the role? · 1/2 claims supported · `0d4ea98e4fa949db98b933c8526c5b82`
- **complete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. · 3/3 claims supported · `8dc4292186034c099ec2bf67f096c1ec`
- **unaudited** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? · `412cdb065d204e5483ebf4effd244503`
- **complete** — Who is the chief technology officer of Zerodha, and what is their academic background? · 2/2 claims supported · `8598905b330540bc8abc8a29d983ddb0`
- **complete** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. · 1/1 claims supported · `c1778668badf485e8fab2e2833434fce`
- **unaudited** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? · `f01b81ebc6554317b965b7866d00cbf0`
- **complete** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. · 1/1 claims supported · `63f494e5168a4d52bbe3259a7eebaeca`

### 2026-09-06T06:47:29.600793+00:00 — 2/8 passed
- **complete** — What is the current goods and services tax (GST) rate applied to restaurant services in India? · 1/1 claims supported · `8751d12d106b42e3ab5b1d57b0bf135c`
- **complete** — Who is the current chief executive officer of Zerodha, and in which year did they take the role? · 1/1 claims supported · `d579cd73943f4d0d8c143061b7802c9c`
- **incomplete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. · 1/2 claims supported · `87fdf0344e7547059802ee58d254db56`
- **unaudited** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? · `7eecd5012a0a4d4199ae88ba6f6c1b5e`
- **incomplete** — Who is the chief technology officer of Zerodha, and what is their academic background? · 0/1 claims supported · `7f38ac1b7c1c4370beca07e07835f5d7`
- **incomplete** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. · 0/1 claims supported · `d69b16f7e2484b01b0e12441e23499a6`
- **unaudited** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? · `9bf0ba37ff094becb57c66f667ce720c`
- **incomplete** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. · 0/1 claims supported · `a11f17dc3d2e4a6e94ac46f2a2ddf910`

### 2026-09-06T06:38:05.194712+00:00 — 0/8 passed
- **incomplete** — What is the current goods and services tax (GST) rate applied to restaurant services in India? · 1/2 claims supported · `0d0fe491841f4d90b09677ad3c9b6423`
- **unaudited** — Who is the current chief executive officer of Zerodha, and in which year did they take the role? · `80cf9061bd564c07a78ece13dbca8e9c`
- **incomplete** — List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each. · 2/3 claims supported · `caa1be526fc44fb5919291646ac8b3ad`
- **incomplete** — Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors? · 0/2 claims supported · `63871950d2f745699d16110a8c908f56`
- **unaudited** — Who is the chief technology officer of Zerodha, and what is their academic background? · `e923ff7168ff44d887ed3b145443508e`
- **unaudited** — Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure. · `ca6b14a203034692929cb08b2894871c`
- **unaudited** — How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round? · `f1643124163e4aab928919bb356f482c`
- **unaudited** — State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each. · `11fcfbaa0b32418e9bc6215d4471f288`

