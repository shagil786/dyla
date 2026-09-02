"""Deterministic reliability and evidence quality gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .domain import AnalystAnswer, AuditVerdict


@dataclass(frozen=True)
class QualityResult:
    status: Literal["complete", "incomplete", "unaudited"]
    issues: list[str]


class QualityGate:
    """Apply fail-closed, deterministic gates to an analyst answer and audit."""

    def validate(
        self, answer: AnalystAnswer, verdicts: list[AuditVerdict], trace_path: Path,
    ) -> QualityResult:
        if not verdicts:
            return QualityResult("unaudited", ["no audit verdicts were produced"])

        issues: set[str] = set()
        by_id: dict[str, AuditVerdict] = {}
        for item in verdicts:
            if item.claim_id in by_id:
                issues.add(f"claim {item.claim_id} has multiple audit verdicts")
            by_id[item.claim_id] = item

        claims = sorted(answer.claims, key=lambda item: item.id)
        for claim in claims:
            if not claim.citations:
                issues.add(f"claim {claim.id} has no citations")
            verdict = by_id.get(claim.id)
            if verdict is None:
                issues.add(f"claim {claim.id} has no audit verdict")
                continue
            if verdict.status == "contradicted":
                issues.add(f"claim {claim.id} is contradicted")
            elif verdict.status == "unsupported":
                issues.add(f"claim {claim.id} is unsupported")
            elif verdict.status == "uncited":
                issues.add(f"claim {claim.id} is uncited")
            if claim.citations and not _all_citations_retrieved(claim, verdict):
                issues.add(f"claim {claim.id} has citations that were not retrieved")

        for verdict in verdicts:
            if verdict.claim_id not in {claim.id for claim in answer.claims}:
                issues.add(f"audit verdict has no matching claim: {verdict.claim_id}")

        if not trace_path.is_file() or trace_path.stat().st_size == 0:
            issues.add("research trace was not saved")
        return QualityResult("incomplete" if issues else "complete", sorted(issues))


def _all_citations_retrieved(claim: object, verdict: AuditVerdict) -> bool:
    citation_urls = {citation.url for citation in claim.citations}  # type: ignore[attr-defined]
    retrieved_urls = {citation.url for citation in verdict.citations_checked}
    return citation_urls <= retrieved_urls
