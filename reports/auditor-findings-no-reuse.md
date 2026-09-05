# What the auditor caught

Run mode: **offline-fixtures / reuse=False**.

## 1. Verdicts on the analyst's own answers

- Claims audited: **29** across 8 questions
- Auditor objected to: **0**

| Verdict | Claims |
| --- | --- |
| supported | 29 |
| unsupported | 0 |
| contradicted | 0 |
| uncited | 0 |

| # | Question | Result | Claims | Objections |
| --- | --- | --- | --- | --- |
| 1 | What is the current goods and services tax (GST) rate applied to rest… | complete | 4 | 0 |
| 2 | Who is the current chief executive officer of Zerodha, and in which y… | complete | 4 | 0 |
| 3 | List the three largest software services exporters by revenue that ar… | complete | 4 | 0 |
| 4 | Which Indian quick-commerce startups raised funding rounds above 100 … | complete | 3 | 0 |
| 5 | Who is the chief technology officer of Zerodha, and what is their aca… | complete | 4 | 0 |
| 6 | Compare the most recent full-year revenues of Infosys and Wipro in ru… | complete | 3 | 0 |
| 7 | How did Zepto's valuation change across its funding rounds up to its … | complete | 4 | 0 |
| 8 | State whether Zerodha, Infosys, Wipro, and Zepto are profitable accor… | complete | 3 | 0 |

### Every objection, in full

_The auditor raised no objections on this run._

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

**Detection rate: 20/20 (100%)**

| Defect class | Caught | Planted | Detection |
| --- | --- | --- | --- |
| `inflated_figure` | 4 | 4 | 100% |
| `dropped_citation` | 4 | 4 | 100% |
| `negated_claim` | 4 | 4 | 100% |
| `fabricated_claim` | 4 | 4 | 100% |
| `swapped_entity` | 4 | 4 | 100% |

### Misses

_Every planted defect was caught._

### Examples of catches

**`inflated_figure` → contradicted**

- Original: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Planted: Restaurant services in India are taxed at 50% GST without input tax credit for standalone restaurants.
- Auditor: The sources conflict with the claim: claim says 50% but https://example.gov.in/cbic/gst-restaurant-rates says 5%.

**`dropped_citation` → uncited**

- Original: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Planted: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Auditor: The claim has no citations to independently retrieve.

**`negated_claim` → contradicted**

- Original: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Planted: Restaurant services in India are not taxed at 5% GST without input tax credit for standalone restaurants.
- Auditor: https://example.gov.in/cbic/gst-restaurant-rates contradicts the claim: the source states the opposite polarity of the claim (claim negates). Source text: "Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants."

**`fabricated_claim` → uncited**

- Original: Restaurant services in India are taxed at 5% GST without input tax credit for standalone restaurants.
- Planted: The company announced a secondary listing on the Singapore Exchange in the same quarter.
- Auditor: The fetched sources do not address the claim (only 0% of its key terms or entities appear).

**`swapped_entity` → unsupported**

- Original: Infosys is headquartered in Bengaluru and is among the largest software services exporters in India.
- Planted: Zerodha is headquartered in Bengaluru and is among the largest software services exporters in India.
- Auditor: The claim is attributed to zerodha, which none of the fetched sources mention. Whatever else the sources confirm is about something else.
