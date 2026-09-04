"""Entity-aware research orchestration and structured answer synthesis."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from typing import Any

from .domain import AnalystAnswer, Citation, Evidence, MemoryRecord, RunEvent, SearchFilters
from .ingest import ingest_document
from .models import ModelRequest
from .ports import SearchProvider
from .query_planner import QueryPlanner

_REJECTED_VERDICTS = frozenset({"unsupported", "contradicted"})


class _CountingEmbedder:
    """Wrap an embedding provider so its token spend lands in the run metrics.

    Ingestion embeds every chunk of every fetched page, which is billed. Without
    counting it, memory reuse looks free in the token column even though the
    saving is largely there.
    """

    def __init__(self, embedder: Any, metrics: dict[str, Any]) -> None:
        self._embedder, self._metrics = embedder, metrics

    def embed(self, texts: list[str]) -> Any:
        self._metrics["embedding_tokens"] += sum(max(1, len(text) // 4) for text in texts)
        return self._embedder.embed(texts)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._embedder, name)


def _claim_fingerprint(text: str) -> frozenset[str]:
    """Content-word fingerprint used to recognise a restated claim."""
    from .verification import content_words

    return frozenset(content_words(text))


def _restates_rejected_claim(text: str, rejected: list[str], threshold: float = 0.8) -> bool:
    """True when `text` substantially restates a previously rejected claim.

    Substring matching was the earlier approach and is too weak: a reworded
    restatement of a rejected claim slips straight through. Comparing
    content-word fingerprints catches paraphrase, and the 0.8 threshold keeps a
    merely adjacent claim about the same entity from being suppressed.
    """
    current = _claim_fingerprint(text)
    if not current:
        return False
    for prior in rejected:
        previous = _claim_fingerprint(prior)
        if not previous:
            continue
        overlap = len(current & previous) / len(previous)
        if overlap >= threshold:
            return True
    return False



class AnalystAgent:
    def __init__(
        self, *, model: Any, resolver: Any, memory: Any, searcher: SearchProvider, fetcher: SearchProvider,
        index: Any, embedder: Any, planner: QueryPlanner | None = None,
        max_subqueries: int = 4, search_limit: int = 5, evidence_limit: int = 8,
        trace_writer: Any | None = None, reuse_enabled: bool = True,
        reuse_min_sources: int = 2, reuse_min_score: float = 0.0, min_evidence: int = 1,
    ) -> None:
        self.model, self.resolver, self.memory = model, resolver, memory
        self.searcher, self.fetcher, self.index = searcher, fetcher, index
        self.planner = planner or QueryPlanner(max_subqueries=max_subqueries)
        self.trace_writer, self.search_limit, self.evidence_limit = trace_writer, search_limit, evidence_limit
        self.reuse_enabled, self.reuse_min_sources = reuse_enabled, reuse_min_sources
        self.reuse_min_score, self.min_evidence = reuse_min_score, min_evidence
        self.metrics = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "duration_ms": 0,
                        "searches": 0, "fetches": 0, "memory_hits": 0, "parallel_calls": 0,
                        "failed_searches": 0, "failed_fetches": 0, "failed_ingestions": 0,
                        "claims_blocked_by_audit_feedback": 0,
                        "searches_skipped": 0, "evidence_reused": 0, "reuse_corrections": 0,
                        "embedding_tokens": 0}
        self.embedder = _CountingEmbedder(embedder, self.metrics)

    async def run(self, question: str, run_id: str) -> AnalystAnswer:
        started = time.monotonic()
        if isinstance(self.planner, QueryPlanner):
            self.planner.run_id = run_id
            if self.trace_writer is not None:
                self.planner.trace_writer = self.trace_writer
        memories = await asyncio.to_thread(self.memory.search_memory, question, 10)
        self._trace(run_id, "memory_retrieved", {"count": len(memories)})
        self.metrics["memory_hits"] += len(memories)
        plan = await asyncio.to_thread(self.planner.expand, question, memories)
        plan = await asyncio.to_thread(self._augment_entities, plan, question, run_id)
        resolved: dict[str, str] = {}
        for entity in plan.entities:
            result = await asyncio.to_thread(self.resolver.resolve, entity, question)
            if result.status == "resolved" and result.entity_id:
                resolved[entity.casefold()] = result.entity_id
        entity_ids = list(dict.fromkeys(resolved.values()))
        if entity_ids:
            entity_memory = []
            for entity in plan.entities:
                entity_memory.extend(await asyncio.to_thread(self.memory.search_memory, entity, 10))
            by_id = {record.id: record for record in (*memories, *entity_memory)}
            memories = [record for record in by_id.values() if not record.entity_ids or set(record.entity_ids) & set(entity_ids)]
            self.metrics["memory_hits"] += len(entity_memory)

        vector = await asyncio.to_thread(self.embedder.embed, [question])
        filters, date_limitations = self._filters(entity_ids, plan.date_constraints)

        # --- Memory-first retrieval -----------------------------------------
        # Evidence indexed while answering earlier questions is durable, so a
        # question about an entity already researched can often be answered
        # without paying for search and fetch again. memory_hits was previously
        # counted but changed no behaviour; this is what makes it pay.
        reuse = await self._assess_reuse(question, vector[0], entity_ids, plan, resolved, run_id)
        collection_limitations: list[str] = []
        if reuse["to_run"]:
            collection_limitations += await self._collect_from_web(reuse["to_run"], plan, resolved, run_id)

        evidence = await asyncio.to_thread(
            self.index.hybrid_search, question, vector[0], filters, self.evidence_limit,
        )

        # Course correction: reuse promised coverage that did not materialise.
        # Skipping a search is a bet; this is the path that pays it off when the
        # bet is wrong, rather than answering from thin evidence.
        if reuse["skipped"] and len(evidence) < self.min_evidence:
            self._trace(run_id, "reuse_insufficient", {
                "evidence_found": len(evidence),
                "evidence_required": self.min_evidence,
                "recovering_queries": [item["query"] for item in reuse["skipped"]],
            })
            self.metrics["reuse_corrections"] += 1
            self.metrics["searches_skipped"] -= len(reuse["skipped"])
            collection_limitations += await self._collect_from_web(
                reuse["skipped"], plan, resolved, run_id
            )
            evidence = await asyncio.to_thread(
                self.index.hybrid_search, question, vector[0], filters, self.evidence_limit,
            )
        self._trace(run_id, "evidence_selected", {"count": len(evidence)})
        answer = await asyncio.to_thread(self._synthesize, question, memories, evidence, [*collection_limitations, *date_limitations])
        self.metrics["duration_ms"] = int((time.monotonic() - started) * 1000)
        return answer

    def _entity_ids_from_content(self, text: str) -> list[str]:
        """Tag a page with every known entity it actually discusses.

        Attribution used to come only from the query that found the page, so a
        page about Infosys fetched while answering "largest exporters
        headquartered in Bengaluru" -- a question naming no company -- was
        stored untagged, and a later Infosys question could not reuse it. The
        page is about Infosys regardless of how it was found.

        Matching is on whole words against canonical names only. Aliases are
        deliberately excluded: they are lower-confidence by construction, and a
        wrong tag here silently poisons reuse for that entity.
        """
        known = getattr(self.memory, "known_entities", None)
        if known is None or not text:
            return []
        try:
            entities = known()
        except Exception:
            return []
        haystack = f" {' '.join(re.findall(r'[A-Za-z0-9&.-]+', text.casefold()))} "
        return [
            entity_id for entity_id, name in entities
            if name.strip() and f" {name.casefold()} " in haystack
        ]

    def _augment_entities(self, plan: Any, question: str, run_id: str) -> Any:
        """Add entities the system already knows about and that appear in the question.

        The planner derives entities from retrieved memory *records*, so on a
        question whose wording does not overlap any stored record text it finds
        nothing -- and with no entities there is no resolution, no entity filter
        and no memory reuse. Consulting the entity store directly is what lets
        knowledge carry across questions rather than only across paraphrases.
        """
        known = getattr(self.memory, "known_entity_names", None)
        if known is None:
            return plan
        try:
            names = known()
        except Exception as exc:
            self._trace(run_id, "reuse_probe_failed", {"error": f"entity lookup failed: {exc}"})
            return plan
        haystack = question.casefold()
        found = [name for name in names if name.casefold() in haystack]
        if not found:
            return plan
        merged = list(dict.fromkeys([*plan.entities, *found]))
        if merged == list(plan.entities):
            return plan
        self._trace(run_id, "memory_retrieved", {"known_entities_in_question": found})
        return plan.model_copy(update={"entities": merged})

    async def _assess_reuse(
        self, question: str, vector: list[float], entity_ids: list[str],
        plan: Any, resolved: dict[str, str], run_id: str,
    ) -> dict[str, Any]:
        """Decide which subqueries the durable index already covers.

        An entity counts as covered when the index already holds evidence from
        at least ``reuse_min_sources`` distinct sources for it. Requiring more
        than one source matters: a single prior page is exactly the thin,
        uncorroborated evidence the analyst is supposed to distrust, so reusing
        it would trade cost for correctness. Requiring two means reuse only
        happens where the earlier run already cross-checked.
        """
        subqueries = list(plan.subqueries)
        if not entity_ids or not self.reuse_enabled:
            return {"to_run": subqueries, "skipped": [], "covered": []}

        covered: list[str] = []
        for entity_id in entity_ids:
            try:
                prior = await asyncio.to_thread(
                    self.index.hybrid_search, question, vector,
                    SearchFilters(entity_ids=[entity_id]), self.evidence_limit,
                )
            except Exception as exc:
                self._trace(run_id, "reuse_probe_failed", {"entity_id": entity_id, "error": str(exc)})
                continue
            sources = {item.source_id for item in prior if item.score >= self.reuse_min_score}
            if len(sources) >= self.reuse_min_sources:
                covered.append(entity_id)

        if not covered:
            self._trace(run_id, "memory_reuse_evaluated", {"covered_entities": 0, "skipped_queries": 0})
            return {"to_run": subqueries, "skipped": [], "covered": []}

        covered_set = set(covered)
        all_covered = covered_set >= set(entity_ids)
        to_run, skipped = [], []
        for item in subqueries:
            ids = self._subquery_entity_ids(item, plan, resolved)
            if ids:
                (skipped if set(ids) <= covered_set else to_run).append(item)
            else:
                # The bare question carries no entity of its own; it is only
                # redundant when every entity in the plan is already covered.
                (skipped if all_covered else to_run).append(item)

        self.metrics["searches_skipped"] += len(skipped)
        self.metrics["evidence_reused"] += len(covered)
        self._trace(run_id, "memory_reuse_evaluated", {
            "covered_entities": len(covered),
            "skipped_queries": [item["query"] for item in skipped],
            "remaining_queries": [item["query"] for item in to_run],
        })
        return {"to_run": to_run, "skipped": skipped, "covered": covered}

    @staticmethod
    def _subquery_entity_ids(item: dict, plan: Any, resolved: dict[str, str]) -> list[str]:
        entities = item.get("entities") or [
            entity for entity in plan.entities
            if entity.casefold() in str(item.get("query", "")).casefold()
        ]
        return [resolved[e.casefold()] for e in entities if e.casefold() in resolved]

    async def _collect_from_web(
        self, subqueries: list[dict], plan: Any, resolved: dict[str, str], run_id: str,
    ) -> list[str]:
        """Search and fetch for the given subqueries, ingesting what comes back."""
        limitations: list[str] = []
        self.metrics["searches"] += len(subqueries)
        self.metrics["parallel_calls"] += 1
        search_results = await asyncio.gather(*[
            asyncio.to_thread(self.searcher.search, item["query"], self.search_limit)
            for item in subqueries
        ], return_exceptions=True)

        hits_by_url: dict[str, tuple[Any, list[str]]] = {}
        for item, batch in zip(subqueries, search_results):
            if isinstance(batch, Exception):
                self.metrics["failed_searches"] += 1
                self._trace(run_id, "web_search_failed", {"query": item["query"], "error": str(batch)})
                limitations.append(f"Web search failed for query '{item['query']}'; its results were excluded.")
                continue
            self._trace(run_id, "web_searched", {"query": item["query"], "results": len(batch)})
            query_ids = self._subquery_entity_ids(item, plan, resolved)
            for hit in batch:
                old = hits_by_url.get(hit.url)
                ids = list(dict.fromkeys((old[1] if old else []) + query_ids))
                hits_by_url[hit.url] = (hit, ids)

        self.metrics["fetches"] += len(hits_by_url)
        self.metrics["parallel_calls"] += 1
        documents = await asyncio.gather(*[
            asyncio.to_thread(self.fetcher.fetch, hit.url) for hit, _ in hits_by_url.values()
        ], return_exceptions=True)
        for document, (hit, ids) in zip(documents, hits_by_url.values()):
            if isinstance(document, Exception):
                self.metrics["failed_fetches"] += 1
                self._trace(run_id, "page_fetch_failed", {"url": hit.url, "error": str(document)})
                limitations.append(f"Page fetch failed for {hit.url}; it was excluded from evidence.")
                continue
            self._trace(run_id, "page_fetched", {"url": hit.url, "chars": len(document.text)})
            content_ids = await asyncio.to_thread(self._entity_ids_from_content, document.text)
            ids = list(dict.fromkeys([*ids, *content_ids]))
            try:
                await asyncio.to_thread(ingest_document, document, self.embedder, self.index, entity_ids=ids)
            except Exception as exc:
                self.metrics["failed_ingestions"] += 1
                self._trace(run_id, "ingest_failed", {"url": hit.url, "error": str(exc)})
                limitations.append(f"Page content from {hit.url} could not be indexed for retrieval; it was excluded from evidence.")
                continue
        return limitations

    def _trace(self, run_id: str, event: str, payload: dict[str, Any]) -> None:
        if self.trace_writer is None:
            return
        try:
            self.trace_writer.append(RunEvent(
                run_id=run_id, timestamp=datetime.now(UTC), component="analyst",
                event=event, payload=payload, duration_ms=None, error=None,
            ))
        except Exception:
            pass

    @staticmethod
    def _filters(entity_ids: list[str], constraints: list[str]) -> tuple[SearchFilters, list[str]]:
        years = sorted({int(value) for constraint in constraints for value in [constraint] if value.isdigit() and len(value) == 4})
        unsupported = [constraint for constraint in constraints if not (constraint.isdigit() and len(constraint) == 4)]
        limitations = [f"Date constraint '{constraint}' was not applied because only year constraints are supported." for constraint in unsupported]
        after = datetime(years[0], 1, 1, tzinfo=UTC) if years else None
        before = datetime(years[-1] + 1, 1, 1, tzinfo=UTC) if years else None
        if years:
            limitations.append(
                f"Date filter applied for {', '.join(str(year) for year in years)}; "
                "sources without a published date were also considered."
            )
        return SearchFilters(entity_ids=entity_ids or None, published_after=after, published_before=before), limitations

    def _synthesize(self, question: str, memories: list[MemoryRecord], evidence: list[Evidence], date_limitations: list[str]) -> AnalystAnswer:
        if not evidence:
            return AnalystAnswer(answer="Insufficient evidence.", claims=[], limitations=["No retrieved evidence was available.", *date_limitations])
        evidence_context = "\n\n".join(
            f"Evidence {index}:\n"
            f"source_id: {item.source_id}\n"
            f"chunk_id: {item.chunk_id}\n"
            f"url: {item.url}\n"
            f"title: {item.title}\n"
            f"text: {item.text}"
            for index, item in enumerate(evidence, start=1)
        )
        # --- Auditor -> analyst feedback ---
        # Claims a previous run asserted and the auditor then rejected. Read from
        # verdict_status, not from `verified`: `verified` is a bool that cannot
        # separate "audited and rejected" from "never audited", and the earlier
        # implementation of this block collected records where verified was True
        # (i.e. the auditor's *approved* claims) into a list it called
        # prior_rejected_claims, then never called the function that used it.
        rejected_before = [
            record.text
            for record in memories
            if record.kind == "claim"
            and record.text
            and (record.verdict_status or "") in _REJECTED_VERDICTS
        ]

        context = "\n".join([*(f"Memory: {m.text}" for m in memories), evidence_context])
        system_prompt = (
            "Answer using only supplied evidence. Return AnalystAnswer JSON. "
            "For every citation, copy source_id, chunk_id, URL, and title exactly "
            "from one supplied evidence item; do not invent or alter citation metadata."
        )
        if rejected_before:
            system_prompt += (
                " An independent auditor previously re-fetched the cited sources for the "
                "following claims and found they were not supported by them. Do not restate "
                "any of these unless the evidence supplied now independently establishes it:\n"
                + "\n".join(f"- {text}" for text in rejected_before[:10])
            )
        response = self.model.complete(ModelRequest(
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": f"Question: {question}\n{context}"}],
            response_schema=AnalystAnswer, max_tokens=1200, temperature=0,
        ))
        self.metrics["input_tokens"] += int(getattr(response, "input_tokens", 0))
        self.metrics["output_tokens"] += int(getattr(response, "output_tokens", 0))
        self.metrics["estimated_cost"] += float(getattr(response, "estimated_cost", 0.0))
        answer = response.parsed if isinstance(response.parsed, AnalystAnswer) else AnalystAnswer.model_validate(response.parsed)
        evidence_keys: set[tuple[str, str, str | None]] = {(item.url, item.source_id, item.chunk_id) for item in evidence}
        valid_claims = []
        limitations = list(answer.limitations)
        for claim in answer.claims:
            if not claim.citations:
                limitations.append(f"Claim {claim.id} was rejected because it had no citations.")
                continue
            mapped = [citation for citation in claim.citations if self._citation_maps(citation, evidence_keys)]
            if len(mapped) != len(claim.citations):
                limitations.append(f"Claim {claim.id} was rejected because a citation did not map to retrieved evidence.")
                continue
            if claim.confidence.casefold() in {"low", "medium", "weak"} and len({citation.source_id for citation in mapped}) < 2:
                limitations.append(f"Claim {claim.id} was rejected for lacking independent evidence.")
                continue
            if _restates_rejected_claim(claim.text, rejected_before):
                # The prompt above asks the model not to restate these. Asking is
                # advisory; this filter is not. The loop has to hold even when the
                # model ignores the instruction.
                limitations.append(
                    f"Claim {claim.id} was rejected because an earlier audit found the same "
                    "assertion unsupported by its cited sources."
                )
                self.metrics["claims_blocked_by_audit_feedback"] += 1
                continue
            valid_claims.append(claim)
        if not answer.claims or not valid_claims:
            return AnalystAnswer(answer="Insufficient evidence.", claims=[], limitations=list(dict.fromkeys([*limitations, *date_limitations])))
        return AnalystAnswer(answer=answer.answer, claims=valid_claims, limitations=list(dict.fromkeys([*limitations, *date_limitations])))

    @staticmethod
    def _citation_maps(citation: Citation, keys: set[tuple[str, str, str | None]]) -> bool:
        return (citation.url, citation.source_id, citation.chunk_id) in keys or any(
            url == citation.url and source == citation.source_id and chunk is None for url, source, chunk in keys
        )
