"""Tests for the evaluation question suite and its cost report."""

import json
from pathlib import Path
from types import SimpleNamespace

from dyla.domain import Metrics
from dyla.evaluation import DEFAULT_QUESTIONS, run_evaluation
from dyla.reliability import QualityResult


def _stub_result(question: str, metrics: Metrics) -> SimpleNamespace:
    return SimpleNamespace(
        quality=QualityResult("complete", []),
        run_id=question,
        metrics=metrics,
    )


def test_default_questions_are_exactly_eight_unique_research_questions():
    assert isinstance(DEFAULT_QUESTIONS, tuple)
    assert len(DEFAULT_QUESTIONS) == 8
    assert all(isinstance(question, str) and question.strip() for question in DEFAULT_QUESTIONS)
    assert len(set(DEFAULT_QUESTIONS)) == 8


def test_default_questions_reuse_entities_from_earlier_questions():
    for entity in ("Zerodha", "Infosys", "Wipro", "Zepto"):
        first = next(index for index, question in enumerate(DEFAULT_QUESTIONS) if entity in question)
        assert any(entity in question for question in DEFAULT_QUESTIONS[first + 1:]), entity


def test_run_evaluation_reports_per_question_costs_totals_and_trend(tmp_path):
    metrics_by_question = {
        "first question": Metrics(
            input_tokens=100, output_tokens=50, estimated_cost=0.5, duration_ms=1000,
            searches=2, fetches=1, memory_hits=0, parallel_calls=1,
        ),
        "second question": Metrics(
            input_tokens=80, output_tokens=60, estimated_cost=0.25, duration_ms=900,
            searches=1, fetches=1, memory_hits=3, parallel_calls=2,
        ),
    }

    def runner(question: str) -> SimpleNamespace:
        return _stub_result(question, metrics_by_question[question])

    report = run_evaluation(
        questions=("first question", "second question"), runner=runner, output_dir=tmp_path,
    )

    cost = report["cost_report"]
    assert cost["estimated_cost_unit"] == "adapter units"
    assert [row["question"] for row in cost["questions"]] == ["first question", "second question"]
    assert [row["status"] for row in cost["questions"]] == ["complete", "complete"]
    assert cost["questions"][0]["input_tokens"] == 100
    assert cost["questions"][0]["memory_hits"] == 0
    assert cost["questions"][1]["output_tokens"] == 60
    assert cost["questions"][1]["memory_hits"] == 3
    assert cost["totals"] == {
        "input_tokens": 180, "output_tokens": 110, "estimated_cost": 0.75,
        "duration_ms": 1900, "memory_hits": 3,
        "embedding_tokens": 0, "searches": 3, "fetches": 2, "searches_skipped": 0,
        # No model name is supplied here, so no price can be established. The
        # report says so rather than reporting 0, which would read as "free".
        "cost_in_rupees": None, "cost_in_usd": None,
    }
    assert cost["pricing"]["resolved"] is False
    assert "DYLA_PRICE_INPUT_PER_MTOK_USD" in cost["pricing"]["note"]

    stored = json.loads(Path(tmp_path, "evaluation.json").read_text())
    assert stored["total"] == 2
    assert stored["passed"] == 2
    assert stored["failed"] == 0
    assert stored["results"][0]["question"] == "first question"
    assert stored["cost_report"]["totals"]["input_tokens"] == 180
    assert stored["cost_report"]["estimated_cost_unit"] == "adapter units"

    markdown = Path(tmp_path, "evaluation.md").read_text()
    assert "## Cost per question" in markdown
    assert "Embed tok" in markdown and "Searches" in markdown and "Cost (rupees)" in markdown
    # Columns: # | Question | Status | input | output | embed | searches | fetches |
    # skipped | duration | rupees. Web-call counts sit alongside tokens because
    # memory reuse shows up there first.
    assert "| 1 | first question | complete | 100 | 50 | 0 | 2 | 1 | 0 | 1000 | unpriced |" in markdown
    assert "| | **Total** | | 180 | 110 | 0 | 3 | 2 | 0 | 1900 | unpriced |" in markdown
    assert "## Cost trend" in markdown
    assert "- Total tokens: 290 (input 180, output 110)" in markdown
    assert "- Total estimated_cost (adapter units): 0.75" in markdown
    assert "- Total duration: 1900 ms" in markdown
    assert "- Memory hits by question: [0, 3] (first-question baseline: 0; later questions total: 3)" in markdown


def test_run_evaluation_cost_rows_default_to_zero_without_metrics(tmp_path):
    def runner(question: str):
        if question == "boom":
            raise RuntimeError("no network")
        return {"plain": "result"}

    report = run_evaluation(questions=("boom", "plain"), runner=runner, output_dir=tmp_path)

    rows = report["cost_report"]["questions"]
    assert rows[0]["status"] == "failed"
    assert rows[0]["input_tokens"] == 0
    assert rows[0]["estimated_cost"] == 0
    assert rows[1]["status"] == "passed"
    assert rows[1]["memory_hits"] == 0
    assert report["cost_report"]["totals"] == {
        "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0,
        "duration_ms": 0, "memory_hits": 0,
        "embedding_tokens": 0, "searches": 0, "fetches": 0, "searches_skipped": 0,
        "cost_in_rupees": None, "cost_in_usd": None,
    }
    assert "| | **Total** | | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unpriced |" in Path(tmp_path, "evaluation.md").read_text()


def test_every_module_imports_on_this_interpreter():
    """Regression guard for the PEP 701 f-string break.

    src/dyla/evaluation.py once used backslashes inside f-string expressions,
    which parses only on Python 3.12+ while pyproject declares >=3.11. Because
    cli.py imports evaluation, that single SyntaxError made every documented
    command unreachable and aborted pytest at collection. A passing unit test
    elsewhere could not catch it; only an explicit import sweep can.
    """
    import importlib
    import pkgutil

    import dyla

    failures = []
    for module in pkgutil.iter_modules(dyla.__path__, "dyla."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # pragma: no cover - the assert reports it
            failures.append(f"{module.name}: {type(exc).__name__}: {exc}")
    assert not failures, "modules failed to import: " + "; ".join(failures)


def test_markdown_escape_handles_pipes_without_pep701_syntax():
    from dyla.evaluation import _md_escape

    assert _md_escape("a|b") == "a\\|b"
    assert _md_escape("plain") == "plain"
    assert _md_escape(7) == "7"
