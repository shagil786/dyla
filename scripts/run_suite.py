#!/usr/bin/env python
"""Run the eight-question suite end to end and write logs plus reports.

Default is the offline recorded-fixture harness, which needs no API keys and is
reproducible. Pass --live to use the configured providers from .env instead.

    python scripts/run_suite.py                # offline, deterministic
    python scripts/run_suite.py --live         # real web + model
    python scripts/run_suite.py --fresh        # discard prior memory first

The suite is ordered so later questions reuse entities from earlier ones, which
is what makes the cost trend meaningful; running it against a database that
already holds the answers would measure caching, not transfer. --fresh is the
default for that reason.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dyla.analyst import AnalystAgent  # noqa: E402
from dyla.auditor import AuditorAgent  # noqa: E402
from dyla.entities import EntityResolver  # noqa: E402
from dyla.evaluation import DEFAULT_QUESTIONS, run_evaluation  # noqa: E402
from dyla.findings import (  # noqa: E402
    build_findings_markdown, run_seeded_defect_audit, summarise_verdicts,
)
from dyla.local_vector import LocalVectorStore  # noqa: E402
from dyla.memory import MemoryStore  # noqa: E402
from dyla.offline import OfflineEmbedder, OfflineModel, OfflineResearchProvider  # noqa: E402
from dyla.orchestrator import RunOrchestrator  # noqa: E402
from dyla.tracing import TraceWriter  # noqa: E402


def build_offline(root: Path, reuse: bool = True):
    memory = MemoryStore(root / "dyla.db")
    memory.initialize()
    provider = OfflineResearchProvider()
    embedder = OfflineEmbedder()
    index = LocalVectorStore()
    model = OfflineModel()
    writer = TraceWriter(root=root)
    analyst = AnalystAgent(
        model=model, resolver=EntityResolver(memory), memory=memory,
        searcher=provider, fetcher=provider, index=index, embedder=embedder,
        trace_writer=writer, reuse_enabled=reuse,
    )
    orchestrator = RunOrchestrator(
        analyst=analyst,
        auditor=AuditorAgent(fetcher=provider, memory=memory, trace_writer=writer,
                             retries=1, timeout_seconds=10.0),
        memory=memory, trace_writer=writer,
    )
    return orchestrator, provider, model


def seed_entities(memory: MemoryStore) -> None:
    """Register the entities the suite reuses.

    Entity resolution is deliberately deterministic and does not invent entities
    from free text, so without a seed the resolver returns "unknown" for
    everything and memory reuse can never engage. Seeding is what a real
    deployment would accumulate over time; doing it up front keeps the harness
    honest about what it is measuring rather than silently measuring nothing.
    """
    for name in ("Zerodha", "Infosys", "Wipro", "Zepto"):
        memory.upsert_entity(name, "company")


def slugify(text: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return cleaned[:limit].rstrip("-")


def archive_logs(root: Path, rows: list[dict], label: str) -> Path:
    """Copy the raw JSONL traces somewhere a human can find them.

    Runs are keyed by an opaque run_id, which is right for the machine and
    useless for a reviewer told to read the logs for question 5. The archive is
    a rename, not a rewrite: the JSONL is copied byte for byte so nothing is
    editorialised out of the record.
    """
    destination = root / "runs" / label
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    index = []
    for number, row in enumerate(rows, start=1):
        source = root / "logs" / f"{row['run_id']}.jsonl"
        name = f"q{number:02d}-{slugify(row['question'])}.jsonl"
        if source.exists():
            shutil.copyfile(source, destination / name)
        index.append({"number": number, "log": name, **row})
    (destination / "index.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )
    return destination




def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="use configured providers instead of fixtures")
    parser.add_argument("--no-reuse", action="store_true", help="disable memory-first retrieval (baseline)")
    parser.add_argument("--fresh", action="store_true", default=True, help="clear prior memory and logs")
    parser.add_argument("--keep", dest="fresh", action="store_false", help="keep prior memory")
    parser.add_argument("--out", default="reports", help="report directory")
    args = parser.parse_args()

    root = ROOT
    if args.fresh:
        for path in (root / "dyla.db", root / "logs"):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

    started = time.monotonic()
    if args.live:
        from dyla.cli import _build_orchestrator
        from dyla.config import load_settings

        settings = load_settings()
        orchestrator = _build_orchestrator(settings)
        model_name = settings.model_name
        provider = None
    else:
        orchestrator, provider, model = build_offline(root, reuse=not args.no_reuse)
        seed_entities(orchestrator.memory)
        model_name = "offline-extractive"

    per_question: list[dict] = []
    answers: list = []

    def runner(question: str):
        before_searches = len(provider.searches) if provider else 0
        before_fetches = len(provider.fetches) if provider else 0
        question_started = time.monotonic()
        result = asyncio.run(orchestrator.ask(question))
        answers.append(result.answer)
        per_question.append({
            "question": question,
            "run_id": result.run_id,
            "wall_seconds": round(time.monotonic() - question_started, 3),
            "web_searches": (len(provider.searches) - before_searches) if provider else None,
            "web_fetches": (len(provider.fetches) - before_fetches) if provider else None,
            "searches_skipped": orchestrator.analyst.metrics.get("searches_skipped"),
            "status": result.quality.status,
        })
        return result

    report = run_evaluation(
        questions=DEFAULT_QUESTIONS, runner=runner,
        output_dir=root / args.out, model_name=model_name,
    )

    label = "no-reuse" if args.no_reuse else "reuse"
    archive = archive_logs(root, per_question, label)

    # Probes audit read-only: the auditor still fetches sources and compares
    # against live memory, but planted lies must not be persisted -- a probe
    # that saves would leave fabricated claims in dyla.db for the next run.
    defects = run_seeded_defect_audit(
        answers=answers,
        audit=lambda answer, run_id: orchestrator.auditor.run(answer, run_id, persist=False),
    )
    findings = build_findings_markdown(
        summary=summarise_verdicts(report["results"]), defects=defects,
        mode=f"{'live' if args.live else 'offline-fixtures'} / reuse={not args.no_reuse}",
    )
    findings_path = root / args.out / (
        "auditor-findings.md" if not args.no_reuse else "auditor-findings-no-reuse.md"
    )
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    findings_path.write_text(findings, encoding="utf-8")

    elapsed = time.monotonic() - started
    summary = {
        "mode": "live" if args.live else "offline-fixtures",
        "reuse_enabled": not args.no_reuse,
        "model": model_name,
        "total_wall_seconds": round(elapsed, 2),
        "questions": per_question,
        "totals": report["cost_report"]["totals"],
        "pricing": report["cost_report"]["pricing"],
        "auditor": {
            "seeded_defects_planted": defects.total,
            "seeded_defects_caught": defects.caught,
            "by_class": {k: {"caught": c, "planted": t} for k, (c, t) in defects.by_class().items()},
        },
    }
    out = root / args.out / ("run-summary-no-reuse.json" if args.no_reuse else "run-summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"mode={summary['mode']} reuse={summary['reuse_enabled']} "
          f"passed={report['passed']}/{report['total']} in {elapsed:.1f}s")
    for row in per_question:
        print(f"  {row['status']:<11} {row['wall_seconds']:>6.2f}s  "
              f"search={row['web_searches']} fetch={row['web_fetches']}  {row['question'][:60]}")
    print(f"seeded-defect audit: {defects.caught}/{defects.total} caught")
    print(f"wrote {out}")
    print(f"wrote {findings_path}")
    print(f"archived logs to {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
