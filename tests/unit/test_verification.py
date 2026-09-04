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
    extract_numbers,
    extract_years,
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
