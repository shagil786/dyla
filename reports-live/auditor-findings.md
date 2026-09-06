# What the auditor caught

Run mode: **live / reuse=True**.

## 1. Verdicts on the analyst's own answers

- Claims audited: **11** across 8 questions
- Auditor objected to: **1**

| Verdict | Claims |
| --- | --- |
| supported | 10 |
| unsupported | 1 |
| contradicted | 0 |
| uncited | 0 |

| # | Question | Result | Claims | Objections |
| --- | --- | --- | --- | --- |
| 1 | What is the current goods and services tax (GST) rate applied to rest… | complete | 1 | 0 |
| 2 | Who is the current chief executive officer of Zerodha, and in which y… | complete | 2 | 0 |
| 3 | List the three largest software services exporters by revenue that ar… | complete | 2 | 0 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 … | unaudited | 0 | 0 |
| 5 | Who is the chief technology officer of Zerodha, and what is their aca… | complete | 4 | 0 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in ru… | complete | 1 | 0 |
| 7 | How did Zepto's valuation change across its funding rounds up to its … | incomplete | 1 | 1 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable accor… | unaudited | 0 | 0 |

### Every objection, in full

**Q7 · unsupported** — Zepto's valuation has evolved across its funding rounds, starting from early seed rounds and culminating in a $7.15 billion unicorn valuation and a $4.5 billion pre-IPO private placement in August 2026.

> The provided source document (Clay.com dossier on Zepto funding) does not contain information about Zepto's valuation history, funding rounds, or specific valuation figures such as $7.15 billion or $4.5 billion pre-IPO placement in August 2026. The document focuses on Clay's own product features and customer examples, with no cited funding data for Zepto.

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

**Detection rate: 15/20 (75%)**

| Defect class | Caught | Planted | Detection |
| --- | --- | --- | --- |
| `inflated_figure` | 2 | 4 | 50% |
| `dropped_citation` | 4 | 4 | 100% |
| `negated_claim` | 1 | 4 | 25% |
| `fabricated_claim` | 4 | 4 | 100% |
| `swapped_entity` | 4 | 4 | 100% |

### Misses

These are the planted defects the auditor waved through. They are the
honest limit of what it can do today.

| Defect class | Verdict | Planted claim |
| --- | --- | --- |
| `negated_claim` | supported | The current GST rate applied to restaurant services in India is not 5% without Input Tax … |
| `negated_claim` | supported | Infosys Ltd is not headquartered in Bengaluru and is a major software services exporter. |
| `negated_claim` | supported | Wipro Ltd is not headquartered in Bengaluru and is a major software services exporter. |
| `inflated_figure` | supported | He joined Zerodha in 20,130 to start its technology team and has served as the company's … |
| `inflated_figure` | supported | Nithin bootstrapped and founded Zerodha in 20,100 to overcome the hurdles he faced during… |

### Examples of catches

**`inflated_figure` → unsupported**

- Original: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Planted: The current GST rate applied to restaurant services in India is 50% without Input Tax Credit for regular restaurants, whether air-condition…
- Auditor: The claim states a 50% GST rate without Input Tax Credit for regular restaurants, but the source document clearly reports a 5% GST rate for non-AC, AC, and takeaway services, with no ITC eligibility. The document specifies 18% rates only for hotels with room tariffs above ₹7,500 or specified premises, and 5% for all other regular restaurants. There is no mention of a 50% rate anywhere in the text.

**`dropped_citation` → uncited**

- Original: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Planted: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Auditor: The claim has no citations to independently retrieve.

**`fabricated_claim` → unsupported**

- Original: The current GST rate applied to restaurant services in India is 5% without Input Tax Credit for regular restaurants, whether air-conditione…
- Planted: The company announced a secondary listing on the Singapore Exchange in the same quarter.
- Auditor: The source document discusses GST rates for restaurant services in India and does not mention any secondary listing on the Singapore Exchange. The claim is unrelated to the provided text.

**`swapped_entity` → unsupported**

- Original: Nithin Kamath is the current chief executive officer of Zerodha
- Planted: Nithin Kamath is the current chief executive officer of Infosys
- Auditor: The source document identifies Nithin Kamath as the Founder and CEO of Zerodha, not Infosys. There is no information in the document linking him to Infosys or serving as its CEO.

**`negated_claim` → unsupported**

- Original: Nithin Kamath is the current chief executive officer of Zerodha
- Planted: Nithin Kamath is not the current chief executive officer of Zerodha
- Auditor: The source document explicitly states that Nithin Kamath is the 'Founder, CEO' of Zerodha, directly contradicting the claim that he is not the current CEO.
