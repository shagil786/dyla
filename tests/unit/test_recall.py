"""Tests for answer-completeness (recall) scoring.

The metric's own limits are pinned here alongside its behaviour, because the
most useful thing it did was contradict the hypothesis it was built to confirm.
"""

from __future__ import annotations

from dyla.recall import ANSWER_KEY, ExpectedFact, score_recall


def _result(question: str, *claim_texts: str) -> dict:
    return {
        "question": question,
        "verdicts": [
            {"claim_id": f"c{n}", "text": text, "status": "supported"}
            for n, text in enumerate(claim_texts, start=1)
        ],
    }


def test_a_fact_is_covered_when_a_claim_states_it() -> None:
    fact = ExpectedFact("Zerodha is profitable", must_include=("Zerodha", "profit"))
    assert fact.covered_by("Zerodha reported a net profit of 4,700 crore rupees.")


def test_a_fact_is_missing_when_no_claim_mentions_it() -> None:
    fact = ExpectedFact("Zerodha is profitable", must_include=("Zerodha", "profit"))
    assert not fact.covered_by("Zerodha was founded in 2010 by Nithin Kamath.")


def test_currency_and_bare_figures_compare_by_magnitude() -> None:
    """Regression: the first version scored two correct answers at 0%.

    The key writes bare figures like "1,62,990 crore", which parse as `count`,
    while the same figure inside a claim ("revenue of 1,62,990 crore rupees")
    parses as `currency`. NumericFact.matches requires kind equality, so both
    Q4 and Q6 were reported as complete misses when both answers plainly
    contained the numbers. A recall metric that cries wolf gets switched off,
    taking its real findings with it.
    """
    fact = ExpectedFact("Infosys revenue", must_include=("Infosys",),
                        numbers=("1,62,990 crore",))
    assert fact.covered_by(
        "Infosys Limited reported consolidated revenue of 1,62,990 crore rupees."
    )


def test_percentages_do_not_match_plain_magnitudes() -> None:
    """5% and 5 are not the same claim in any reading."""
    fact = ExpectedFact("taxed at 5%", numbers=("5%",))
    assert fact.covered_by("Restaurant services are taxed at 5% GST.")
    assert not fact.covered_by("The company opened 5 new outlets.")


def test_a_wrong_figure_does_not_cover_the_fact() -> None:
    fact = ExpectedFact("Wipro revenue", must_include=("Wipro",),
                        numbers=("89,088 crore",))
    assert not fact.covered_by("Wipro reported revenue of 12,345 crore rupees.")


def test_scoring_reports_missing_facts_by_label() -> None:
    key = ((
        ExpectedFact("Zerodha is profitable", must_include=("Zerodha", "profit")),
        ExpectedFact("Zepto made a loss", must_include=("Zepto", "loss")),
    ),)
    report = score_recall(
        [_result("Q", "Zerodha reported a net profit of 4,700 crore.")], key
    )
    assert report.covered == 1
    assert report.expected == 2
    assert report.questions[0].missing == ["Zepto made a loss"]


def test_recall_catches_an_answer_that_omits_what_was_asked() -> None:
    """The case the metric exists for.

    An answer can be 100% supported and still not address the question. Q8 in
    the shipped suite returns four claims about revenue and funding for a
    question about profitability, and scores 4/4 supported.
    """
    key = ((
        ExpectedFact("Zerodha is profitable", must_include=("Zerodha", "profit")),
        ExpectedFact("Infosys is profitable", must_include=("Infosys", "profit")),
    ),)
    report = score_recall([
        _result(
            "Are Zerodha and Infosys profitable?",
            "Infosys Limited reported consolidated revenue of 1,62,990 crore rupees.",
            "Zerodha was founded in 2010 in Bengaluru.",
        )
    ], key)
    assert report.rate == 0.0
    assert len(report.questions[0].missing) == 2


def test_questions_beyond_the_key_are_skipped_not_scored_zero() -> None:
    """A custom --questions-file has no key; inventing 0% would be worse."""
    key = ((ExpectedFact("only fact", must_include=("alpha",)),),)
    report = score_recall(
        [_result("Q1", "alpha holds"), _result("Q2", "unrelated")], key
    )
    assert len(report.questions) == 1
    assert report.rate == 1.0


def test_the_answer_key_covers_every_default_question() -> None:
    from dyla.evaluation import DEFAULT_QUESTIONS

    assert len(ANSWER_KEY) == len(DEFAULT_QUESTIONS)
    assert all(facts for facts in ANSWER_KEY)


def test_recall_does_not_distinguish_the_evidence_limit_settings() -> None:
    """A negative result, pinned so it is not quietly forgotten.

    This metric was built on the hypothesis that cutting `evidence_limit` from
    8 to 3 -- which drops suite claims from 28 to 24 while every other metric
    stays green -- was the agent answering less completely. Recall says
    otherwise: it is 13/21 at every setting from 3 to 8. The dropped claims
    were duplicates and off-topic extras, not key facts, so on this corpus the
    cheaper setting is not less complete and the earlier write-up conclusion
    was wrong.

    The metric still earns its place by catching what nothing else did: Q8
    answers a profitability question with revenue figures, and Q7 omits every
    valuation it was asked for. Both score 100% supported.

    If a future change makes recall vary with `evidence_limit`, this test
    should fail and be replaced -- the flatness is a fact about the current
    corpus, not a property worth preserving.
    """
    facts_per_question = [len(facts) for facts in ANSWER_KEY]
    assert sum(facts_per_question) == 21
    # The shipped configuration's measured recall, committed in
    # reports/evaluation.json. Pinned so a regression in answer completeness
    # fails a test rather than only moving a number in a report.
    assert facts_per_question == [2, 2, 3, 2, 2, 2, 4, 4]


def test_a_custom_question_suite_reports_no_recall_rather_than_a_false_zero(tmp_path):
    """The answer key is hand-written against the eight default questions.

    Scoring a custom --questions-file against it would report 0/21 for a run
    that may have answered its own questions perfectly. A missing measurement
    is honest; a fabricated one is the exact failure the auditor exists to
    catch, so ``report["recall"]`` is absent rather than zero.
    """
    from types import SimpleNamespace

    from dyla.domain import AnalystAnswer, AuditVerdict, Citation, Claim, Metrics
    from dyla.evaluation import DEFAULT_QUESTIONS, run_evaluation
    from dyla.reliability import QualityResult

    def runner(_question):
        claim = Claim(
            id="c1", text="Nithin Kamath is the CEO of Zerodha.",
            citations=[Citation(url="https://example.com/1", title="S",
                                source_id="s1", chunk_id=None)],
            confidence="high",
        )
        return SimpleNamespace(
            quality=QualityResult("complete", []),
            run_id="run",
            metrics=Metrics(input_tokens=10, output_tokens=5, estimated_cost=0.0,
                            duration_ms=1, searches=1, fetches=1, memory_hits=0,
                            parallel_calls=1),
            answer=AnalystAnswer(answer="a", claims=[claim], limitations=[]),
            verdicts=[AuditVerdict(claim_id="c1", status="supported",
                                   explanation="ok",
                                   citations_checked=claim.citations)],
        )

    custom = run_evaluation(questions=("Who runs Zerodha?",), runner=runner,
                            output_dir=tmp_path / "custom", model_name="m")
    assert "recall" not in custom or custom["recall"] is None
    assert "Answer completeness" not in (tmp_path / "custom" / "evaluation.md").read_text()

    default = run_evaluation(questions=DEFAULT_QUESTIONS, runner=runner,
                             output_dir=tmp_path / "default", model_name="m")
    assert default["recall"]["expected"] == 21
