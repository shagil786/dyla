"""Tests for the source-disagreement resolver.

The property under test is not "a winner is produced" -- a resolver that always
picks something is exactly as uninformative as an auditor that approves
everything. It is that the *stated reason* matches the rule that fired, and
that the genuine standoff stays reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dyla.resolution import (
    DEFAULT_TIER,
    SourceGrade,
    grade_source,
    resolve_disagreement,
)


def _d(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


@pytest.mark.parametrize(
    ("url", "tier"),
    [
        ("https://example.com/filings/zepto-fy25-financials", 4),
        ("https://example.gov.in/cbic/gst-restaurant-rates", 4),
        ("https://example.com/exchange/infosys-annual-report-fy25", 4),
        ("https://example.com/business-daily/zerodha-leadership", 2),
        ("https://example.com/quick-summaries/infosys-revenue-note", 1),
        ("https://example.com/something-unclassified/page", DEFAULT_TIER),
    ],
)
def test_grade_source_assigns_expected_tier(url: str, tier: int) -> None:
    assert grade_source(url).tier == tier


def test_grade_source_takes_the_highest_matching_tier() -> None:
    """A filing that happens to summarise is a filing, not a summary."""
    graded = grade_source("https://example.com/filings/annual-report-summary")
    assert graded.tier == 4


def test_authority_beats_recency_even_when_the_weaker_source_is_newer() -> None:
    """The rule the whole module exists for.

    A preliminary summary does not overturn an audited filing by being
    published later, and the justification must say authority decided it.
    """
    filing = grade_source(
        "https://example.com/exchange/infosys-annual-report-fy25", _d(2025, 4, 17)
    )
    note = grade_source(
        "https://example.com/quick-summaries/infosys-revenue-note", _d(2026, 12, 30)
    )
    resolution = resolve_disagreement(
        claim_source=filing, rival_source=note,
        claim_value="1,62,990 crore", rival_value="1,53,670 crore",
    )
    assert resolution.winner == "claim"
    assert resolution.basis == "authority"
    assert resolution.resolved is True
    assert "Authority" in resolution.justification
    assert "regardless of publication date" in resolution.justification


def test_authority_can_defeat_the_claim_not_only_confirm_it() -> None:
    """The resolver must be able to rule against the claim it was given."""
    resolution = resolve_disagreement(
        claim_source=grade_source("https://example.com/blog/note", _d(2026, 5, 1)),
        rival_source=grade_source("https://example.com/filings/report", _d(2025, 1, 1)),
    )
    assert resolution.winner == "rival"
    assert resolution.basis == "authority"


def test_recency_breaks_a_tie_within_one_tier() -> None:
    older = grade_source("https://example.com/filings/a", _d(2025, 4, 17))
    newer = grade_source("https://example.com/filings/b", _d(2026, 6, 2))
    resolution = resolve_disagreement(claim_source=older, rival_source=newer)
    assert resolution.winner == "rival"
    assert resolution.basis == "recency"
    assert "Recency tie-break" in resolution.justification


def test_undated_loses_to_dated_within_a_tier() -> None:
    """An undated page cannot be shown to be the newer one.

    Treating undated as newest would let any unstamped page overturn a dated
    source of equal authority, which is the opposite of the intended caution.
    """
    dated = grade_source("https://example.com/filings/a", _d(2025, 4, 17))
    undated = grade_source("https://example.com/filings/b", None)
    resolution = resolve_disagreement(claim_source=undated, rival_source=dated)
    assert resolution.winner == "rival"
    assert resolution.basis == "recency"


def test_same_tier_same_date_is_left_unresolved() -> None:
    """The standoff must stay reachable.

    If every input produced a winner, the resolver would be asserting a fact it
    has no basis for -- the failure this project's auditor exists to catch.
    """
    left = grade_source("https://example.com/filings/a", _d(2025, 4, 17))
    right = grade_source("https://example.com/filings/b", _d(2025, 4, 17))
    resolution = resolve_disagreement(claim_source=left, rival_source=right)
    assert resolution.winner == "unresolved"
    assert resolution.basis == "none"
    assert resolution.resolved is False
    assert "no principled choice" in resolution.justification


def test_both_undated_in_the_same_tier_is_unresolved() -> None:
    left = SourceGrade("https://a.example/filings/x", 4, "primary filing", None)
    right = SourceGrade("https://b.example/filings/y", 4, "primary filing", None)
    assert resolve_disagreement(claim_source=left, rival_source=right).winner == "unresolved"


def test_event_payload_is_flat_and_names_both_sources() -> None:
    """The trace has to show what was compared, not just the outcome."""
    resolution = resolve_disagreement(
        claim_source=grade_source("https://example.com/filings/a", _d(2025, 4, 17)),
        rival_source=grade_source("https://example.com/blog/b", _d(2026, 1, 1)),
        claim_value="1,62,990 crore", rival_value="1,53,670 crore",
    )
    event = resolution.as_event()
    assert event["winner"] == "claim"
    assert event["claim_value"] == "1,62,990 crore"
    assert event["rival_value"] == "1,53,670 crore"
    assert event["claim_source_published"] == "2025-04-17"
    assert event["rival_source_tier"] == 1
    # JSON-safe: no datetimes or dataclasses leak into the trace.
    assert all(isinstance(value, (str, int, float, bool)) for value in event.values())
