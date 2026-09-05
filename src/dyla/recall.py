"""Answer-completeness scoring: what the agent *failed to say*.

Why this exists
---------------
Every other quality number in this project is precision-shaped. The quality
gate asks whether each asserted claim is supported; the seeded-defect audit
asks whether planted lies are caught. Both grade the claims that were made.
Neither asks the complementary question: **of the things the corpus supports
and the question asked for, how many came back?**

That blind spot is not theoretical. It was found by sweeping ``evidence_limit``
down from 8 to 3, which cut Q5-Q8 tokens by 51.2% -- clearing the brief's
"halve the cost" bar -- while every reported metric stayed green: 8/8 questions
complete, 20/20 seeded defects caught, 100% of claims supported. The only thing
that changed was that 28 claims became 24. The agent had started answering less
thoroughly and the scoreboard could not see it.

Worse, when the key below was first run against the *shipped* configuration it
showed that Q8 -- "state whether Zerodha, Infosys, Wipro and Zepto are
profitable" -- returned four claims about revenue and funding and **not one
about profitability**, while scoring a perfect 4/4 supported. A 100% support
rate is trivially reachable by answering a question other than the one asked.

So this module scores recall against a hand-written key: for each question, the
facts a complete answer must contain, each with the corpus text that supports
it. A fact counts as covered when some asserted claim carries its required
content.

What this is and is not
-----------------------
It is a **fixture-corpus answer key**, valid only for the eight questions in
``DEFAULT_QUESTIONS`` run against ``dyla.offline.CORPUS``. It is hand-written by
me, which means it encodes my judgement of what each question demands, and a
reviewer is entitled to disagree with any individual entry. It does not
generalise to live results, where "what the web supports" is not enumerable.

That limit is worth accepting rather than designing around. The alternative --
inferring expected facts from the retrieved evidence at run time -- grades the
agent against whatever it happened to retrieve, which is precisely the circular
measurement that let an answer omitting all four profitability facts score
100%. A key that is fixed, external and arguable is weaker in scope and much
stronger in what it can actually catch.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .verification import content_words, extract_numbers


def _same_magnitude(wanted: Any, candidate: Any) -> bool:
    """Compare two numbers by value, ignoring the currency/count distinction.

    ``NumericFact.matches`` requires ``kind`` equality, which is right for
    verification -- "5 crore rupees" and "5 crore shares" are different claims.
    It is wrong here. The key writes bare figures like ``"1,62,990 crore"``
    with no currency marker, so they parse as ``count`` while the same figure
    inside a claim ("revenue of 1,62,990 crore rupees") parses as ``currency``.
    Requiring kind equality scored Q4 and Q6 at 0% when both answers plainly
    contained the figures, which is a false alarm -- and a recall metric that
    cries wolf gets switched off, taking the real findings with it.

    Percentages stay distinct from plain magnitudes: 5% and 5 are not the same
    claim in any reading.
    """
    if (wanted.kind == "percent") != (candidate.kind == "percent"):
        return False
    return wanted.matches(candidate) or wanted.value == candidate.value


def _stem(word: str) -> str:
    """Suffix strip shared with the offline model's selector.

    Kept as a local four-line function rather than imported from
    ``dyla.offline``: the metric must not depend on the component it grades, or
    a change to the model's notion of a word match would silently move the
    score it is being measured against.
    """
    word = word.removesuffix("'s").removesuffix("s'")
    for suffix in ("ability", "ations", "ation", "able", "ings", "ing", "ies",
                   "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


@dataclass(frozen=True)
class ExpectedFact:
    """One thing a complete answer to a question has to contain.

    ``must_include`` are content words that must all appear in a single claim.
    ``numbers`` are figures that must appear, compared numerically rather than
    as strings so "1,62,990 crore" and "162990 crore" match. ``label`` is what
    gets printed when the fact is missing.
    """

    label: str
    must_include: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()

    def covered_by(self, claim_text: str) -> bool:
        # Stems, not exact words. ``must_include=("hotel",)`` failed to match a
        # claim saying "Restaurants located within hotels ... are taxed at 18%",
        # so Q1 was reported as missing a fact the answer actually contained --
        # the metric's own false positive, found while fixing the real ones it
        # had exposed. A recall number that cries wolf gets switched off, taking
        # its true findings with it, so the matcher is deliberately forgiving on
        # morphology while staying strict on figures.
        words = {_stem(word) for word in content_words(claim_text)}
        for term in self.must_include:
            if not {_stem(word) for word in content_words(term)} <= words:
                return False
        if self.numbers:
            claim_values = extract_numbers(claim_text)
            for raw in self.numbers:
                wanted = extract_numbers(raw)
                if not wanted:
                    continue
                if not any(_same_magnitude(wanted[0], candidate) for candidate in claim_values):
                    return False
        return True


# The key. One entry per question in DEFAULT_QUESTIONS, same order.
#
# Entries are deliberately conservative: they require the *core* facts a
# question asks for, not every true statement the corpus contains. Q3 asks for
# three exporters, so three names are required; it also asks for a source each,
# but citation presence is already checked by the auditor and is not restated
# here.
ANSWER_KEY: tuple[tuple[ExpectedFact, ...], ...] = (
    # Q1 - GST on restaurant services.
    (
        ExpectedFact("standalone restaurants are taxed at 5%",
                     must_include=("restaurant",), numbers=("5%",)),
        ExpectedFact("restaurants in high-tariff hotels are taxed at 18%",
                     must_include=("hotel",), numbers=("18%",)),
    ),
    # Q2 - Zerodha CEO and year.
    (
        ExpectedFact("Nithin Kamath is the CEO of Zerodha",
                     must_include=("Kamath", "Zerodha", "chief executive")),
        ExpectedFact("he has held the role since 2010", numbers=("2010",)),
    ),
    # Q3 - three largest Bengaluru software exporters.
    (
        ExpectedFact("Infosys is named", must_include=("Infosys",)),
        ExpectedFact("Wipro is named", must_include=("Wipro",)),
        ExpectedFact("Mphasis is named", must_include=("Mphasis",)),
    ),
    # Q4 - quick-commerce rounds above $100M in 2025.
    (
        ExpectedFact("Zepto raised 350 million led by General Catalyst",
                     must_include=("Zepto", "General Catalyst"), numbers=("350 million",)),
        ExpectedFact("Swiggy Instamart's parent raised 200 million led by Prosus",
                     must_include=("Prosus",), numbers=("200 million",)),
    ),
    # Q5 - Zerodha CTO and academic background.
    (
        ExpectedFact("Kailash Nadh is the CTO of Zerodha",
                     must_include=("Nadh", "Zerodha", "chief technology")),
        ExpectedFact("he holds a PhD in computer science / AI",
                     must_include=("phd",)),
    ),
    # Q6 - Infosys vs Wipro revenue, and which is larger.
    (
        ExpectedFact("Infosys revenue of 1,62,990 crore",
                     must_include=("Infosys",), numbers=("1,62,990 crore",)),
        ExpectedFact("Wipro revenue of 89,088 crore",
                     must_include=("Wipro",), numbers=("89,088 crore",)),
    ),
    # Q7 - Zepto valuation trajectory and who led the latest round.
    (
        ExpectedFact("valued at 1.4 billion in 2023", numbers=("1.4 billion",)),
        ExpectedFact("valued at 3.6 billion in 2024", numbers=("3.6 billion",)),
        ExpectedFact("valued at 5 billion in the latest round", numbers=("5 billion",)),
        ExpectedFact("the latest round was led by General Catalyst",
                     must_include=("General Catalyst",)),
    ),
    # Q8 - profitability of all four companies.
    (
        ExpectedFact("Zerodha is profitable",
                     must_include=("Zerodha", "profit")),
        ExpectedFact("Infosys is profitable",
                     must_include=("Infosys", "profit")),
        ExpectedFact("Wipro is profitable",
                     must_include=("Wipro", "profit")),
        ExpectedFact("Zepto is not profitable / made a loss",
                     must_include=("Zepto", "loss")),
    ),
)


@dataclass
class QuestionRecall:
    """Recall for one question."""

    number: int
    question: str
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def expected(self) -> int:
        return len(self.covered) + len(self.missing)

    @property
    def rate(self) -> float:
        return len(self.covered) / self.expected if self.expected else 1.0


@dataclass
class RecallReport:
    """Recall across the whole suite."""

    questions: list[QuestionRecall] = field(default_factory=list)

    @property
    def covered(self) -> int:
        return sum(len(q.covered) for q in self.questions)

    @property
    def expected(self) -> int:
        return sum(q.expected for q in self.questions)

    @property
    def rate(self) -> float:
        return self.covered / self.expected if self.expected else 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "covered": self.covered,
            "expected": self.expected,
            "rate": round(self.rate, 4),
            "questions": [
                {
                    "number": q.number,
                    "question": q.question,
                    "covered": len(q.covered),
                    "expected": q.expected,
                    "rate": round(q.rate, 4),
                    "missing": list(q.missing),
                }
                for q in self.questions
            ],
        }


def _claim_texts(result: dict[str, Any]) -> list[str]:
    return [str(v.get("text") or "") for v in (result.get("verdicts") or [])]


def score_recall(
    results: Sequence[dict[str, Any]],
    key: Sequence[Sequence[ExpectedFact]] = ANSWER_KEY,
) -> RecallReport:
    """Score how much of each question's expected content the answer contained.

    Questions beyond the key's length are skipped rather than scored zero: a
    custom suite run through ``--questions-file`` has no key, and inventing a
    0% for it would be worse than reporting nothing.
    """
    report = RecallReport()
    for index, result in enumerate(results):
        if index >= len(key):
            break
        facts = key[index]
        if not facts:
            continue
        claims = _claim_texts(result)
        entry = QuestionRecall(number=index + 1, question=str(result.get("question", "")))
        for fact in facts:
            if any(fact.covered_by(text) for text in claims):
                entry.covered.append(fact.label)
            else:
                entry.missing.append(fact.label)
        report.questions.append(entry)
    return report


def render_recall_markdown(report: RecallReport) -> list[str]:
    """Markdown for the evaluation report.

    Missing facts are listed explicitly. A recall score with no list of what was
    missed is a number nobody can act on, and the list is the part that made
    the Q8 profitability gap obvious.
    """
    if not report.questions:
        return []
    lines = [
        "## Answer completeness (recall)",
        "",
        "Every other quality number here grades the claims that *were* made. This",
        "one grades what was left out: for each question, the facts the fixture",
        "corpus supports and the question asks for, scored against what the answer",
        "actually asserted. See `src/dyla/recall.py` for the key and its limits.",
        "",
        "| # | Question | Covered | Expected | Recall | Missing |",
        "|---|---|---|---|---|---|",
    ]
    for q in report.questions:
        missing = "; ".join(q.missing) if q.missing else "—"
        question = str(q.question).replace("|", "\\|")
        lines.append(
            f"| {q.number} | {question} | {len(q.covered)} | {q.expected} "
            f"| {q.rate:.0%} | {missing} |"
        )
    lines.append(
        f"| | **Total** | **{report.covered}** | **{report.expected}** "
        f"| **{report.rate:.0%}** | |"
    )
    return lines
