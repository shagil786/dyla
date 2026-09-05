

def test_one_malformed_claim_does_not_discard_the_whole_answer():
    """Observed live: a model omitted `citations` on one claim of several.

    Pydantic rejected the entire AnalystAnswer, the adapter raised, and the
    question failed outright -- three perfectly cited claims thrown away
    because of a fourth. That is a parser failure reported as a research
    failure, and it was a large part of the live suite's 4/8.
    """
    import json

    from dyla.compatible import _parse_structured
    from dyla.domain import AnalystAnswer

    payload = {
        "answer": "Satya Nadella is the CEO of Microsoft.",
        "claims": [
            {"id": "c1", "text": "Satya Nadella is the CEO of Microsoft.",
             "citations": [{"url": "https://example.com/a", "title": "A",
                            "source_id": "s1", "chunk_id": None}],
             "confidence": "high"},
            {"id": "c2", "text": "He became CEO in 2014.", "confidence": "high"},
        ],
        "limitations": [],
    }

    answer = _parse_structured(json.dumps(payload), AnalystAnswer)
    assert [claim.id for claim in answer.claims] == ["c1", "c2"]
    assert len(answer.claims[0].citations) == 1


def test_a_claim_missing_citations_is_recovered_uncited_never_fabricated():
    """The salvage must not manufacture provenance.

    Defaulting `citations` to a plausible-looking value would parse just as
    well and be far worse: an uncited assertion would become a *valid* claim.
    Recovering it with an empty list routes it into the analyst's existing
    no_citations rejection instead.
    """
    import json

    from dyla.compatible import _parse_structured
    from dyla.domain import AnalystAnswer

    payload = {"answer": "a", "claims": [
        {"id": "c1", "text": "An uncited assertion.", "confidence": "high"}]}

    answer = _parse_structured(json.dumps(payload), AnalystAnswer)
    assert answer.claims[0].citations == []


def test_salvage_drops_claims_with_no_id_or_text_and_junk_citations():
    import json

    from dyla.compatible import _parse_structured
    from dyla.domain import AnalystAnswer

    payload = {"answer": "a", "claims": [
        {"id": "c1", "text": "Keeps this.",
         "citations": [{"url": "https://example.com/a", "title": "A",
                        "source_id": "s1", "chunk_id": None},
                       {"title": "no url"}, "not-a-dict"]},
        {"id": "", "text": "no id"},
        {"id": "c3"},
    ]}

    answer = _parse_structured(json.dumps(payload), AnalystAnswer)
    assert [claim.id for claim in answer.claims] == ["c1"]
    assert len(answer.claims[0].citations) == 1


def test_an_unsalvageable_response_still_raises():
    """A parse that recovers nothing must not return an empty answer.

    An empty AnalystAnswer would read as "the model found nothing" rather than
    "the response could not be parsed", which are different failures.
    """
    import json

    import pytest
    from pydantic import ValidationError

    from dyla.compatible import _parse_structured
    from dyla.domain import AnalystAnswer

    with pytest.raises(ValidationError):
        _parse_structured(json.dumps({"answer": "a", "claims": [{"junk": 1}]}), AnalystAnswer)


def test_salvage_does_not_preempt_the_truncation_repair():
    """Ordering regression, caught by the existing suite.

    For a response cut off mid-claim, the first JSON candidate is the raw
    truncated parse (keeping a half-written claim) and a later candidate is the
    cleanly drop-repaired version. Salvaging inline with the validation loop
    returned the former. Salvage must run only after every candidate has failed
    to validate outright.
    """
    from dyla.compatible import _parse_structured
    from dyla.domain import AnalystAnswer

    content = (
        '{"answer": "final answer", "claims": ['
        '{"id": "c1", "text": "first claim", "citations": []}, '
        '{"id": "c2", "text": "second cl' + "\n" * 10
    )

    answer = _parse_structured(content, AnalystAnswer)
    assert [claim.id for claim in answer.claims] == ["c1"]
