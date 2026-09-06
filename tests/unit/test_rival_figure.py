"""Tests for the disagreement detector.

Every negative case here is a false positive the first implementation actually
produced against the project's own fixture corpus. The first draft gated only
on word overlap and reported six disagreements on the eight-question suite, of
which exactly one was real; these tests pin the three gates that removed the
other five.
"""

from __future__ import annotations

from dyla.verification import claim_subjects, rival_figure

INFOSYS_CLAIM = (
    "Infosys Limited reported consolidated revenue of 1,62,990 crore rupees "
    "for the financial year 2025."
)
WIPRO_CLAIM = (
    "Wipro Limited reported consolidated revenue of 89,088 crore rupees for "
    "the financial year 2025."
)


def test_detects_a_genuine_conflict_on_the_same_measure_and_subject() -> None:
    """The one real disagreement planted in the corpus."""
    source = (
        "Infosys Limited reported consolidated revenue of 1,53,670 crore rupees "
        "for the financial year 2025 according to a preliminary summary."
    )
    rival = rival_figure(INFOSYS_CLAIM, source)
    assert rival is not None
    assert "1,53,670" in rival.raw


def test_agreeing_source_is_not_a_conflict() -> None:
    source = (
        "Infosys Limited reported consolidated revenue of 1,62,990 crore rupees "
        "for the financial year 2025."
    )
    assert rival_figure(INFOSYS_CLAIM, source) is None


def test_a_different_company_is_not_a_conflict() -> None:
    """Regression: corporate suffixes are not subjects.

    "Infosys Limited ..." previously yielded the subject {"limited"}, which
    "Wipro Limited ..." satisfies, so Wipro's revenue was ruled to contradict
    Infosys's. Both figures are correct and about different companies.
    """
    source = (
        "Wipro Limited reported consolidated revenue of 89,088 crore rupees for "
        "the financial year 2025."
    )
    assert rival_figure(INFOSYS_CLAIM, source) is None


def test_a_different_measure_is_not_a_conflict() -> None:
    """Profit and revenue are both large rupee figures and do not conflict."""
    source = (
        "Infosys Limited reported a net profit of 26,713 crore rupees for the "
        "financial year 2025."
    )
    assert rival_figure(INFOSYS_CLAIM, source) is None


def test_valuation_and_raise_amount_are_different_measures() -> None:
    """Regression: "round" belonged to the funding group and matched valuations.

    "Zepto raised 350 million in a round that valued it at 5 billion" is one
    sentence containing both measures; grouping "round" with funding made a
    valuation claim conflict with a raise amount.
    """
    claim = "The round valued Zepto at 5 billion dollars."
    source = (
        "Zepto raised 350 million dollars in 2025 in a round led by General "
        "Catalyst."
    )
    assert rival_figure(claim, source) is None


def test_claim_with_no_named_subject_is_never_adjudicated() -> None:
    """Co-reference limit, failing safe.

    "The company reported ..." cannot be attributed, so no source can be shown
    to be talking about the same subject. Returning None keeps an
    unattributable figure out of the resolver rather than pairing it with
    whichever company happens to be nearby.
    """
    claim = "The company reported a net profit of 13,135 crore rupees."
    source = (
        "Zerodha reported a net profit of 4,700 crore rupees for the financial "
        "year 2025."
    )
    assert rival_figure(claim, source) is None


def test_unrelated_number_elsewhere_on_the_page_is_not_a_conflict() -> None:
    source = (
        "The Nifty index closed at 24,500 points while gold traded near 72,000 "
        "rupees per ten grams."
    )
    assert rival_figure(INFOSYS_CLAIM, source) is None


def test_claim_without_numbers_has_nothing_to_conflict_with() -> None:
    claim = "Nithin Kamath is the chief executive officer of Zerodha."
    source = "Kailash Nadh is the chief technology officer of Zerodha."
    assert rival_figure(claim, source) is None


def test_claim_subjects_strips_corporate_suffixes_but_keeps_the_name() -> None:
    assert claim_subjects(INFOSYS_CLAIM) == {"infosys"}
    assert claim_subjects(WIPRO_CLAIM) == {"wipro"}


def test_claim_subjects_keeps_sentence_initial_names() -> None:
    """Unlike named_entities, which drops them.

    Claims overwhelmingly begin with their subject, so dropping the first token
    discarded the only word identifying who a figure belonged to.
    """
    assert "infosys" in claim_subjects("Infosys reported revenue of 100 crore.")
