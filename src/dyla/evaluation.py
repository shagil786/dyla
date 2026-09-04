"""Offline-friendly question-suite evaluation and report generation.

DEFAULT_QUESTIONS follows the take-home brief: eight research questions of
increasing difficulty, where later questions deliberately reuse entities
introduced by earlier questions so durable memory is exercised (see the
difficulty/reuse map above the tuple).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Assignment suite: eight questions of increasing difficulty; questions after the
# first four deliberately reuse entities introduced earlier so durable memory is
# exercised (memory_hits in the cost report should be non-zero for Q5-Q8).
#   Q1 easy        - single factual lookup (India GST on restaurants); no prior entities.
#   Q2 easy        - named-entity lookup; introduces ZERODHA (reused by Q5, Q8).
#   Q3 medium      - ranked list with per-item sources; introduces INFOSYS and WIPRO (reused by Q6, Q8).
#   Q4 medium      - funding aggregation with amounts, lead investors and a dated window
#                    (calendar year 2025); introduces ZEPTO (reused by Q7, Q8).
#   Q5 medium-hard - reuses ZERODHA (Q2): engineering-leadership lookup.
#   Q6 hard        - reuses INFOSYS and WIPRO (Q3): cross-company revenue comparison.
#   Q7 hard        - reuses ZEPTO (Q4): multi-hop funding-trajectory question.
#   Q8 hardest     - reuses ZERODHA (Q2), INFOSYS and WIPRO (Q3), ZEPTO (Q4): four-way
#                    profitability synthesis with one citation per company.
DEFAULT_QUESTIONS = (
    # Q1 easy - single factual lookup; no prior entities.
    "What is the current goods and services tax (GST) rate applied to restaurant services in India?",
    # Q2 easy - named-entity lookup; introduces Zerodha.
    "Who is the current chief executive officer of Zerodha, and in which year did they take the role?",
    # Q3 medium - ranked list with per-item sources; introduces Infosys and Wipro.
    "List the three largest software services exporters by revenue that are headquartered in Bengaluru, with one source for each.",
    # Q4 medium - funding aggregation with amounts, lead investors and a dated window; introduces Zepto.
    "Which Indian quick-commerce startups raised funding rounds above 100 million dollars in 2025, and what were the amounts and lead investors?",
    # Q5 medium-hard - reuses Zerodha (Q2): engineering-leadership lookup.
    "Who is the chief technology officer of Zerodha, and what is their academic background?",
    # Q6 hard - reuses Infosys and Wipro (Q3): cross-company revenue comparison.
    "Compare the most recent full-year revenues of Infosys and Wipro in rupees, and state which company reported the larger figure.",
    # Q7 hard - reuses Zepto (Q4): multi-hop funding-trajectory question.
    "How did Zepto's valuation change across its funding rounds up to its most recent round, and who led that most recent round?",
    # Q8 hardest - reuses Zerodha (Q2), Infosys and Wipro (Q3), Zepto (Q4): four-way
    #              profitability synthesis with one citation per company.
    "State whether Zerodha, Infosys, Wipro, and Zepto are profitable according to their latest published financials, and cite one source for each.",
)

COST_FIELDS = ("input_tokens", "output_tokens", "estimated_cost", "duration_ms", "memory_hits")
ESTIMATED_COST_UNIT = "adapter units"


def _metric_value(metrics: Any, field: str) -> int | float:
    if not isinstance(metrics, dict):
        return 0
    value = metrics.get(field, 0)
    return value if isinstance(value, (int, float)) else 0


def _cost_row(item: dict[str, Any]) -> dict[str, Any]:
    metrics = item.get("metrics")
    row: dict[str, Any] = {"question": item.get("question"), "status": item.get("status")}
    row.update({field: _metric_value(metrics, field) for field in COST_FIELDS})
    return row


def _cost_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [_cost_row(item) for item in results]
    totals: dict[str, Any] = {}
    for field in COST_FIELDS:
        summed = sum(row[field] for row in rows)
        totals[field] = float(summed) if field == "estimated_cost" else int(summed)
    return {"estimated_cost_unit": ESTIMATED_COST_UNIT, "questions": rows, "totals": totals}


def _md_cost_table(cost: dict[str, Any]) -> list[str]:
    lines = [
        "## Cost per question", "",
        "| # | Question | Status | Input tokens | Output tokens | Estimated cost (adapter units) | Duration (ms) | Memory hits |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(cost["questions"], start=1):
        question = str(row["question"]).replace("|", "\\|")
        lines.append(
            f"| {index} | {question} | {row['status']} | {row['input_tokens']} | {row['output_tokens']}"
            f" | {row['estimated_cost']} | {row['duration_ms']} | {row['memory_hits']} |"
        )
    totals = cost["totals"]
    lines.append(
        f"| | **Total** | | {totals['input_tokens']} | {totals['output_tokens']}"
        f" | {totals['estimated_cost']} | {totals['duration_ms']} | {totals['memory_hits']} |"
    )
    return lines


def _md_trend(cost: dict[str, Any]) -> list[str]:
    totals = cost["totals"]
    hits = [row["memory_hits"] for row in cost["questions"]]
    baseline = hits[0] if hits else 0
    return [
        "## Cost trend", "",
        f"- Total tokens: {totals['input_tokens'] + totals['output_tokens']}"
        f" (input {totals['input_tokens']}, output {totals['output_tokens']})",
        f"- Total estimated_cost (adapter units): {totals['estimated_cost']}",
        f"- Total duration: {totals['duration_ms']} ms",
        f"- Memory hits by question: {hits}"
        f" (first-question baseline: {baseline}; later questions total: {sum(hits[1:])})",
    ]


def run_evaluation(
    *,
    questions: tuple[str, ...] = DEFAULT_QUESTIONS,
    runner: Callable[[str], Any] | None = None,
    output_dir: str | Path = "reports",
) -> dict[str, Any]:
    """Run the configured question suite and write stable JSON and Markdown reports."""
    if runner is None:
        from .cli import _build_orchestrator
        from .config import load_settings
        orchestrator = _build_orchestrator(load_settings())
        runner = lambda question: asyncio.run(orchestrator.ask(question))

    results: list[dict[str, Any]] = []
    for question in questions:
        try:
            value = runner(question)
            if hasattr(value, "quality"):
                result = {
                    "question": question,
                    "status": value.quality.status,
                    "run_id": value.run_id,
                    "metrics": value.metrics.model_dump(mode="json"),
                }
            else:
                result = {"question": question, "status": "passed", "result": value}
        except Exception as exc:
            result = {"question": question, "status": "failed", "error": str(exc)}
        results.append(result)

    passed = sum(item["status"] in {"passed", "complete"} for item in results)
    cost = _cost_report(results)
    report: dict[str, Any] = {
        "total": len(results), "passed": passed, "failed": len(results) - passed,
        "cost_report": cost, "results": results,
    }
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "evaluation.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    lines = ["# Evaluation", "", f"- Total: {report['total']}", f"- Passed: {report['passed']}", f"- Failed: {report['failed']}", "", "## Questions", ""]
    for item in results:
        lines.append(f"- **{item['status']}** — {item['question']}")
    lines.extend(["", *_md_cost_table(cost), "", *_md_trend(cost)])
    (directory / "evaluation.md").write_text("\n".join(lines) + "\n")
    return report
