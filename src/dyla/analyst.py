"""Entity-aware research orchestration and structured answer synthesis."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from .domain import AnalystAnswer, Citation, Evidence, MemoryRecord, SearchFilters
from .ingest import ingest_document
from .models import ModelRequest
from .query_planner import QueryPlanner


class AnalystAgent:
    def __init__(
        self, *, model: Any, resolver: Any, memory: Any, searcher: Any, fetcher: Any,
        index: Any, embedder: Any, planner: QueryPlanner | None = None,
        max_subqueries: int = 4, search_limit: int = 5, evidence_limit: int = 8,
        trace_writer: Any | None = None,
    ) -> None:
        self.model, self.resolver, self.memory = model, resolver, memory
        self.searcher, self.fetcher, self.index, self.embedder = searcher, fetcher, index, embedder
        self.planner = planner or QueryPlanner(max_subqueries=max_subqueries)
        self.trace_writer, self.search_limit, self.evidence_limit = trace_writer, search_limit, evidence_limit

    async def run(self, question: str, run_id: str) -> AnalystAnswer:
        if isinstance(self.planner, QueryPlanner):
            self.planner.run_id = run_id
            if self.trace_writer is not None:
                self.planner.trace_writer = self.trace_writer
        memories = await asyncio.to_thread(self.memory.search_memory, question, 10)
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

        search_results = await asyncio.gather(*[
            asyncio.to_thread(self.searcher.search, item["query"], self.search_limit)
            for item in plan.subqueries
        ])
        hits_by_url: dict[str, tuple[Any, list[str]]] = {}
        for item, batch in zip(plan.subqueries, search_results):
            query_entities = item.get("entities", [])
            if not query_entities:
                query_entities = [entity for entity in plan.entities if entity.casefold() in item["query"].casefold()]
            query_ids = [resolved[entity.casefold()] for entity in query_entities if entity.casefold() in resolved]
            for hit in batch:
                old = hits_by_url.get(hit.url)
                ids = list(dict.fromkeys((old[1] if old else []) + query_ids))
                hits_by_url[hit.url] = (hit, ids)
        documents = await asyncio.gather(*[
            asyncio.to_thread(self.fetcher.fetch, hit.url) for hit, _ in hits_by_url.values()
        ])
        for document, (_, ids) in zip(documents, hits_by_url.values()):
            await asyncio.to_thread(ingest_document, document, self.embedder, self.index, entity_ids=ids)
        vector = await asyncio.to_thread(self.embedder.embed, [question])
        filters, date_limitations = self._filters(entity_ids, plan.date_constraints)
        evidence = await asyncio.to_thread(
            self.index.hybrid_search, question, vector[0], filters, self.evidence_limit,
        )
        return await asyncio.to_thread(self._synthesize, question, memories, evidence, date_limitations)

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
        context = "\n".join([*(f"Memory: {m.text}" for m in memories), *(f"Evidence: {e.text} ({e.url})" for e in evidence)])
        response = self.model.complete(ModelRequest(
            messages=[{"role": "system", "content": "Answer using only supplied evidence. Return AnalystAnswer JSON."},
                      {"role": "user", "content": f"Question: {question}\n{context}"}],
            response_schema=AnalystAnswer, max_tokens=1200, temperature=0,
        ))
        answer = response.parsed if isinstance(response.parsed, AnalystAnswer) else AnalystAnswer.model_validate(response.parsed)
        evidence_keys: set[tuple[str, str, str | None]] = {(item.url, item.source_id, item.chunk_id) for item in evidence}
        valid_claims = []
        limitations = list(answer.limitations)
        for claim in answer.claims:
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
