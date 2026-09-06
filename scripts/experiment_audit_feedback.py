#!/usr/bin/env python
"""Measure the auditor -> analyst feedback loop.

The loop is implemented in ``AnalystAgent._synthesize``: claims a previous run
asserted and the auditor then marked ``unsupported`` or ``contradicted`` are
read back out of memory, named in the system prompt, and -- if the model
restates one anyway -- rejected before the answer is returned.

**It has never fired in the evaluation suite, and that is not a bug.** The
offline corpus is clean and the extractive model quotes verbatim, so all 29
claims are supported, nothing is ever stored with a rejected verdict, and the
list the loop reads is always empty. Reporting
``claims_blocked_by_audit_feedback`` in ``reports/evaluation.md`` would print a
permanent 0 that looks like a broken feature rather than an unexercised one.

So the mechanism is measured here instead, on a run where it *can* fire: a
rejected verdict is written to memory first, then the same question is asked
again. Two things are checked, because only the second one is the feature:

1. the prompt carries the warning (the analyst told the model);
2. a restatement is actually blocked (the analyst overruled the model).

A harness that only checked (1) would pass while the loop did nothing.

Run: ``.venv/bin/python scripts/experiment_audit_feedback.py``
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dyla.domain import AuditVerdict, Citation, Claim  # noqa: E402

from run_suite import build_offline, seed_entities  # noqa: E402

QUESTION = "Who is the current chief executive officer of Zerodha, and in which year did they take the role?"

# A claim the corpus does support, so the only reason to withhold it is the
# recorded verdict. Using a fact the evidence contradicts would prove nothing:
# the claim would vanish for the ordinary reason instead of the audited one.
POISONED = "Nithin Kamath is the chief executive officer of Zerodha."


def _prompts_seen(model) -> list[str]:
    return getattr(model, "_seen_prompts", [])


def _instrument(model) -> None:
    """Record every system prompt the analyst sends."""
    model._seen_prompts = []
    original = model.complete

    def complete(request):
        for message in request.messages:
            if message.get("role") == "system":
                model._seen_prompts.append(str(message.get("content", "")))
        return original(request)

    model.complete = complete


def _run(reject_first: bool) -> dict:
    db = ROOT / "dyla-feedback-experiment.db"
    if db.exists():
        db.unlink()
    orchestrator, _provider, model = build_offline(ROOT, reuse=True, db_path=db)
    seed_entities(orchestrator.memory)
    _instrument(model)

    if reject_first:
        # Exactly what a prior run would have left behind after the auditor
        # rejected this claim: the text, and the verdict that condemned it.
        claim = Claim(
            id="prior-1",
            text=POISONED,
            citations=[Citation(url="https://example.com/business-daily/zerodha-leadership",
                                title="Zerodha leadership", source_id="seed", chunk_id=None)],
            confidence="high",
        )
        orchestrator.memory.save_claim(
            claim,
            AuditVerdict(claim_id="prior-1", status="unsupported",
                         explanation="planted by the feedback experiment",
                         citations_checked=list(claim.citations)),
        )

    result = asyncio.run(orchestrator.ask(QUESTION))
    metrics = orchestrator.analyst.metrics
    prompts = _prompts_seen(model)
    db.unlink(missing_ok=True)
    return {
        "warned_in_prompt": any(POISONED in prompt for prompt in prompts),
        "blocked": int(metrics.get("claims_blocked_by_audit_feedback", 0)),
        "claim_texts": [claim.text for claim in result.answer.claims],
        "restated": any(POISONED == claim.text for claim in result.answer.claims),
    }


def main() -> int:
    control = _run(reject_first=False)
    treatment = _run(reject_first=True)

    print("auditor -> analyst feedback loop\n")
    print(f"{'':28} {'control':>10} {'after rejection':>16}")
    print(f"{'warning present in prompt':28} {str(control['warned_in_prompt']):>10} "
          f"{str(treatment['warned_in_prompt']):>16}")
    print(f"{'claim asserted in answer':28} {str(control['restated']):>10} "
          f"{str(treatment['restated']):>16}")
    print(f"{'claims blocked':28} {control['blocked']:>10} {treatment['blocked']:>16}")

    ok = (
        not control["warned_in_prompt"]
        and control["restated"]
        and treatment["warned_in_prompt"]
        and not treatment["restated"]
        and treatment["blocked"] >= 1
    )
    print("\nresult:", "loop engaged" if ok else "LOOP DID NOT ENGAGE")
    if not ok:
        print(json.dumps({"control": control, "treatment": treatment}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
