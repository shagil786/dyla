"""Tests for deterministic claim verification, using realistic paraphrased prose.

The previous auditor test suite asserted claim text "supported" against document
text "source". Those fixtures pass under a matcher that is badly wrong, which is
how a comparator that could never return "supported" for a real source, and
could never return "contradicted" at all, shipped to main. Every fixture here is
prose of the kind a live fetch actually returns.
"""

from __future__ import annotations

import pytest

from dyla.auditor import _TextComparator
from dyla.domain import Claim, Citation, Document
from dyla.verification import (
    CONFLICT_TOLERANCE,
    MATCH_TOLERANCE,
    NumericFact,
    content_words,
    corroborates,
    extract_numbers,
    extract_years,
    on_topic,
    verify_claim,
)


# --------------------------------------------------------------------------
# Number extraction: Indian and Western magnitudes
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("revenue of Rs 1,53,670 crore", 1.53670e12),
        ("revenue of 1.54 lakh crore rupees", 1.54e12),
        ("raised $665 million", 665e6),
        ("a $1.4 billion round", 1.4e9),
        ("₹2,000 crore", 2.0e10),
        ("50,000 crore", 5.0e11),
        ("3.5 lakh", 3.5e5),
    ],
)
def test_extract_numbers_normalises_indian_and_western_magnitudes(text, expected):
    facts = extract_numbers(text)
    assert facts, f"no number extracted from {text!r}"
    assert any(abs(fact.value - expected) / expected < 1e-6 for fact in facts), (
        f"{text!r} -> {[f.value for f in facts]}, expected {expected}"
    )


def test_bare_year_is_not_treated_as_a_magnitude():
    """Otherwise "2024" would be compared against monetary amounts."""
    assert extract_numbers("in the financial year 2024") == []
    assert extract_years("in the financial year 2024") == {2024}
    assert extract_years("FY2023 and 2025 results") == {2023, 2025}


def test_percentages_and_currency_are_different_kinds():
    percent = extract_numbers("grew 4.7%")[0]
    currency = extract_numbers("earned $4.7")[0]
    assert percent.kind == "percent"
    assert currency.kind == "currency"
    # Same magnitude, different kind -> never comparable.
    assert not percent.matches(currency)
    assert not percent.conflicts(currency)


def test_content_words_strips_stopwords():
    assert content_words("the revenue of the company was") == {"revenue", "company"}


# --------------------------------------------------------------------------
# The regression that motivated this module
# --------------------------------------------------------------------------

CLAIM_REVENUE = "Infosys reported revenue of 1,53,670 crore rupees in FY2024."

SOURCE_SUPPORTING = (
    "Infosys Limited reported consolidated revenue of Rs 1,53,670 crore for the "
    "financial year 2024, up 4.7% year on year. The board recommended a final dividend."
)


def test_paraphrased_supporting_source_is_supported():
    """The exact case the old substring matcher got wrong."""
    result = verify_claim(CLAIM_REVENUE, {"https://example.com/ar": SOURCE_SUPPORTING})
    assert result.status == "supported", result.explanation
    assert "1,53,670" in " ".join(result.matched_facts)


def test_rounded_restatement_still_supports():
    """1.54 lakh crore is 0.21% from 1,53,670 crore — inside MATCH_TOLERANCE."""
    source = "Infosys posted revenue of 1.54 lakh crore rupees for FY2024."
    result = verify_claim(CLAIM_REVENUE, {"https://example.com/x": source})
    assert result.status == "supported", result.explanation


def test_different_figure_on_topic_is_contradicted():
    source = (
        "Infosys Limited reported consolidated revenue of Rs 1,22,000 crore for the "
        "financial year 2024, the company said in its annual report."
    )
    result = verify_claim(CLAIM_REVENUE, {"https://example.com/x": source})
    assert result.status == "contradicted", result.explanation
    assert result.conflicting_facts


def test_on_topic_source_that_omits_the_figure_is_unsupported():
    source = (
        "Infosys Limited published its annual report for the financial year 2024. "
        "The company described a challenging demand environment and headcount reduction."
    )
    result = verify_claim(CLAIM_REVENUE, {"https://example.com/x": source})
    assert result.status == "unsupported", result.explanation
    assert "1,53,670" in " ".join(result.missing_facts)


def test_off_topic_source_is_uncited_not_unsupported():
    """'uncited' means the source does not address the claim; the distinction matters."""
    source = "The Bengaluru metro Purple Line extension opened to passengers on Saturday."
    result = verify_claim(CLAIM_REVENUE, {"https://example.com/x": source})
    assert result.status == "uncited", result.explanation


# --------------------------------------------------------------------------
# corroborates(): the independent cross-check question
# --------------------------------------------------------------------------

def test_corroborates_when_an_independent_source_states_the_figure():
    source = (
        "Infosys Limited reported consolidated revenue of Rs 1,53,670 crore for the "
        "financial year 2024 according to its annual report."
    )
    assert corroborates(CLAIM_REVENUE, source)


def test_corroborates_a_rounded_restatement_within_tolerance():
    source = "Infosys posted revenue of 1.54 lakh crore rupees for FY2024."
    assert corroborates(CLAIM_REVENUE, source)


def test_does_not_corroborate_when_the_source_is_on_topic_but_states_a_different_figure():
    source = (
        "Infosys Limited reported consolidated revenue of Rs 1,22,000 crore for the "
        "financial year 2024, the company said in its annual report."
    )
    assert not corroborates(CLAIM_REVENUE, source)


def test_does_not_corroborate_when_the_figure_belongs_to_another_subject():
    source = "The Nifty index closed at 24,500 points while gold traded near 72,000 rupees."
    assert not corroborates(CLAIM_REVENUE, source)


def test_a_multi_figure_claim_is_corroborated_by_either_figure():
    """A comparison claim needs one page per company; either confirms it."""
    claim = "Infosys reported revenue of 1,53,670 crore rupees in FY2024 while Wipro reported 89,088 crore rupees."
    infosys_page = "Infosys Limited reported consolidated revenue of 1,53,670 crore rupees for FY2024."
    wipro_page = "Wipro Limited reported consolidated revenue of 89,088 crore rupees for FY2024."
    assert corroborates(claim, infosys_page)
    assert corroborates(claim, wipro_page)


def test_year_only_claims_are_corroborated_by_the_year():
    claim = "Nithin Kamath has served as chief executive officer of Zerodha since 2010."
    source = "Zerodha was founded in 2010 by Nithin Kamath, who remains chief executive officer."
    assert corroborates(claim, source)
    no_year = "Zerodha is the largest retail broker in India by active clients."
    assert not corroborates(claim, no_year)


def test_figureless_claims_need_an_actual_restatement_to_corroborate():
    claim = "Nithin Kamath is the chief executive officer of Zerodha."
    restated = (
        "Nithin Kamath, the chief executive officer of Zerodha, addressed the "
        "brokerage's annual results call."
    )
    assert corroborates(claim, restated)
    adjacent = "Zerodha is a Bengaluru-based brokerage founded by the Kamath brothers."
    assert not corroborates(claim, adjacent)


def test_on_topic_and_corroborates_agree_on_the_relevance_gate():
    claim = "Infosys reported revenue of 1,53,670 crore rupees in FY2024."
    assert on_topic(claim, "Infosys Limited published its annual report for FY2024.")
    assert not on_topic(claim, "The Bengaluru metro opened a new extension on Saturday.")


def test_rounding_band_between_thresholds_is_unsupported_not_contradicted():
    """A 3% difference sits between MATCH (1%) and CONFLICT (5%).

    Reported as unverified rather than forced into either verdict. An auditor
    that called this a contradiction would be crying wolf over rounding.
    """
    assert MATCH_TOLERANCE < 0.03 < CONFLICT_TOLERANCE
    source = (
        "Infosys Limited reported consolidated revenue of Rs 1,58,280 crore for the "
        "financial year 2024 according to the filing."
    )
    result = verify_claim(CLAIM_REVENUE, {"https://example.com/x": source})
    assert result.status == "unsupported", result.explanation
    assert not result.conflicting_facts


def test_unrelated_number_elsewhere_on_page_does_not_manufacture_a_contradiction():
    source = (
        "Infosys Limited reported consolidated revenue of Rs 1,53,670 crore for the "
        "financial year 2024. In unrelated news the Nifty index closed at 24,500 points "
        "while gold traded near 72,000 rupees per ten grams."
    )
    result = verify_claim(CLAIM_REVENUE, {"https://example.com/x": source})
    assert result.status == "supported", result.explanation


# --------------------------------------------------------------------------
# Polarity contradiction for claims with no numbers
# --------------------------------------------------------------------------

def test_antonym_reversal_is_contradicted():
    claim = "Zepto reported a net profit in its latest published financial year."
    source = (
        "Zepto reported a net loss in its latest published financial year, "
        "widening from the year before as it spent on expansion."
    )
    result = verify_claim(claim, {"https://example.com/x": source})
    assert result.status == "contradicted", result.explanation


def test_negation_reversal_is_contradicted():
    claim = "Zerodha is profitable according to its latest annual filing."
    source = "Zerodha is not profitable according to its latest annual filing, the company disclosed."
    result = verify_claim(claim, {"https://example.com/x": source})
    assert result.status == "contradicted", result.explanation


def test_negation_shared_with_the_source_cancels_instead_of_hiding_a_real_flip():
    """The seeded 'negated_claim' mutation this check exists to catch.

    The mutated claim carries TWO negation words — 'not taxed' and 'without
    input tax credit' — and so does the source ('without input tax credit').
    Judging negation parity by mere presence on each side counts the shared
    'without' clause on both sides and waves the mutation through as
    supported. Parity must be judged per shared word: 'taxed' is negated on
    the claim side only.
    """
    claim = (
        "Restaurant services in India are not taxed at 5% GST without input tax "
        "credit for standalone restaurants."
    )
    source = (
        "Restaurant services in India are taxed at 5% GST without input tax credit "
        "for standalone restaurants. Restaurants located within hotels where the "
        "declared room tariff exceeds 7,500 rupees per night are taxed at 18% GST "
        "with input tax credit."
    )
    result = verify_claim(claim, {"https://example.com/x": source})
    assert result.status == "contradicted", result.explanation


def test_a_subclause_negation_in_a_weaker_sentence_cannot_override_a_better_restatement():
    """Scope regression: a claim quoted verbatim by its source is supported.

    The claim carries 'without input tax credit'; the source's second sentence
    is about a different customer class that pays 'with input tax credit'. A
    naive polarity check reads the second sentence as the claim's negation
    even though the first sentence restates the claim exactly. A sentence may
    only contradict when no better-matching sentence stays silent.
    """
    claim = (
        "Restaurant services in India are taxed at 5% GST without input tax credit "
        "for standalone restaurants."
    )
    source = (
        "Restaurant services in India are taxed at 5% GST without input tax credit "
        "for standalone restaurants. Restaurants located within hotels where the "
        "declared room tariff exceeds 7,500 rupees per night are taxed at 18% GST "
        "with input tax credit."
    )
    result = verify_claim(claim, {"https://example.com/x": source})
    assert result.status == "supported", result.explanation


def test_scope_discriminator_is_general_not_keyed_to_any_fixture_vocabulary():
    """The same structure with unrelated wording must behave identically."""
    healthy = "The Atlas device ships with a one-year warranty without a repair fee for home users."
    source = (
        "The Atlas device ships with a one-year warranty without a repair fee for "
        "home users. Home users who ship the device with the extended plan pay a "
        "repair fee of 60 dollars a year for a three-year warranty."
    )
    assert verify_claim(healthy, {"https://example.com/x": source}).status == "supported"

    mutated = (
        "The Atlas device does not ship with a one-year warranty without a repair "
        "fee for home users."
    )
    result = verify_claim(mutated, {"https://example.com/x": source})
    assert result.status == "contradicted", result.explanation


def test_future_intent_does_not_contradict_a_present_tense_claim():
    """'aims to be profitable' must not be read as 'is not profitable'."""
    claim = "Zepto operates more than 250 dark stores across India."
    source = (
        "Zepto operates more than 250 dark stores across India and aims to be "
        "profitable within the next financial year."
    )
    result = verify_claim(claim, {"https://example.com/x": source})
    assert result.status == "supported", result.explanation


def test_lexical_restatement_without_numbers_is_supported():
    claim = "Nithin Kamath is the chief executive officer of Zerodha."
    source = (
        "Nithin Kamath, the chief executive officer of Zerodha, addressed the "
        "brokerage's annual results call in Bengaluru."
    )
    result = verify_claim(claim, {"https://example.com/x": source})
    assert result.status == "supported", result.explanation


# --------------------------------------------------------------------------
# Multi-source behaviour
# --------------------------------------------------------------------------

def test_one_supporting_source_is_enough_when_the_other_is_merely_silent():
    result = verify_claim(
        CLAIM_REVENUE,
        {
            "https://example.com/a": SOURCE_SUPPORTING,
            "https://example.com/b": "Infosys announced a new delivery centre in FY2024.",
        },
    )
    assert result.status == "supported", result.explanation


def test_a_source_that_disagrees_outweighs_one_that_agrees():
    """Disagreement is surfaced, not averaged away."""
    result = verify_claim(
        CLAIM_REVENUE,
        {
            "https://example.com/a": SOURCE_SUPPORTING,
            "https://example.com/b": (
                "Infosys Limited reported consolidated revenue of Rs 1,22,000 crore "
                "for the financial year 2024 in its regulatory filing."
            ),
        },
    )
    assert result.status == "contradicted", result.explanation


def test_empty_and_missing_inputs_fail_closed():
    assert verify_claim("", {"u": "text"}).status == "unsupported"
    assert verify_claim("a claim", {}).status == "unsupported"
    assert verify_claim("a claim", {"u": "   "}).status == "unsupported"


# --------------------------------------------------------------------------
# The comparator the CLI actually ships with
# --------------------------------------------------------------------------

def _doc(text: str, url: str = "https://example.com/x") -> Document:
    return Document(source_id="s1", url=url, title="Source", text=text, published_at=None)


def _claim(text: str) -> Claim:
    return Claim(
        id="c1",
        text=text,
        citations=[Citation(url="https://example.com/x", title="Source", source_id="s1", chunk_id=None)],
        confidence="high",
    )


def test_default_comparator_supports_a_paraphrased_source():
    """`.env.example` ships DYLA_AUDITOR_PROVIDER=local, so this is the default path.

    It previously had zero test coverage of any kind.
    """
    status, explanation = _TextComparator().compare(
        _claim(CLAIM_REVENUE), {"https://example.com/x": _doc(SOURCE_SUPPORTING)}
    )
    assert status == "supported", explanation


def test_default_comparator_can_return_contradicted():
    """The old implementation had no code path to this verdict at all."""
    status, explanation = _TextComparator().compare(
        _claim(CLAIM_REVENUE),
        {"https://example.com/x": _doc(
            "Infosys Limited reported consolidated revenue of Rs 1,22,000 crore for "
            "the financial year 2024."
        )},
    )
    assert status == "contradicted", explanation


def test_default_comparator_does_not_approve_everything():
    """Guard against the failure mode the brief calls out explicitly."""
    status, _ = _TextComparator().compare(
        _claim(CLAIM_REVENUE),
        {"https://example.com/x": _doc("A completely unrelated page about monsoon forecasts.")},
    )
    assert status != "supported"


def test_numeric_fact_tolerance_bands():
    base = NumericFact(value=1000.0, kind="currency", raw="1000")
    assert base.matches(NumericFact(1005.0, "currency", "1005"))       # 0.5% -> match
    assert not base.matches(NumericFact(1030.0, "currency", "1030"))   # 3%   -> no match
    assert not base.conflicts(NumericFact(1030.0, "currency", "1030")) # 3%   -> no conflict
    assert base.conflicts(NumericFact(1200.0, "currency", "1200"))     # 20%  -> conflict


# --- misattribution -------------------------------------------------------
# A true statement bolted onto the wrong company is the failure mode that
# survived every other check: it matches on wording and on numbers, and only
# the name is wrong.


def test_a_true_statement_attributed_to_the_wrong_company_is_not_supported():
    result = verify_claim(
        "Nithin Kamath is the chief executive officer of Infosys.",
        {"https://example.com/zerodha": (
            "Nithin Kamath is the chief executive officer of Zerodha, the "
            "discount broker he co-founded in 2010."
        )},
    )

    assert result.status == "unsupported", (
        "the source is about Zerodha; it cannot vouch for a claim about Infosys"
    )
    assert "infosys" in result.explanation.casefold()


def test_misattribution_is_unsupported_not_contradicted():
    """Silence is not denial.

    A page about Zerodha that never mentions Infosys does not assert anything
    false about Infosys. Calling that "contradicted" would overstate what the
    auditor actually knows.
    """
    result = verify_claim(
        "Wipro reported revenue of 89,760 crore rupees.",
        {"https://example.com/infosys": "Infosys reported revenue of 89,760 crore rupees."},
        known_entities=frozenset({"Wipro", "Infosys"}),
    )

    assert result.status == "unsupported"


def test_period_labels_are_not_treated_as_entities():
    """Regression: FY2024 is a period, not a company.

    The first version of the attribution check demanded the source spell
    "FY2024" the same way the claim did, which broke five correct verdicts
    against sources reading "financial year 2024".
    """
    result = verify_claim(
        "Infosys reported revenue of 1,53,670 crore rupees in FY2024.",
        {"https://example.com/infosys": (
            "Infosys Limited reported consolidated revenue of Rs 1,53,670 crore "
            "for the financial year 2024."
        )},
    )

    assert result.status == "supported"


def test_a_sentence_initial_ordinary_word_is_not_an_entity():
    """"Restaurant services..." must not require the source to capitalise it."""
    result = verify_claim(
        "Restaurant services are taxed at 5% GST.",
        {"https://example.gov.in/gst": "Standalone restaurant services are taxed at 5% GST."},
    )

    assert result.status == "supported"


def test_a_page_that_never_names_the_subject_is_not_on_topic():
    """Regression: financial boilerplate is near-identical across companies.

    Infosys's filing shares 0.88 of its content words with a claim about
    *Zerodha's* profit -- "reported a net profit of N crore rupees for the
    financial year 2025" is the same sentence with the name swapped -- while
    sharing no entity with it. The old ``max(word, entity)`` rule called that
    on topic, the corroboration scan then found it silent on Zerodha's figure,
    and used that silence to reject a true, correctly cited claim. Q8 lost
    every profitability claim it had this way.
    """
    from dyla.verification import on_topic

    claim = "Zerodha reported a net profit of 4,700 crore rupees for the financial year 2025."
    infosys = ("Infosys Limited reported consolidated revenue of 1,62,990 crore rupees "
               "for the financial year 2025. The company reported a net profit of "
               "26,713 crore rupees and remains profitable.")
    assert not on_topic(claim, infosys)

    zerodha = ("Zerodha reported a net profit of 4,700 crore rupees for the financial "
               "year 2025. The brokerage remains profitable.")
    assert on_topic(claim, zerodha)


def test_on_topic_still_uses_word_overlap_when_the_claim_names_no_entity():
    """The entity requirement must not break claims that name nobody."""
    from dyla.verification import on_topic

    claim = "The tax rate applied to restaurant services is 5 percent without input tax credit."
    assert on_topic(claim, "Restaurant services are taxed at 5 percent without input tax credit.")
