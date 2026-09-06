# What the auditor caught

Run mode: **live / reuse=False**.

## 1. Verdicts on the analyst's own answers

- Claims audited: **16** across 8 questions
- Auditor objected to: **5**

| Verdict | Claims |
| --- | --- |
| supported | 11 |
| unsupported | 5 |
| contradicted | 0 |
| uncited | 0 |

| # | Question | Result | Claims | Objections |
| --- | --- | --- | --- | --- |
| 1 | What is the current goods and services tax (GST) rate applied to rest… | complete | 1 | 0 |
| 2 | Who is the current chief executive officer of Zerodha, and in which y… | complete | 1 | 0 |
| 3 | List the three largest software services exporters by revenue that ar… | incomplete | 3 | 1 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 … | unaudited | 0 | 0 |
| 5 | Who is the chief technology officer of Zerodha, and what is their aca… | complete | 4 | 0 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in ru… | complete | 1 | 0 |
| 7 | How did Zepto's valuation change across its funding rounds up to its … | incomplete | 2 | 1 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable accor… | incomplete | 4 | 3 |

### Every objection, in full

**Q3 · unsupported** — Tata Consultancy Services Ltd is headquartered in Bengaluru and is a major software services exporter.

> The provided text discusses software export figures for Karnataka and mentions Bengaluru as a major IT hub, but does not state that Tata Consultancy Services Ltd is headquartered in Bengaluru. The claim about TCS headquarters is therefore unsupported by the source documents.

**Q7 · unsupported** — The most recent round was a pre-IPO private placement in August 2026 led by StepStone Group at a $4.5 billion valuation.

> The source document does not contain information about Zepto's most recent funding round, valuation, or investors. It focuses on Clay's data infrastructure and services.

**Q8 · unsupported** — Zerodha is not profitable according to latest published financials.

> The provided source document discusses Zepto's financials (net loss of Rs 1,538.67 crore in the March quarter) but contains no information about Zerodha's profitability or financial results. The claim about Zerodha cannot be verified from the given documents.

**Q8 · unsupported** — Infosys is profitable according to latest published financials.

> The provided source document discusses Zepto's financials, including its net loss and revenue, but contains no information about Infosys or its profitability. Therefore, the claim cannot be verified from the documents.

**Q8 · unsupported** — Wipro is profitable according to latest published financials.

> The provided source document discusses Zepto's financials, including its net loss and revenue, but contains no information about Wipro's profitability. Therefore, the claim that Wipro is profitable according to latest published financials cannot be verified from the documents.

## 2. Seeded defects

A support rate near 100% is not evidence that the auditor works. On the
offline harness the analyst model is extractive -- it quotes source
sentences verbatim -- so it *cannot* misattribute, drift or invent. The
section above therefore measures the model's inability to lie, not the
auditor's ability to detect lying.

To measure the auditor itself, known-bad claims are planted in the real
answers, one defect class at a time, and each is audited alone. Auditing
them in a batch would let a healthy neighbour's sources vouch for the
defective claim -- the cross-source masking bug that made this auditor
useless in the first place.

**Detection rate: 14/20 (70%)**

| Defect class | Caught | Planted | Detection |
| --- | --- | --- | --- |
| `inflated_figure` | 2 | 4 | 50% |
| `dropped_citation` | 4 | 4 | 100% |
| `negated_claim` | 2 | 4 | 50% |
| `fabricated_claim` | 4 | 4 | 100% |
| `swapped_entity` | 2 | 4 | 50% |

### Misses

These are the planted defects the auditor waved through. They are the
honest limit of what it can do today.

| Defect class | Verdict | Planted claim |
| --- | --- | --- |
| `negated_claim` | supported | The current GST rate applied to restaurant services in India is not 5% without Input Tax … |
| `inflated_figure` | supported | Nithin bootstrapped and founded Zerodha in 20,100 to overcome the hurdles he faced during… |
| `swapped_entity` | supported | Nithin bootstrapped and founded Infosys in 2010 to overcome the hurdles he faced during h… |
| `negated_claim` | supported | Tata Consultancy Services Ltd is not headquartered in Bengaluru and is a major software s… |
| `swapped_entity` | supported | Kailash Nadh is the Chief Technology Officer of Infosys. |
| `inflated_figure` | supported | He joined Zerodha in 20,130 to start its technology team and has served as the company's … |

### Examples of catches

**`inflated_figure` → unsupported**

- Original: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Planted: The current GST rate applied to restaurant services in India is 50% without Input Tax Credit for regular restaurants, whether air-condition…
- Auditor: The claim states a 50% GST rate without Input Tax Credit, but the source document clearly reports a 5% GST rate for regular restaurants (including AC, non-AC, and takeaway) without ITC. The document specifies 18% only for hotels with room tariffs above ₹7,500, which can claim ITC. No 50% rate is mentioned anywhere in the text.

**`dropped_citation` → uncited**

- Original: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Planted: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Auditor: The claim has no citations to independently retrieve.

**`fabricated_claim` → unsupported**

- Original: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Planted: The company announced a secondary listing on the Singapore Exchange in the same quarter.
- Auditor: The provided source document discusses GST rates for restaurant services in India and does not mention any secondary listing on the Singapore Exchange. The claim is unsupported as the document contains no relevant information about stock exchange listings.

**`swapped_entity` → unsupported**

- Original: Infosys Ltd is headquartered in Bengaluru and is a major software services exporter.
- Planted: Zerodha Ltd is headquartered in Bengaluru and is a major software services exporter.
- Auditor: The provided text discusses software export statistics for Karnataka and mentions Bengaluru as a major IT hub, but does not state that Zerodha Ltd is headquartered in Bengaluru or that it is a major software services exporter. The claim cannot be verified from the documents.

**`negated_claim` → unsupported**

- Original: Infosys Ltd is headquartered in Bengaluru and is a major software services exporter.
- Planted: Infosys Ltd is not headquartered in Bengaluru and is a major software services exporter.
- Auditor: The provided text discusses software export figures from Karnataka and mentions Bengaluru as a major IT hub, but does not state Infosys Ltd's headquarters location or confirm its status as a major software services exporter. The claim about Infosys Ltd's headquarters and export status cannot be verified from the given document.
