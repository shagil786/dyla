#!/usr/bin/env python
"""P3-3 adversarial-analyst experiment (offline, recorded fixtures).

The premise: tell the analyst an auditor will check every claim, and measure
whether citation quality improves. With OfflineModel the answer is a measured
negative result by construction: the extractive stand-in joins all messages,
recovers the Question: line and evidence blocks by marker, and ignores every
other word — so the adversarial system message cannot change a single byte of
the answer. That invariance is pinned by tests/unit/test_offline.py; this
script is the honest run-level measurement of it (two full eight-question
suites, same fresh state, outputs diffed).

    python scripts/experiment_adversarial_analyst.py          # reuse mode
    python scripts/experiment_adversarial_analyst.py --no-reuse

Real answers to P3-3 need a live model: pass --live to run both arms against
the configured providers (the offline path stays available for the pinned
invariance that tests/unit/test_offline.py asserts).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_suite import build_offline, seed_entities  # noqa: E402

from dyla.cli import _build_orchestrator  # noqa: E402
from dyla.config import load_settings  # noqa: E402
from dyla.evaluation import DEFAULT_QUESTIONS  # noqa: E402
from dyla.models import ModelRequest  # noqa: E402

ADVERSARIAL_SYSTEM = (
    "An auditor will check every claim against its cited sources before the "
    "answer ships. Claims whose citations do not genuinely support them will "
    "be rejected and made visible. Cite conservatively: prefer the source that "
    "states the fact most directly, and never pad citations."
)


class _AdversarialPromptModel:
    """Delegates to the inner model after adding the audit threat to the system message.

    Rebuilds a real ``ModelRequest`` rather than a messages-only shim, so the
    same wrapper works for the live ``compatible`` provider (which needs
    ``response_schema``/``max_tokens``/``temperature``) and the offline
    extractive model (which reads only ``messages``).
    """

    def __init__(self, inner: object) -> None:
        self.inner = inner

    def complete(self, request: object) -> object:
        messages = list(request.messages)
        system = messages[0]["content"] if messages else ""
        messages[0] = {**messages[0], "content": f"{system} {ADVERSARIAL_SYSTEM}"}
        return self.inner.complete(ModelRequest(
            messages, request.response_schema, request.max_tokens, request.temperature,
        ))


def _claim_events(trace_path) -> list[dict]:
    events = []
    path = Path(trace_path) if trace_path else None
    if path is None or not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event["event"] in ("claim_audited", "claim_rejected", "answer_synthesized", "quality_completed"):
            events.append(event)
    return events


def run_one(root: Path, adversarial: bool, reuse: bool) -> list[dict]:
    """Run the suite in a fresh scratch directory; return per-question rows."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "logs").mkdir()
    orchestrator, provider, model = build_offline(root, reuse=reuse)
    seed_entities(orchestrator.memory)
    if adversarial:
        orchestrator.analyst.model = _AdversarialPromptModel(model)

    rows = []
    for question in DEFAULT_QUESTIONS:
        result = asyncio.run(orchestrator.ask(question))
        rows.append({
            "question": question,
            "answer": result.answer.answer,
            "claims": [
                {"text": claim.text, "citations": [c.model_dump() for c in claim.citations]}
                for claim in result.answer.claims
            ],
            "events": _claim_events(root / "logs" / f"{result.run_id}.jsonl"),
        })
    return rows


def run_one_live(root: Path, adversarial: bool, reuse: bool) -> list[dict]:
    """Run the suite against the configured live providers in a scratch root.

    Memory is pointed at the scratch directory so the experiment neither
    inherits the repo database's history nor pollutes it. Nondeterminism is
    expected and is the point: the offline run could not answer whether the
    threat changes behaviour because its model ignores the system message.
    """
    if root.exists():
        shutil.rmtree(root)
    (root / "logs").mkdir(parents=True)
    settings = load_settings().model_copy(update={"memory_db_path": str(root / "dyla.db")})
    orchestrator = _build_orchestrator(settings, reuse=reuse)
    if adversarial:
        orchestrator.analyst.model = _AdversarialPromptModel(orchestrator.analyst.model)

    rows = []
    for question in DEFAULT_QUESTIONS:
        result = asyncio.run(orchestrator.ask(question))
        rows.append({
            "question": question,
            "answer": result.answer.answer,
            "claims": [
                {"text": claim.text, "citations": [c.model_dump() for c in claim.citations]}
                for claim in result.answer.claims
            ],
            "events": _claim_events(result.trace_path),
        })
    return rows


def _live_row_summary(row: dict) -> dict:
    verdicts = [e["payload"]["status"] for e in row["events"] if e["event"] == "claim_audited"]
    rejections = [e["payload"].get("reason") for e in row["events"] if e["event"] == "claim_rejected"]
    quality = [e["payload"]["status"] for e in row["events"] if e["event"] == "quality_completed"]
    return {
        "answer_chars": len(row["answer"] or ""),
        "claims": len(row["claims"]),
        "citations_per_claim": [len(c["citations"]) for c in row["claims"]],
        "verdicts": verdicts,
        "rejection_reasons": rejections,
        "quality": quality[0] if quality else None,
    }


def _strip_metrics(row: dict) -> dict:
    """Answers and verdicts only — token counts legitimately differ (the
    adversarial system message makes every prompt longer), and the point of the
    comparison is content, not cost."""
    stripped = {"answer": row["answer"], "claims": row["claims"]}
    events = []
    for event in row["events"]:
        payload = dict(event["payload"])
        for key in ("input_tokens", "output_tokens", "duration_ms", "estimated_cost", "embedding_tokens"):
            payload.pop(key, None)
        events.append({"event": event["event"], "payload": payload})
    stripped["events"] = events
    return stripped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-reuse", action="store_true", help="disable memory-first retrieval")
    parser.add_argument("--live", action="store_true", help="run both arms against the configured live providers")
    parser.add_argument("--scratch", default="/tmp/dyla-adversarial", help="scratch root")
    args = parser.parse_args()

    reuse = not args.no_reuse
    scratch = Path(args.scratch)
    if args.live:
        baseline = run_one_live(scratch / "baseline", adversarial=False, reuse=reuse)
        adversarial = run_one_live(scratch / "adversarial", adversarial=True, reuse=reuse)
        report = {
            "experiment": "P3-3 adversarial analyst (live)",
            "model": load_settings().model_name,
            "reuse_enabled": reuse,
            "note": (
                "Two full live suites, the second with the audit threat appended to the "
                "system message. Live models are nondeterministic, so the comparison is "
                "per-question behavioural (claims kept, citations per claim, verdicts, "
                "rejection reasons), not byte equality."
            ),
            "per_question": [
                {"question": b["question"], "baseline": _live_row_summary(b), "adversarial": _live_row_summary(a)}
                for b, a in zip(baseline, adversarial)
            ],
        }
        print(json.dumps(report, indent=2))
        return 0

    baseline = run_one(scratch / "baseline", adversarial=False, reuse=reuse)
    adversarial = run_one(scratch / "adversarial", adversarial=True, reuse=reuse)

    identical = [_strip_metrics(b) == _strip_metrics(a) for b, a in zip(baseline, adversarial)]
    report = {
        "experiment": "P3-3 adversarial analyst",
        "model": "OfflineModel (extractive stand-in, no API key)",
        "reuse_enabled": reuse,
        "byte_identical_questions": sum(identical),
        "total_questions": len(baseline),
        "note": (
            "OfflineModel derives its answer from the Question: line and the supplied "
            "evidence blocks; the system message is inert. Identical outputs are "
            "therefore the expected negative result, not evidence about model "
            "honesty. P3-3 needs a live model (see tests/unit/test_offline.py)."
        ),
        "differences": [
            {"question": b["question"], "what": "answers, claims, or verdicts differ"}
            for b, a in zip(baseline, adversarial)
            if _strip_metrics(b) != _strip_metrics(a)
        ],
    }
    print(json.dumps(report, indent=2))
    return 0 if all(identical) else 1


if __name__ == "__main__":
    raise SystemExit(main())
