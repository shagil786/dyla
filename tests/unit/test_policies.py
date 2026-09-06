"""Policies is the single source for behaviour thresholds (ADR-0001, P7-1).

This refactor must be behaviour-preserving, so the defaults are pinned to the
literals they replaced, and the override rules — per-knob kwargs beat the
policy — are asserted rather than assumed.
"""

from dyla.analyst import AnalystAgent, _restates_rejected_claim
from dyla.local_vector import _LEXICAL_WEIGHT
from dyla.policies import DEFAULT_POLICIES, Policies
from dyla import verification


def test_defaults_are_the_literals_the_refactor_replaced():
    """If one of these changes, it is a policy change — it must show up here,
    in the write-up, and in regenerated run artifacts, not silently."""
    policy = Policies()
    assert policy.max_subqueries == 4
    assert policy.search_limit == 5
    assert policy.evidence_limit == 8
    assert policy.min_evidence == 1
    assert policy.reuse_enabled is True
    assert policy.reuse_min_sources == 2
    assert policy.reuse_min_score == 0.0
    assert policy.memory_search_limit == 10
    assert policy.rejected_claim_overlap == 0.8
    assert policy.match_tolerance == 0.01
    assert policy.conflict_tolerance == 0.05
    assert policy.topicality_floor == 0.20
    assert policy.conflict_context_floor == 0.34
    assert policy.lexical_support_floor == 0.70
    assert policy.lexical_weight == 0.3


def test_verification_and_local_vector_read_their_values_from_policies():
    """The modules' public constants are aliases, not independent copies."""
    assert verification.MATCH_TOLERANCE == DEFAULT_POLICIES.match_tolerance
    assert verification.CONFLICT_TOLERANCE == DEFAULT_POLICIES.conflict_tolerance
    assert verification.TOPICALITY_FLOOR == DEFAULT_POLICIES.topicality_floor
    assert verification.CONFLICT_CONTEXT_FLOOR == DEFAULT_POLICIES.conflict_context_floor
    assert verification.LEXICAL_SUPPORT_FLOOR == DEFAULT_POLICIES.lexical_support_floor
    assert _LEXICAL_WEIGHT == DEFAULT_POLICIES.lexical_weight


def _agent(**kwargs) -> AnalystAgent:
    return AnalystAgent(
        model=object(), resolver=object(), memory=object(),
        searcher=object(), fetcher=object(), index=object(), embedder=object(),
        **kwargs,
    )


def test_agent_defaults_come_from_the_policy_object():
    agent = _agent()
    assert agent.policies is DEFAULT_POLICIES
    assert agent.search_limit == DEFAULT_POLICIES.search_limit
    assert agent.evidence_limit == DEFAULT_POLICIES.evidence_limit
    assert agent.reuse_enabled == DEFAULT_POLICIES.reuse_enabled
    assert agent.reuse_min_sources == DEFAULT_POLICIES.reuse_min_sources
    assert agent.reuse_min_score == DEFAULT_POLICIES.reuse_min_score
    assert agent.min_evidence == DEFAULT_POLICIES.min_evidence
    assert agent.planner.max_subqueries == DEFAULT_POLICIES.max_subqueries


def test_a_custom_policy_flows_through_without_touching_the_default():
    policy = Policies(reuse_min_sources=3, search_limit=7, min_evidence=2)
    agent = _agent(policies=policy)
    assert agent.policies is policy
    assert agent.reuse_min_sources == 3
    assert agent.search_limit == 7
    assert agent.min_evidence == 2
    # Unspecified knobs still come from the same instance.
    assert agent.evidence_limit == DEFAULT_POLICIES.evidence_limit
    # And the shared default is untouched.
    assert DEFAULT_POLICIES.reuse_min_sources == 2


def test_explicit_kwargs_override_the_policy_per_knob():
    policy = Policies(reuse_min_sources=3, search_limit=7)
    agent = _agent(policies=policy, reuse_min_sources=1)
    assert agent.reuse_min_sources == 1
    assert agent.search_limit == 7, "one override must not turn off the policy for other knobs"


def test_an_explicit_max_subqueries_still_reaches_the_planner():
    agent = _agent(max_subqueries=6)
    assert agent.planner.max_subqueries == 6
    assert _agent().planner.max_subqueries == DEFAULT_POLICIES.max_subqueries


def test_rejected_claim_overlap_default_is_the_policy_value():
    # This pair shares exactly 4 of 5 content words (0.8): "fiscal" became
    # "FY2024", which is a single token, and the numbers are verified separately
    # as numeric facts, not topic words. At the policy threshold it is caught;
    # a stricter one would let the restatement through.
    prior = "Infosys reported revenue of 1,53,670 crore in fiscal 2024"
    restatement = "Infosys reported revenue of 1,53,670 crore in FY2024"
    assert _restates_rejected_claim(restatement, [prior]) is True
    assert _restates_rejected_claim(
        restatement, [prior], threshold=DEFAULT_POLICIES.rejected_claim_overlap + 0.01
    ) is False


def test_policy_validation_rejects_structurally_broken_thresholds():
    import pytest

    with pytest.raises(ValueError, match="strictly below"):
        Policies(match_tolerance=0.05, conflict_tolerance=0.01)
    with pytest.raises(ValueError, match="max_subqueries"):
        Policies(max_subqueries=0)
    with pytest.raises(ValueError, match="reuse_min_sources"):
        Policies(reuse_min_sources=0)
    with pytest.raises(ValueError, match="rejected_claim_overlap"):
        Policies(rejected_claim_overlap=1.5)
    with pytest.raises(ValueError, match="topicality_floor"):
        Policies(topicality_floor=-0.1)
    with pytest.raises(ValueError, match="lexical_weight"):
        Policies(lexical_weight=2.0)
