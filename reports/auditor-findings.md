# What the auditor caught

Run mode: **offline-fixtures / reuse=True**.

## 1. Verdicts on the analyst's own answers

- Claims audited: **32** across 8 questions
- Auditor objected to: **1**

| Verdict | Claims |
| --- | --- |
| supported | 31 |
| unsupported | 0 |
| contradicted | 1 |
| uncited | 0 |

| # | Question | Result | Claims | Objections |
| --- | --- | --- | --- | --- |
| 1 | What is the current goods and services tax (GST) rate applied to rest… | incomplete | 4 | 1 |
| 2 | Who is the current chief executive officer of Zerodha, and in which y… | complete | 4 | 0 |
| 3 | List the three largest software services exporters by revenue that ar… | complete | 4 | 0 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 … | complete | 4 | 0 |
| 5 | Who is the chief technology officer of Zerodha, and what is their aca… | complete | 4 | 0 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in ru… | complete | 4 | 0 |
| 7 | How did Zepto's valuation change across its funding rounds up to its … | complete | 4 | 0 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable accor… | complete | 4 | 0 |

### Every objection, in full

**Q1 · contradicted** — Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.

> https://example.gov.in/cbic/gst-restaurant-rates contradicts the claim: the source states the opposite polarity of the claim (claim negates). Source text: "Restaurants located within hotels where the declared room tariff exceeds 7,500 rupees per night are taxed at 18% GST with input tax credit."

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

**Detection rate: 19/20 (95%)**

| Defect class | Caught | Planted | Detection |
| --- | --- | --- | --- |
| `inflated_figure` | 4 | 4 | 100% |
| `dropped_citation` | 4 | 4 | 100% |
| `negated_claim` | 3 | 4 | 75% |
| `fabricated_claim` | 4 | 4 | 100% |
| `swapped_entity` | 4 | 4 | 100% |

### Misses

These are the planted defects the auditor waved through. They are the
honest limit of what it can do today.

| Defect class | Verdict | Planted claim |
| --- | --- | --- |
| `negated_claim` | supported | Restaurant services in India are not taxed at 5% GST without input tax credit for standal… |

### Examples of catches

**`inflated_figure` → contradicted**

- Original: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Planted: Restaurant services in India are taxed at 50% GST without input tax credit for standalone restaurants.
- Auditor: https://example.gov.in/cbic/gst-restaurant-rates contradicts the claim: the source states the opposite polarity of the claim (claim negates). Source text: "Restaurants located within hotels where the declared room tariff exceeds 7,500 rupees per night are taxed at 18% GST with input tax credit."

**`dropped_citation` → uncited**

- Original: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Planted: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Auditor: The claim has no citations to independently retrieve.

**`fabricated_claim` → uncited**

- Original: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Planted: The company announced a secondary listing on the Singapore Exchange in the same quarter.
- Auditor: The fetched sources do not address the claim (only 0% of its key terms or entities appear).

**`negated_claim` → contradicted**

- Original: The 5% rate has applied to standalone restaurant services since 2017.
- Planted: The 5% rate has not applied to standalone restaurant services since 2017.
- Auditor: https://example.gov.in/cbic/gst-restaurant-rates contradicts the claim: the source states the opposite polarity of the claim (claim negates). Source text: "The 5% rate has applied to standalone restaurant services since 2017."

**`swapped_entity` → unsupported**

- Original: Infosys is headquartered in Bengaluru and is among the largest software services exporters in India.
- Planted: Zerodha is headquartered in Bengaluru and is among the largest software services exporters in India.
- Auditor: The claim is attributed to zerodha, which none of the fetched sources mention. Whatever else the sources confirm is about something else.
