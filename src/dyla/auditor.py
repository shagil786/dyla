"""Independent, failure-tolerant claim auditing."""

from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeout, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Literal

from .domain import AnalystAnswer, AuditVerdict, AuditorVerdictModel, Citation, RunEvent
from .models import ModelRequest
from .ports import SearchProvider

AuditStatus = Literal["supported", "unsupported", "contradicted", "uncited"]
AuditRunStatus = Literal["complete", "partial", "failed"]


@dataclass(frozen=True)
class AuditState:
    status: AuditRunStatus
    issues: list[str]


class AuditorAgent:
    """Audit claims against freshly fetched sources, not analyst evidence."""

    def __init__(
        self,
        *,
        fetcher: SearchProvider,
        comparator: Any | None = None,
        memory: Any | None = None,
        trace_writer: Any | None = None,
        retries: int = 2,
        timeout_seconds: float = 10.0,
    ) -> None:
        if retries < 0 or timeout_seconds <= 0:
            raise ValueError("retries must be non-negative and timeout_seconds must be positive")
        self.fetcher = fetcher
        self.comparator = comparator or _TextComparator()
        self.memory = memory
        self.trace_writer = trace_writer
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.metrics = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "duration_ms": 0,
                        "searches": 0, "fetches": 0, "memory_hits": 0, "parallel_calls": 0}
        self.audit_state = AuditState("complete", [])

    def run(self, answer: AnalystAnswer, run_id: str) -> list[AuditVerdict]:
        self.audit_state = AuditState("complete", [])
        verdicts: list[AuditVerdict] = []
        issues: list[str] = []
        try:
            for claim in answer.claims:
                if not claim.citations:
                    verdict = AuditVerdict(
                        claim_id=claim.id, status="uncited",
                        explanation="The claim has no citations to independently retrieve.",
                        citations_checked=[],
                    )
                    verdicts.append(verdict)
                    self._persist(claim, verdict, run_id)
                    self._trace(run_id, "claim_audited", {"claim_id": claim.id, "status": verdict.status})
                    continue

                documents: dict[str, Any] = {}
                checked: list[Citation] = []
                failed = False
                for citation in _unique_citations(claim.citations):
                    self.metrics["fetches"] += 1
                    try:
                        document = self._fetch(citation.url)
                    except Exception as exc:
                        failed = True
                        self._warning(run_id, claim.id, "source fetch failed")
                        self._trace(run_id, "source_fetch_failed", {"claim_id": claim.id, "url": citation.url, "error": str(exc)})
                        continue
                    documents[citation.url] = document
                    checked.append(citation)
                    self._trace(run_id, "source_fetched", {"claim_id": claim.id, "url": citation.url})

                if not documents:
                    verdict = AuditVerdict(
                        claim_id=claim.id, status="unsupported",
                        explanation="No cited source could be fetched for independent audit.",
                        citations_checked=[],
                    )
                elif failed:
                    verdict = AuditVerdict(
                        claim_id=claim.id, status="unsupported",
                        explanation="At least one cited source could not be fetched; the claim is not verified.",
                        citations_checked=checked,
                    )
                else:
                    status, explanation = self._compare(claim, documents)
                    verdict = AuditVerdict(
                        claim_id=claim.id, status=status,
                        explanation=explanation, citations_checked=checked,
                    )
                verdicts.append(verdict)
                self._persist(claim, verdict, run_id)
                self._trace(run_id, "claim_audited", {"claim_id": claim.id, "status": verdict.status})
        except Exception as exc:
            message = f"{run_id}: auditor failed: {exc}"
            issues.append(message)
            self._warning(run_id, None, f"auditor failed: {exc}")
            self._trace(run_id, "auditor_failed", {"error": str(exc)})
        issues = list(dict.fromkeys([*issues, *self.audit_state.issues]))
        run_status: AuditRunStatus = "partial" if issues and verdicts else ("failed" if issues else "complete")
        self.audit_state = AuditState(run_status, issues)
        return verdicts

    def _fetch(self, url: str) -> Any:
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                pool = ThreadPoolExecutor(max_workers=1)
                future = pool.submit(self.fetcher.fetch, url)
                try:
                    return future.result(timeout=self.timeout_seconds)
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
            except (Exception, FutureTimeout) as exc:
                last_error = exc
        raise RuntimeError(f"fetch failed after {self.retries + 1} attempts") from last_error

    def _compare(self, claim: Any, documents: dict[str, Any]) -> tuple[AuditStatus, str]:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.comparator.compare, claim, documents)
        try:
            result = future.result(timeout=self.timeout_seconds)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if isinstance(result, AuditVerdict):
            return result.status, result.explanation
        if isinstance(result, tuple) and len(result) == 2:
            status, explanation = result
        else:
            status, explanation = result, f"Comparator returned {result}."
        if status not in {"supported", "unsupported", "contradicted", "uncited"}:
            raise ValueError(f"invalid audit status: {status}")
        return status, str(explanation)

    def _record_issue(self, issue: str) -> None:
        self.audit_state = AuditState("partial", [*self.audit_state.issues, issue])

    def _persist(self, claim: Any, verdict: AuditVerdict, run_id: str) -> None:
        if self.memory is None:
            return
        try:
            self.memory.save_claim(claim, verdict)
        except Exception as exc:
            message = f"{run_id}: {claim.id}: memory persistence failed: {exc}"
            self._record_issue(message)
            self._warning(run_id, claim.id, f"memory persistence failed: {exc}")

    def _warning(self, run_id: str, claim_id: str | None, message: str) -> None:
        if self.memory is not None:
            warning = f"{run_id}: {claim_id + ': ' if claim_id else ''}{message}"
            try:
                self.memory.save_research_warning(warning)
            except Exception as exc:
                self._record_issue(f"{run_id}: warning persistence failed: {exc}")

    def _trace(self, run_id: str, event: str, payload: dict[str, Any]) -> None:
        if self.trace_writer is None:
            return
        try:
            self.trace_writer.append(RunEvent(
                run_id=run_id, timestamp=datetime.now(UTC), component="auditor",
                event=event, payload=payload, duration_ms=None, error=None,
            ))
        except Exception as exc:
            self._record_issue(f"{run_id}: {event} tracing failed: {exc}")


class ModelComparator:
    """Model-backed comparator that judges claims against fetched source documents."""

    def __init__(self, provider: Any, *, max_document_chars: int = 4000, max_prompt_chars: int = 24000) -> None:
        self.provider = provider
        self.max_document_chars = max_document_chars
        self.max_prompt_chars = max_prompt_chars

    def compare(self, claim: Any, documents: dict[str, Any]) -> tuple[AuditStatus, str]:
        request = ModelRequest(
            messages=[
                {"role": "system", "content": _AUDITOR_SYSTEM_PROMPT},
                {"role": "user", "content": self._build_prompt(claim, documents)},
            ],
            response_schema=AuditorVerdictModel,
            max_tokens=300,
            temperature=0.0,
        )
        response = self.provider.complete(request)
        verdict = response.parsed
        if verdict is None:
            raise ValueError("auditor model returned no structured verdict")
        status = str(verdict.status).strip().casefold()
        if status not in {"supported", "unsupported", "contradicted", "uncited"}:
            raise ValueError(f"invalid audit status: {verdict.status}")
        return status, str(verdict.explanation)

    def _build_prompt(self, claim: Any, documents: dict[str, Any]) -> str:
        sections = []
        for url, document in documents.items():
            title = getattr(document, "title", None) or "untitled"
            excerpt = (getattr(document, "text", "") or "")[: self.max_document_chars]
            sections.append(f"URL: {url}\nTitle: {title}\nText: {excerpt}")
        prompt = f"Claim:\n{claim.text}\n\nSource documents:\n" + "\n\n".join(sections)
        return prompt[: self.max_prompt_chars]


_AUDITOR_SYSTEM_PROMPT = (
    "You are an independent auditor. Judge ONLY the claim text against the provided "
    "source documents. Respond with JSON only and no other text, shaped as "
    '{"status": "<status>", "explanation": "<explanation>"}. '
    "status must be exactly one of: supported, unsupported, contradicted, uncited. "
    "supported = the claim text is directly supported by document content; "
    "contradicted = document content asserts the opposite of the claim; "
    "uncited = the documents do not address the claim; "
    "unsupported = the claim cannot be verified from the documents."
)


def _unique_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[str] = set()
    result = []
    for citation in citations:
        if citation.url not in seen:
            seen.add(citation.url)
            result.append(citation)
    return result


class _TextComparator:
    """Deterministic fallback comparator for deployments without a judge model."""

    def compare(self, claim: Any, documents: dict[str, Any]) -> tuple[AuditStatus, str]:
        claim_text = _normalize(claim.text)
        source_text = " ".join(_normalize(getattr(document, "text", "")) for document in documents.values())
        if claim_text and claim_text in source_text:
            return "supported", "The complete claim text appears in the independently fetched sources."
        return "unsupported", "The complete claim text was not found in the independently fetched sources."


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))
