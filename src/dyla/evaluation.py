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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .pricing import (
    counterfactual_model,
    price_counterfactual,
    price_run,
    resolve_pricing,
)

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

COST_FIELDS = ("input_tokens", "output_tokens", "embedding_tokens", "estimated_cost",
               "duration_ms", "memory_hits", "searches", "fetches", "searches_skipped")
ESTIMATED_COST_UNIT = "adapter units"
HISTORY_CAP = 50


def _md_escape(value: Any) -> str:
    """Escape Markdown table cell content.

    Defined as a helper rather than inlined into f-strings: a backslash inside an
    f-string expression is PEP 701 syntax and only parses on Python 3.12+, which
    silently broke every CLI entry point on the declared floor of Python 3.11.
    """
    return str(value).replace("|", "\\|")


def _metric_value(metrics: Any, field: str) -> int | float:
    if not isinstance(metrics, dict):
        return 0
    value = metrics.get(field, 0)
    return value if isinstance(value, (int, float)) else 0


def _cost_row(item: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    metrics = item.get("metrics")
    row: dict[str, Any] = {"question": item.get("question"), "status": item.get("status")}
    row.update({field: _metric_value(metrics, field) for field in COST_FIELDS})
    priced = price_run(model, int(row["input_tokens"]), int(row["output_tokens"]))
    row["cost_in_rupees"] = priced["cost_inr"]
    row["cost_in_usd"] = priced["cost_usd"]
    row["priced"] = priced["priced"]
    # Projected cost on a reference model, always computed, always labelled as a
    # projection. Kept in separate keys so a consumer can never mistake it for
    # what the run actually cost.
    projected = price_counterfactual(int(row["input_tokens"]), int(row["output_tokens"]))
    row["counterfactual_inr"] = projected["cost_inr"]
    row["counterfactual_usd"] = projected["cost_usd"]
    row["counterfactual_priced"] = projected["priced"]
    return row


def _cost_report(results: list[dict[str, Any]], model: str | None = None) -> dict[str, Any]:
    rows = [_cost_row(item, model) for item in results]
    totals: dict[str, Any] = {}
    for field in COST_FIELDS:
        summed = sum(row[field] for row in rows)
        totals[field] = float(summed) if field == "estimated_cost" else int(summed)
    priced_rows = [row for row in rows if row["priced"]]
    totals["cost_in_rupees"] = round(sum(row["cost_in_rupees"] for row in priced_rows), 6) if priced_rows else None
    totals["cost_in_usd"] = round(sum(row["cost_in_usd"] for row in priced_rows), 8) if priced_rows else None
    projected_rows = [row for row in rows if row["counterfactual_priced"]]
    totals["counterfactual_inr"] = (
        round(sum(row["counterfactual_inr"] for row in projected_rows), 6) if projected_rows else None
    )
    totals["counterfactual_usd"] = (
        round(sum(row["counterfactual_usd"] for row in projected_rows), 8) if projected_rows else None
    )
    reference = price_counterfactual(0, 0)
    pricing = resolve_pricing(model)
    return {
        "estimated_cost_unit": ESTIMATED_COST_UNIT,
        "questions": rows,
        "totals": totals,
        "pricing": {
            "model": model,
            "resolved": pricing is not None,
            "input_per_mtok_usd": pricing.input_per_mtok_usd if pricing else None,
            "output_per_mtok_usd": pricing.output_per_mtok_usd if pricing else None,
            "usd_to_inr": pricing.usd_to_inr if pricing else None,
            "rate_source": pricing.source if pricing else None,
            "note": None if pricing else price_run(model, 0, 0)["note"],
        },
        "counterfactual": {
            "model": counterfactual_model(),
            "resolved": bool(reference["priced"]),
            "input_per_mtok_usd": reference.get("input_per_mtok_usd"),
            "output_per_mtok_usd": reference.get("output_per_mtok_usd"),
            "usd_to_inr": reference.get("usd_to_inr"),
            "note": reference.get("note"),
        },
    }


def _md_cost_table(cost: dict[str, Any]) -> list[str]:
    lines = [
        "## Cost per question", "",
        "| # | Question | Status | Input tok | Output tok | Embed tok | Searches | Fetches | Skipped | Duration (ms) | Cost (rupees) | Projected ₹ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(cost["questions"], start=1):
        question = _md_escape(row["question"])
        lines.append(
            f"| {index} | {question} | {row['status']} | {row['input_tokens']} | {row['output_tokens']}"
            f" | {row['embedding_tokens']} | {row['searches']} | {row['fetches']} | {row['searches_skipped']}"
            f" | {row['duration_ms']} | {_rupees(row['cost_in_rupees'])}"
            f" | {_rupees(row.get('counterfactual_inr'))} |"
        )
    totals = cost["totals"]
    lines.append(
        f"| | **Total** | | {totals['input_tokens']} | {totals['output_tokens']}"
        f" | {totals['embedding_tokens']} | {totals['searches']} | {totals['fetches']} | {totals['searches_skipped']}"
        f" | {totals['duration_ms']} | {_rupees(totals.get('cost_in_rupees'))}"
        f" | {_rupees(totals.get('counterfactual_inr'))} |"
    )
    pricing = cost.get("pricing") or {}
    lines.append("")
    if pricing.get("resolved"):
        lines.append(
            f"Priced at ${pricing['input_per_mtok_usd']}/1M input and "
            f"${pricing['output_per_mtok_usd']}/1M output tokens for `{pricing['model']}` "
            f"({pricing['rate_source']}), converted at {pricing['usd_to_inr']} INR/USD."
        )
    else:
        lines.append(f"**Cost (rupees) is unavailable.** {pricing.get('note', '')}")

    reference = cost.get("counterfactual") or {}
    lines.append("")
    if reference.get("resolved"):
        lines.append(
            f"**Projected ₹** is not a measurement. It is what these exact token "
            f"counts would have cost on `{reference['model']}` at "
            f"${reference['input_per_mtok_usd']}/1M input and "
            f"${reference['output_per_mtok_usd']}/1M output, converted at "
            f"{reference['usd_to_inr']} INR/USD. The tokens are real; the model "
            f"that would have charged for them did not run. Override the "
            f"reference with `DYLA_COUNTERFACTUAL_MODEL`."
        )
    else:
        lines.append(f"**Projected ₹ is unavailable.** {reference.get('note', '')}")
    return lines


def _rupees(value: Any) -> str:
    """Render a rupee amount, or an explicit marker when no price is known.

    Never renders 0 for an unpriced run: a zero in a cost column reads as "this
    was free" rather than "we do not know".
    """
    if value is None:
        return "unpriced"
    return f"{value:.4f}"


def _verdict_detail(value: Any) -> list[dict[str, Any]]:
    """Per-claim verdict quality from a run result, so reports show exactly which
    claims were supported or rejected instead of only the question-level status."""
    answer = getattr(value, "answer", None)
    claims = getattr(answer, "claims", None)
    verdicts = getattr(value, "verdicts", None)
    if not claims or not verdicts:
        return []
    by_id = {verdict.claim_id: verdict for verdict in verdicts}
    detail: list[dict[str, Any]] = []
    for claim in claims:
        verdict = by_id.get(claim.id)
        if verdict is None:
            continue
        urls = [citation.url for citation in getattr(claim, "citations", [])]
        if not urls:
            urls = [citation.url for citation in getattr(verdict, "citations_checked", [])]
        detail.append({
            "claim_id": claim.id,
            "text": claim.text,
            "status": verdict.status,
            "explanation": verdict.explanation,
            "urls": urls,
        })
    return detail


def _md_verdict_detail(item: dict[str, Any], index: int) -> list[str]:
    lines = [f"### {index}. {_md_escape(item['question'])} — {item['status']}"]
    run_id = item.get("run_id")
    if run_id:
        lines.append(f"Run: `{run_id}`")
    verdicts = item.get("verdicts") or []
    if not verdicts:
        lines.append("_No claims were audited for this question._")
        return lines
    lines.extend(["", "| Claim | Verdict | Cited sources |", "|---|---|---|"])
    for verdict in verdicts:
        urls = "; ".join(url for url in verdict.get("urls", [])) or "—"
        lines.append(
            f"| {_md_escape(verdict['claim_id'])} | {verdict['status']} | {_md_escape(urls)} |"
        )
    lines.append("")
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
        *_md_counterfactual_trend(cost),
    ]


def _md_counterfactual_trend(cost: dict[str, Any]) -> list[str]:
    """The rupee trend the brief asks for, on the reference model.

    Reported separately from the token trend and named as a projection every
    time it appears. Without this the rupee half of "report your cost per
    question in tokens and rupees, and show the trend" has no answer at all
    for a run whose model has no price.
    """
    reference = cost.get("counterfactual") or {}
    rows = [row for row in cost["questions"] if row.get("counterfactual_priced")]
    if not reference.get("resolved") or not rows:
        return []
    values = [row["counterfactual_inr"] for row in rows]
    first, last = values[0], values[-1]
    delta = ((last - first) / first * 100) if first else 0.0
    peak = max(values)
    peak_index = values.index(peak) + 1
    ratio = (peak / first) if first else 0.0
    return [
        "",
        f"**Projected rupee trend on `{reference['model']}`** (a projection over "
        "real token counts, not a measured charge):",
        "",
        f"- Per question: {', '.join(f'₹{value:.4f}' for value in values)}",
        f"- Q1 ₹{first:.4f} → Q{len(values)} ₹{last:.4f} ({delta:+.1f}%)",
        f"- Most expensive: Q{peak_index} at ₹{peak:.4f} ({ratio:.2f}× Q1)",
        f"- Suite total: ₹{sum(values):.4f}",
    ]


def run_evaluation(
    *,
    questions: tuple[str, ...] = DEFAULT_QUESTIONS,
    runner: Callable[[str], Any] | None = None,
    output_dir: str | Path = "reports",
    model_name: str | None = None,
) -> dict[str, Any]:
    """Run the configured question suite and write stable JSON and Markdown reports."""
    if runner is None:
        from .cli import _build_orchestrator
        from .config import load_settings
        settings = load_settings()
        orchestrator = _build_orchestrator(settings)
        model_name = model_name or getattr(settings, "model_name", None)
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
                    "verdicts": _verdict_detail(value),
                }
            else:
                result = {"question": question, "status": "passed", "result": value, "verdicts": []}
        except Exception as exc:
            result = {"question": question, "status": "failed", "error": str(exc), "verdicts": []}
        results.append(result)

    passed = sum(item["status"] in {"passed", "complete"} for item in results)
    cost = _cost_report(results, model=model_name)
    report: dict[str, Any] = {
        "total": len(results), "passed": passed, "failed": len(results) - passed,
        "cost_report": cost, "results": results,
    }
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "evaluation.json"
    history = _load_history(json_path)
    history.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": passed,
        "total": len(results),
        "questions": [
            {
                "question": item["question"],
                "status": item["status"],
                "supported": sum(1 for verdict in item.get("verdicts") or [] if verdict["status"] == "supported"),
                "total": len(item.get("verdicts") or []),
                "run_id": item.get("run_id"),
            }
            for item in results
        ],
    })
    if len(history) > HISTORY_CAP:
        history = history[-HISTORY_CAP:]
    report["history"] = history
    (directory / "evaluation.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    lines = ["# Evaluation", "", f"- Total: {report['total']}", f"- Passed: {report['passed']}", f"- Failed: {report['failed']}", "", "## Questions", ""]
    for item in results:
        lines.append(f"- **{item['status']}** — {item['question']}")
    lines.extend(["", "## Verdict detail", ""])
    for index, item in enumerate(results, start=1):
        lines.extend(_md_verdict_detail(item, index))
    lines.extend([*_md_cost_table(cost), "", *_md_trend(cost), "", *_md_history(history)])
    (directory / "evaluation.md").write_text("\n".join(lines) + "\n")
    return report


def _load_history(path: Path) -> list[dict[str, Any]]:
    """Read the persisted run history so repeated evaluations accumulate instead of
    overwriting; a missing or malformed history file starts a fresh history."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    history = data.get("history", []) if isinstance(data, dict) else []
    return [entry for entry in history if isinstance(entry, dict)]


def _md_history(history: list[dict[str, Any]]) -> list[str]:
    if not history:
        return ["## Run history", "", "_No complete-suite runs recorded yet._"]
    lines = ["## Run history", "", f"Most recent {len(history)} full-suite runs recorded.", ""]
    lines.extend(_md_trend_table(history))
    lines.extend(["**Run details (newest first):**", ""])
    for entry in reversed(history):
        passed, total = entry.get("passed"), entry.get("total")
        summary = f"{passed}/{total} passed" if isinstance(passed, int) and isinstance(total, int) else "status unknown"
        lines.append(f"### {entry.get('timestamp', '?')} — {summary}")
        for row in entry.get("questions", []):
            counts = f" · {row['supported']}/{row['total']} claims supported" if row.get("total") else ""
            run_id = f" · `{row['run_id']}`" if row.get("run_id") else ""
            lines.append(f"- **{row.get('status', '?')}** — {row.get('question', '?')}{counts}{run_id}")
        lines.append("")
    return lines


def _short_timestamp(value: Any) -> str:
    if not value:
        return "?"
    try:
        return datetime.fromisoformat(str(value)).strftime("%m-%d %H:%M")
    except ValueError:
        return str(value)[:16]


def _trend_cell(row: dict[str, Any] | None) -> str:
    """Compact cell: '✓ 4/4' for a passed run with audited claims, '✗ 2/4' for a
    failed one, the status word when nothing was audited, or '—' when the
    question did not participate in that run."""
    if row is None:
        return "—"
    status = str(row.get("status", "?"))
    passed = status in {"complete", "passed"}
    total = row.get("total")
    supported = row.get("supported")
    if isinstance(total, int) and total > 0:
        supported = supported if isinstance(supported, int) else 0
        return f"{'✓' if passed else '✗'} {supported}/{total}"
    return "✓" if passed else status


def _md_trend_table(history: list[dict[str, Any]]) -> list[str]:
    """One row per question, one column per recorded run (oldest left), so
    supported-vs-total movement over time is visible at a glance."""
    runs: list[dict[str, Any]] = []
    questions: list[str] = []
    for entry in history:
        rows = {row.get("question"): row for row in entry.get("questions", []) if row.get("question")}
        for question in rows:
            if question not in questions:
                questions.append(question)
        runs.append(rows)
    lines = ["**Verdict trend, oldest run on the left:**", "",
             "Cell = supported/total claims audited; ✓ = passed, ✗ = not passed; — = question absent from that run.", ""]
    header = ["| # | Question | Pass rate |"]
    header.append(" | ".join(f"{_short_timestamp(entry.get('timestamp'))}" for entry in history) + " |")
    lines.append(" | ".join(header))
    lines.append("|" + "---|" * (len(history) + 3))
    for index, question in enumerate(questions, start=1):
        cells: list[str] = []
        passed_runs = total_runs = 0
        for rows in runs:
            row = rows.get(question)
            cells.append(_trend_cell(row))
            if row is not None:
                total_runs += 1
                if row.get("status") in {"complete", "passed"}:
                    passed_runs += 1
        rate = f"{passed_runs}/{total_runs}" if total_runs else "—"
        lines.append(
            f"| {index} | {_md_escape(question)} | {rate} | " + " | ".join(cells) + " |"
        )
    lines.append("")
    return lines
