"""Offline-friendly question-suite evaluation and report generation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_QUESTIONS = (
    "What evidence supports the answer?",
    "Which sources provide independent support?",
    "What are the important limitations?",
    "Which claims remain uncertain?",
    "What changed in the relevant period?",
    "How do the retrieved sources compare?",
    "What facts can be directly cited?",
    "Is there sufficient evidence for a reliable answer?",
)


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
    report: dict[str, Any] = {
        "total": len(results), "passed": passed, "failed": len(results) - passed,
        "results": results,
    }
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "evaluation.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    lines = ["# Evaluation", "", f"- Total: {report['total']}", f"- Passed: {report['passed']}", f"- Failed: {report['failed']}", "", "## Questions", ""]
    for item in results:
        lines.append(f"- **{item['status']}** — {item['question']}")
    (directory / "evaluation.md").write_text("\n".join(lines) + "\n")
    return report
