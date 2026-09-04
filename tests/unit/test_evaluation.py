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
    }

    stored = json.loads(Path(tmp_path, "evaluation.json").read_text())
    assert stored["total"] == 2
    assert stored["passed"] == 2
    assert stored["failed"] == 0
    assert stored["results"][0]["question"] == "first question"
    assert stored["cost_report"]["totals"]["input_tokens"] == 180
    assert stored["cost_report"]["estimated_cost_unit"] == "adapter units"

    markdown = Path(tmp_path, "evaluation.md").read_text()
    assert "## Cost per question" in markdown
    assert "Estimated cost (adapter units)" in markdown
    assert "| 1 | first question | complete | 100 | 50 | 0.5 | 1000 | 0 |" in markdown
    assert "| | **Total** | | 180 | 110 | 0.75 | 1900 | 3 |" in markdown
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
    }
    assert "| | **Total** | | 0 | 0 | 0.0 | 0 | 0 |" in Path(tmp_path, "evaluation.md").read_text()
