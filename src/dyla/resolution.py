"""Resolving two credible sources that give different numbers.

Why this module exists
----------------------
Before this, the analyst's cross-check had exactly two outcomes: a second
source restated the figure (accept) or it did not (reject). A source that
addressed the claim and stated a *different* number fell into the second
bucket, so the agent's response to genuine disagreement was to drop the claim
and report that independent sources "none states the claim's figure".

That is the "reporting both and shrugging" failure in a more evasive form: it
does not even report both, it silently discards the better-sourced figure
because a worse-sourced one exists. A regulatory filing losing to a blog post
that disagrees with it is not caution, it is a bug with good manners.

The policy: authority first, recency as tie-break
-------------------------------------------------
1. **Authority.** Sources are graded into tiers (see ``AUTHORITY_TIERS``). A
   company's own filing outranks an exchange disclosure, which outranks
   established press, which outranks aggregators and summaries. A higher tier
   wins outright, regardless of date. This is the ordering a human analyst
   applies: a preliminary summary does not overturn an audited annual report
   by being published later.

2. **Recency, only within a tier.** When two sources sit in the same tier, the
   later publication wins, on the reasoning that same-authority sources
   disagreeing usually means one is a restatement of the other. A source with
   no date is treated as older than any dated source, because an undated page
   cannot be shown to be the newer one.

3. **Neither.** Same tier, same date (or both undated) is a genuine standoff.
   The resolver refuses to pick, and says so. This case must stay reachable:
   a resolver that always produces a winner is as uninformative as an auditor
   that approves everything.

What this deliberately does not do
----------------------------------
It does not read the sources to judge which figure is more plausible, and it
does not average them. Both would be inventing a fact. It ranks the
*provenance* and reports the ranking it applied, so the choice is auditable
and arguable rather than a black box. The justification string names the tier
and the date that decided it, and is written into the trace and the claim's
limitations.

Domain matching is substring-based on the URL, which is crude and will
misgrade a URL that merely contains a marker word. That is a stated limit,
not a hidden one -- see WRITEUP 4.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# Higher number = more authoritative. Ordered most specific first within a tier
# since matching takes the highest tier whose marker appears in the URL.
AUTHORITY_TIERS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (
        4,
        "primary filing or regulator",
        (
            "/filings/", "/filing/", "annual-report", "annual_report",
            "investor-relations", "investors/", "/sec.gov", "sebi.gov",
            "rbi.org", "mca.gov", ".gov.in", ".gov/", "cbic",
        ),
    ),
    (
        3,
        "exchange or official disclosure",
        ("/exchange/", "bseindia", "nseindia", "regulatory-disclosure", "press-release"),
    ),
    (
        2,
        "established press",
        (
            "reuters", "bloomberg", "ft.com", "economictimes", "livemint",
            "business-standard", "business-daily", "moneycontrol", "the-hindu",
            "tech-press", "funding-wire", "markets-wire", "news",
        ),
    ),
    (
        1,
        "aggregator, summary or unclassified",
        ("quick-summaries", "summary", "wiki", "blog", "explainer", "note"),
    ),
)

DEFAULT_TIER = 1
DEFAULT_TIER_LABEL = "aggregator, summary or unclassified"

Winner = Literal["claim", "rival", "unresolved"]


@dataclass(frozen=True)
class SourceGrade:
    """An authority grade and date for one URL."""

    url: str
    tier: int
    label: str
    published_at: datetime | None = None

    def date_text(self) -> str:
        return self.published_at.date().isoformat() if self.published_at else "undated"


@dataclass
class Resolution:
    """The outcome of comparing two disagreeing sources."""

    winner: Winner
    justification: str
    claim_source: SourceGrade
    rival_source: SourceGrade
    basis: Literal["authority", "recency", "none"] = "none"
    rival_value: str = ""
    claim_value: str = ""
    considered: list[SourceGrade] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.winner != "unresolved"

    def as_event(self) -> dict[str, object]:
        """Trace payload. Flat and JSON-safe, matching the other trace events."""
        return {
            "winner": self.winner,
            "basis": self.basis,
            "justification": self.justification,
            "claim_source": self.claim_source.url,
            "claim_source_tier": self.claim_source.tier,
            "claim_source_published": self.claim_source.date_text(),
            "claim_value": self.claim_value,
            "rival_source": self.rival_source.url,
            "rival_source_tier": self.rival_source.tier,
            "rival_source_published": self.rival_source.date_text(),
            "rival_value": self.rival_value,
        }


def grade_source(url: str, published_at: datetime | None = None) -> SourceGrade:
    """Grade one URL into an authority tier.

    Takes the *highest* matching tier: a URL carrying both "/filings/" and
    "summary" is a filing that happens to summarise, not a summary.
    """
    lowered = (url or "").casefold()
    for tier, label, markers in AUTHORITY_TIERS:
        if any(marker in lowered for marker in markers):
            return SourceGrade(url, tier, label, published_at)
    return SourceGrade(url, DEFAULT_TIER, DEFAULT_TIER_LABEL, published_at)


def _compare_dates(left: datetime | None, right: datetime | None) -> int:
    """1 if left is newer, -1 if right is newer, 0 if indistinguishable.

    Undated loses to dated: an undated page cannot be demonstrated to be the
    newer one, and treating it as newer would let any unstamped page overturn
    a dated source of equal authority.
    """
    if left is None and right is None:
        return 0
    if left is None:
        return -1
    if right is None:
        return 1
    if left == right:
        return 0
    return 1 if left > right else -1


def resolve_disagreement(
    *,
    claim_source: SourceGrade,
    rival_source: SourceGrade,
    claim_value: str = "",
    rival_value: str = "",
) -> Resolution:
    """Decide which of two disagreeing sources to believe, and say why.

    ``claim_source`` is the source the claim cites; ``rival_source`` states a
    conflicting figure. Returns a ``Resolution`` whose justification always
    names the rule applied and the evidence for it.
    """
    values = (claim_value, rival_value)

    if claim_source.tier != rival_source.tier:
        claim_wins = claim_source.tier > rival_source.tier
        winner_grade = claim_source if claim_wins else rival_source
        loser_grade = rival_source if claim_wins else claim_source
        justification = (
            f"Authority: {winner_grade.url} is a {winner_grade.label} "
            f"(tier {winner_grade.tier}) while {loser_grade.url} is a "
            f"{loser_grade.label} (tier {loser_grade.tier}), so the "
            f"higher-authority figure is preferred regardless of publication date."
        )
        return Resolution(
            winner="claim" if claim_wins else "rival",
            justification=justification,
            claim_source=claim_source,
            rival_source=rival_source,
            basis="authority",
            claim_value=values[0],
            rival_value=values[1],
        )

    order = _compare_dates(claim_source.published_at, rival_source.published_at)
    if order == 0:
        justification = (
            f"Unresolved: {claim_source.url} and {rival_source.url} are both a "
            f"{claim_source.label} (tier {claim_source.tier}) and neither is "
            f"demonstrably more recent ({claim_source.date_text()} vs "
            f"{rival_source.date_text()}). Authority and recency both tie, so "
            f"no principled choice is available and the disagreement stands."
        )
        return Resolution(
            winner="unresolved",
            justification=justification,
            claim_source=claim_source,
            rival_source=rival_source,
            basis="none",
            claim_value=values[0],
            rival_value=values[1],
        )

    claim_wins = order > 0
    winner_grade = claim_source if claim_wins else rival_source
    loser_grade = rival_source if claim_wins else claim_source
    justification = (
        f"Recency tie-break: both sources are a {claim_source.label} "
        f"(tier {claim_source.tier}), so authority does not separate them; "
        f"{winner_grade.url} ({winner_grade.date_text()}) is more recent than "
        f"{loser_grade.url} ({loser_grade.date_text()})."
    )
    return Resolution(
        winner="claim" if claim_wins else "rival",
        justification=justification,
        claim_source=claim_source,
        rival_source=rival_source,
        basis="recency",
        claim_value=values[0],
        rival_value=values[1],
    )
