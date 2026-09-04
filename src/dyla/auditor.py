"""Independent, failure-tolerant claim auditing."""

from __future__ import annotations

import time
from concurrent.futures import TimeoutError as FutureTimeout, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from .domain import AnalystAnswer, AuditVerdict, AuditorVerdictModel, Citation, RunEvent
from .models import ModelRequest
from .ports import SearchProvider
from .verification import verify_claim

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
        self.comparator = comparator or _TextComparator(memory)
        self.memory = memory
        self.trace_writer = trace_writer
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.metrics = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "duration_ms": 0,
                        "searches": 0, "fetches": 0, "memory_hits": 0, "parallel_calls": 0}
        self.audit_state = AuditState("complete", [])

    def run(
        self, answer: AnalystAnswer, run_id: str, deadline: float | None = None
    ) -> list[AuditVerdict]:
        """Audit every claim, stopping early if ``deadline`` passes.

        ``deadline`` is a ``time.monotonic()`` timestamp. Cooperative checking
        between claims is what actually bounds this stage: the auditor is
        synchronous and runs on a worker thread, and Python cannot kill a
        thread, so an external timeout alone would abandon a thread that keeps
        working. Stopping between claims returns the verdicts already earned and
        reports the shortfall instead of silently truncating.
        """
        self.audit_state = AuditState("complete", [])
        verdicts: list[AuditVerdict] = []
        issues: list[str] = []
        try:
            for index, claim in enumerate(answer.claims):
                if deadline is not None and time.monotonic() >= deadline:
                    remaining = len(answer.claims) - index
                    message = (
                        f"{run_id}: audit stopped at the wall-clock deadline with "
                        f"{remaining} of {len(answer.claims)} claims unaudited"
                    )
                    issues.append(message)
                    self._trace(run_id, "auditor_failed", {"error": message})
                    break
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
                        document = self._fetch(citation.url, run_id, deadline)
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
                    status, explanation = self._compare(claim, documents, deadline)
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

    def _fetch(self, url: str, run_id: str = "", deadline: float | None = None) -> Any:
        """Fetch a cited source, retrying, and saying so in the trace.

        Retries used to be entirely silent: each attempt overwrote last_error
        and only the final failure surfaced. A source that succeeded on the
        third try looked identical in the log to one that succeeded on the
        first, which hides both flakiness and latency spent. Every failed
        attempt now emits an event.
        """
        last_error: Exception | None = None
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                timeout = self._budgeted_timeout(deadline)
                pool = ThreadPoolExecutor(max_workers=1)
                future = pool.submit(self.fetcher.fetch, url)
                try:
                    result = future.result(timeout=timeout)
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
                if attempt > 1 and run_id:
                    self._trace(run_id, "source_fetch_recovered", {
                        "url": url, "attempt": attempt, "attempts_allowed": attempts,
                    })
                return result
            except (Exception, FutureTimeout) as exc:
                last_error = exc
                if run_id:
                    self._trace(run_id, "source_fetch_retried", {
                        "url": url, "attempt": attempt, "attempts_allowed": attempts,
                        "error": str(exc) or exc.__class__.__name__,
                        "will_retry": attempt < attempts,
                    })
        raise RuntimeError(f"fetch failed after {attempts} attempts") from last_error

    def _budgeted_timeout(self, deadline: float | None) -> float:
        """Never wait past the run deadline, and never wait a non-positive time."""
        if deadline is None:
            return self.timeout_seconds
        return max(0.01, min(self.timeout_seconds, deadline - time.monotonic()))

    def _compare(
        self, claim: Any, documents: dict[str, Any], deadline: float | None = None
    ) -> tuple[AuditStatus, str]:
        timeout = self._budgeted_timeout(deadline)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.comparator.compare, claim, documents)
        try:
            result = future.result(timeout=timeout)
        except FutureTimeout as exc:
            raise TimeoutError(f"comparator did not finish within {timeout:.2f}s") from exc
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
    "unsupported = the claim cannot be verified from the documents. "
    "For profitability claims, judge by the reported financial results: a reported "
    "net loss in the company's latest published period supports a claim that it is "
    "not profitable, and a reported net profit supports a claim that it is "
    "profitable. Statements of future intent (e.g. 'aims to be profitable', 'on "
    "track to profitability') do not contradict a claim about current profitability."
)


def _unique_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[str] = set()
    result = []
    for citation in citations:
        if citation.url not in seen:
            seen.add(citation.url)
            result.append(citation)
    return result


def _known_entity_names(memory: Any | None) -> frozenset[str]:
    """Entity names the system has already researched.

    Used only to decide whether a *sentence-initial* capitalised word is a name.
    Everything mid-sentence is checked regardless, so an auditor with no memory
    attached is weaker at misattribution detection but never wrong in a new way.
    """
    getter = getattr(memory, "known_entity_names", None)
    if getter is None:
        return frozenset()
    try:
        return frozenset(getter())
    except Exception:
        return frozenset()


class _TextComparator:
    """Deterministic comparator used when no judge model is configured.

    Delegates to :mod:`dyla.verification`, which decomposes a claim into
    numeric/date facts plus content words and checks those against the source.
    The previous implementation required the whole claim to appear verbatim as a
    substring, so paraphrasing sources — that is, all real sources — were marked
    unsupported and no claim could ever be marked contradicted.
    """

    def __init__(self, memory: Any | None = None) -> None:
        # Read from memory per comparison, never snapshotted. Snapshotting at
        # construction looked equivalent and was not: the auditor is built
        # before the first question runs, so the snapshot was always empty and
        # entities discovered during the run were invisible to the
        # misattribution check. That silently cost half its detection rate.
        self.memory = memory

    @property
    def known_entities(self) -> frozenset[str]:
        return _known_entity_names(self.memory)

    def compare(self, claim: Any, documents: dict[str, Any]) -> tuple[AuditStatus, str]:
        texts = {
            url: (getattr(document, "text", "") or "")
            for url, document in documents.items()
        }
        result = verify_claim(
            getattr(claim, "text", "") or "", texts, self.known_entities
        )
        return result.status, result.explanation
