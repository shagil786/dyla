"""Behaviour policies: the thresholds that were previously scattered literals.

Every number here used to live as a default argument or a module constant at
its point of use — ``reuse_min_sources=2`` in the analyst's constructor,
``threshold=0.8`` in ``_restates_rejected_claim``, the tolerance floors at the
top of ``verification.py``, and so on. Each was individually tested but none
was visible as a *decision*: a reader had to know which file held it.

``Policies`` is the single source of truth for the values; the agents read
their defaults from ``DEFAULT_POLICIES`` (ADR-0001 increment 1). Scope, stated
plainly: per-run injection — passing a modified instance — is implemented for
the analyst's planning/reuse/retrieval knobs via ``AnalystAgent(policies=...)``.
The verification tolerances and the lexical blend weight are bound from
``DEFAULT_POLICIES`` at import time (their modules take no policy parameter),
so changing those is a code change to the ``Policies`` defaults, covered by the
pinning tests — not a per-run override. It is deliberately frozen and
deliberately *not* wired to environment variables: changing policy is a code
change with tests, not a deployment flag (same reasoning as the
``valid_events`` allowlist — visible and deliberate beats configurable and
silent).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Policies:
    """The analyst's behaviour thresholds, in one place.

    Grouped by the decision each value governs. Defaults are the values the
    system was tuned with; ``tests/unit/test_policies.py`` pins them.
    """

    # Planning: how many subqueries the planner may expand per question.
    max_subqueries: int = 4
    # Retrieval: results per web search, evidence kept per run, and the floor
    # below which a reuse bet is "corrected" by re-running the skipped queries.
    search_limit: int = 5
    evidence_limit: int = 8
    min_evidence: int = 1
    # Memory reuse: an entity counts as covered only when the index already
    # holds evidence from this many distinct sources (one is exactly the thin,
    # uncorroborated evidence the analyst is supposed to distrust), scored at
    # or above this floor (meaningful only with a real embedding — see
    # WRITEUP §6, weakness 6).
    reuse_enabled: bool = True
    reuse_min_sources: int = 2
    reuse_min_score: float = 0.0
    # How many memory records are fetched per query when gathering context.
    memory_search_limit: int = 10
    # A claim whose content words overlap a previously *rejected* claim by at
    # least this share is treated as a restatement and blocked.
    rejected_claim_overlap: float = 0.8

    # Verification (deterministic auditor). A fact is confirmed within
    # match_tolerance, contradicted beyond conflict_tolerance, and honestly
    # reported as unverified in between — the gap is the point, so match must
    # be strictly smaller than conflict.
    match_tolerance: float = 0.01
    conflict_tolerance: float = 0.05
    # Below this share of claim content words appearing in the sources, the
    # sources are judged not to address the claim at all.
    topicality_floor: float = 0.20
    # A sentence must share this share of the claim's content words before a
    # numeric disagreement inside it counts as a contradiction.
    conflict_context_floor: float = 0.34
    # Lexical entailment floor for figure-free claims.
    lexical_support_floor: float = 0.70

    # Retrieval blend: the local vector store's dense score is combined with
    # token-overlap lexical score as (1 - w) * dense + w * lexical.
    lexical_weight: float = 0.3

    def __post_init__(self) -> None:
        if self.max_subqueries < 1:
            raise ValueError("max_subqueries must be positive")
        if self.search_limit < 1 or self.evidence_limit < 1 or self.min_evidence < 1:
            raise ValueError("search_limit, evidence_limit and min_evidence must be positive")
        if self.memory_search_limit < 1:
            raise ValueError("memory_search_limit must be positive")
        if self.reuse_min_sources < 1:
            raise ValueError("reuse_min_sources must be positive")
        if self.reuse_min_score < 0.0:
            raise ValueError("reuse_min_score must be non-negative")
        if not 0.0 <= self.rejected_claim_overlap <= 1.0:
            raise ValueError("rejected_claim_overlap must be between 0 and 1")
        if not 0.0 <= self.match_tolerance or not 0.0 <= self.conflict_tolerance:
            raise ValueError("verification tolerances must be non-negative")
        if self.match_tolerance >= self.conflict_tolerance:
            # The unverified band between the two tolerances is what keeps the
            # auditor from crying contradiction over rounding; match >= conflict
            # would close it and misreport every rounding difference.
            raise ValueError("match_tolerance must be strictly below conflict_tolerance")
        if not 0.0 <= self.topicality_floor <= 1.0:
            raise ValueError("topicality_floor must be between 0 and 1")
        if not 0.0 <= self.conflict_context_floor <= 1.0:
            raise ValueError("conflict_context_floor must be between 0 and 1")
        if not 0.0 <= self.lexical_support_floor <= 1.0:
            raise ValueError("lexical_support_floor must be between 0 and 1")
        if not 0.0 <= self.lexical_weight <= 1.0:
            raise ValueError("lexical_weight must be between 0 and 1")


DEFAULT_POLICIES = Policies()
