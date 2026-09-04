"""Entity-aware research orchestration and structured answer synthesis."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from .domain import AnalystAnswer, Citation, Evidence, MemoryRecord, RunEvent, SearchFilters
from .ingest import ingest_document
from .models import ModelRequest
from .ports import SearchProvider
from .query_planner import QueryPlanner


class AnalystAgent:
    def __init__(
        self, *, model: Any, resolver: Any, memory: Any, searcher: SearchProvider, fetcher: SearchProvider,
        index: Any, embedder: Any, planner: QueryPlanner | None = None,
        max_subqueries: int = 4, search_limit: int = 5, evidence_limit: int = 8,
        trace_writer: Any | None = None,
    ) -> None:
        self.model, self.resolver, self.memory = model, resolver, memory
        self.searcher, self.fetcher, self.index, self.embedder = searcher, fetcher, index, embedder
        self.planner = planner or QueryPlanner(max_subqueries=max_subqueries)
        self.trace_writer, self.search_limit, self.evidence_limit = trace_writer, search_limit, evidence_limit
        self.metrics = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "duration_ms": 0,
                        "searches": 0, "fetches": 0, "memory_hits": 0, "parallel_calls": 0,
                        "failed_searches": 0, "failed_fetches": 0}

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

        self.metrics["searches"] += len(plan.subqueries)
        self.metrics["parallel_calls"] += 1
        collection_limitations: list[str] = []
        search_results = await asyncio.gather(*[
            asyncio.to_thread(self.searcher.search, item["query"], self.search_limit)
            for item in plan.subqueries
        ], return_exceptions=True)
        hits_by_url: dict[str, tuple[Any, list[str]]] = {}
        for item, batch in zip(plan.subqueries, search_results):
            if isinstance(batch, Exception):
                self.metrics["failed_searches"] += 1
                self._trace(run_id, "web_search_failed", {"query": item["query"], "error": str(batch)})
                collection_limitations.append(f"Web search failed for query '{item['query']}'; its results were excluded.")
                continue
            self._trace(run_id, "web_searched", {"query": item["query"], "results": len(batch)})
            query_entities = item.get("entities", [])
            if not query_entities:
                query_entities = [entity for entity in plan.entities if entity.casefold() in item["query"].casefold()]
            query_ids = [resolved[entity.casefold()] for entity in query_entities if entity.casefold() in resolved]
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
                collection_limitations.append(f"Page fetch failed for {hit.url}; it was excluded from evidence.")
                continue
            self._trace(run_id, "page_fetched", {"url": hit.url, "chars": len(document.text)})
            await asyncio.to_thread(ingest_document, document, self.embedder, self.index, entity_ids=ids)
        vector = await asyncio.to_thread(self.embedder.embed, [question])
        filters, date_limitations = self._filters(entity_ids, plan.date_constraints)
        evidence = await asyncio.to_thread(
            self.index.hybrid_search, question, vector[0], filters, self.evidence_limit,
        )
        self._trace(run_id, "evidence_selected", {"count": len(evidence)})
        answer = await asyncio.to_thread(self._synthesize, question, memories, evidence, [*collection_limitations, *date_limitations])
        self.metrics["duration_ms"] = int((time.monotonic() - started) * 1000)
        return answer

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
        context = "\n".join([*(f"Memory: {m.text}" for m in memories), evidence_context])
        response = self.model.complete(ModelRequest(
            messages=[{"role": "system", "content": (
                "Answer using only supplied evidence. Return AnalystAnswer JSON. "
                "For every citation, copy source_id, chunk_id, URL, and title exactly "
                "from one supplied evidence item; do not invent or alter citation metadata."
            )},
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
            valid_claims.append(claim)
        if not answer.claims or not valid_claims:
            return AnalystAnswer(answer="Insufficient evidence.", claims=[], limitations=list(dict.fromkeys([*limitations, *date_limitations])))
        return AnalystAnswer(answer=answer.answer, claims=valid_claims, limitations=list(dict.fromkeys([*limitations, *date_limitations])))

    @staticmethod
    def _citation_maps(citation: Citation, keys: set[tuple[str, str, str | None]]) -> bool:
        return (citation.url, citation.source_id, citation.chunk_id) in keys or any(
            url == citation.url and source == citation.source_id and chunk is None for url, source, chunk in keys
        )
