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

    def runner(question: str):
        before_searches = len(provider.searches) if provider else 0
        before_fetches = len(provider.fetches) if provider else 0
        question_started = time.monotonic()
        result = asyncio.run(orchestrator.ask(question))
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

    elapsed = time.monotonic() - started
    summary = {
        "mode": "live" if args.live else "offline-fixtures",
        "reuse_enabled": not args.no_reuse,
        "model": model_name,
        "total_wall_seconds": round(elapsed, 2),
        "questions": per_question,
        "totals": report["cost_report"]["totals"],
        "pricing": report["cost_report"]["pricing"],
    }
    out = root / args.out / ("run-summary-no-reuse.json" if args.no_reuse else "run-summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"mode={summary['mode']} reuse={summary['reuse_enabled']} "
          f"passed={report['passed']}/{report['total']} in {elapsed:.1f}s")
    for row in per_question:
        print(f"  {row['status']:<11} {row['wall_seconds']:>6.2f}s  "
              f"search={row['web_searches']} fetch={row['web_fetches']}  {row['question'][:60]}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
