"""Deterministic reliability and evidence quality gates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .domain import AnalystAnswer, AuditVerdict, RunEvent


@dataclass(frozen=True)
class QualityResult:
    status: Literal["complete", "incomplete", "unaudited"]
    issues: list[str]


class QualityGate:
    """Apply fail-closed, deterministic gates to an analyst answer and audit."""

    def validate(
        self, answer: AnalystAnswer, verdicts: list[AuditVerdict], trace_path: Path,
        *, run_id: str | None = None, audit_issues: list[str] | None = None,
    ) -> QualityResult:
        issues: set[str] = set(audit_issues or [])
        claim_ids = [claim.id for claim in answer.claims]
        for claim_id in sorted({item for item in claim_ids if claim_ids.count(item) > 1}):
            issues.add(f"answer contains duplicate claim id: {claim_id}")
        if not verdicts:
            issues.add("no audit verdicts were produced")
            self._validate_trace(trace_path, run_id, issues)
            return QualityResult("unaudited", sorted(issues))

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

        claim_ids = {claim.id for claim in answer.claims}
        for verdict in verdicts:
            if verdict.claim_id not in claim_ids:
                issues.add(f"audit verdict has no matching claim: {verdict.claim_id}")

        self._validate_trace(trace_path, run_id, issues)
        return QualityResult("incomplete" if issues else "complete", sorted(issues))

    @staticmethod
    def _validate_trace(trace_path: Path, run_id: str | None, issues: set[str]) -> None:
        if not trace_path.is_file() or trace_path.stat().st_size == 0:
            issues.add("research trace was not saved")
            return
        valid_events = {
            "started", "completed", "failed", "query_expanded", "source_fetched",
            "source_fetch_failed", "claim_audited", "auditor_failed", "memory_saved",
            "quality_completed", "memory_retrieved", "web_searched", "web_search_failed",
            "page_fetched", "page_fetch_failed", "ingest_failed", "evidence_selected",
            "memory_reuse_evaluated", "reuse_probe_failed", "reuse_insufficient",
        }
        try:
            for line_number, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    event = RunEvent.model_validate(json.loads(line))
                except (ValueError, TypeError) as exc:
                    issues.add(f"research trace has invalid event at line {line_number}: {exc}")
                    continue
                if run_id is not None and event.run_id != run_id:
                    issues.add(f"research trace contains event for another run: {event.run_id}")
                if event.event not in valid_events:
                    issues.add(f"research trace has unknown event: {event.event}")
        except OSError as exc:
            issues.add(f"research trace could not be read: {exc}")


def _all_citations_retrieved(claim: object, verdict: AuditVerdict) -> bool:
    citation_urls = {citation.url for citation in claim.citations}  # type: ignore[attr-defined]
    retrieved_urls = {citation.url for citation in verdict.citations_checked}
    return citation_urls <= retrieved_urls
