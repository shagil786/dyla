"""Entity-aware research orchestration and structured answer synthesis."""

from __future__ import annotations

import asyncio
from typing import Any

from .domain import AnalystAnswer, Evidence, MemoryRecord, SearchFilters
from .ingest import ingest_document
from .models import ModelRequest
from .query_planner import QueryPlanner


class AnalystAgent:
    def __init__(
        self, *, model: Any, resolver: Any, memory: Any, searcher: Any, fetcher: Any,
        index: Any, embedder: Any, planner: QueryPlanner | None = None,
        max_subqueries: int = 4, search_limit: int = 5, evidence_limit: int = 8,
    ) -> None:
        self.model, self.resolver, self.memory = model, resolver, memory
        self.searcher, self.fetcher, self.index, self.embedder = searcher, fetcher, index, embedder
        self.planner = planner or QueryPlanner(max_subqueries=max_subqueries)
        self.search_limit, self.evidence_limit = search_limit, evidence_limit

    async def run(self, question: str, run_id: str) -> AnalystAnswer:
        del run_id  # The runtime owns trace identity; this method remains directly testable.
        memories = await asyncio.to_thread(self.memory.search_memory, question, 10)
        plan = self.planner.expand(question, memories)
        entity_ids: list[str] = []
        for entity in plan.entities:
            resolved = await asyncio.to_thread(self.resolver.resolve, entity, question)
            if resolved.status == "resolved" and resolved.entity_id:
                entity_ids.append(resolved.entity_id)
        entity_ids = list(dict.fromkeys(entity_ids))
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
        hits = []
        for batch in search_results:
            hits.extend(batch)
        unique_hits = {hit.url: hit for hit in hits}
        documents = await asyncio.gather(*[
            asyncio.to_thread(self.fetcher.fetch, hit.url) for hit in unique_hits.values()
        ])
        for document in documents:
            await asyncio.to_thread(ingest_document, document, self.embedder, self.index, entity_ids=entity_ids)
        vector = (self.embedder.embed([question]) or [[0.0]])[0]
        evidence = await asyncio.to_thread(
            self.index.hybrid_search, question, vector,
            SearchFilters(entity_ids=entity_ids or None), self.evidence_limit,
        )
        return self._synthesize(question, memories, evidence)

    def _synthesize(self, question: str, memories: list[MemoryRecord], evidence: list[Evidence]) -> AnalystAnswer:
        context = "\n".join([*(f"Memory: {m.text}" for m in memories), *(f"Evidence: {e.text} ({e.url})" for e in evidence)])
        response = self.model.complete(ModelRequest(
            messages=[{"role": "system", "content": "Answer using only supplied evidence. Return AnalystAnswer JSON."},
                      {"role": "user", "content": f"Question: {question}\n{context}"}],
            response_schema=AnalystAnswer, max_tokens=1200, temperature=0,
        ))
        if not isinstance(response.parsed, AnalystAnswer):
            raise TypeError("analyst model did not return AnalystAnswer")
        return response.parsed
