"""Bounded, single-pass research query planning."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .domain import MemoryRecord, ResearchPlan, RunEvent
from .models import ModelRequest


class QueryPlanner:
    def __init__(self, *, model: Any | None = None, max_subqueries: int = 4, trace_writer: Any | None = None, run_id: str | None = None) -> None:
        if max_subqueries < 1:
            raise ValueError("max_subqueries must be positive")
        self.model = model
        self.max_subqueries = max_subqueries
        self.trace_writer, self.run_id = trace_writer, run_id

    def expand(self, question: str, memory: list[MemoryRecord]) -> ResearchPlan:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        if self.model is not None:
            response = self.model.complete(ModelRequest(
                messages=[{"role": "system", "content": "Return a bounded research plan. Do not expand subqueries."},
                          {"role": "user", "content": question}],
                response_schema=ResearchPlan, max_tokens=800, temperature=0,
            ))
            if response.parsed is not None:
                plan = self._normalize(response.parsed, question)
                self._trace(question, plan)
                return plan
        entities = self._entities(question, memory)
        dates = sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", question)))
        subqueries = [{"query": question, "purpose": "answer the original question"}]
        for entity in entities:
            subqueries.append({"query": f"{entity} {question}", "purpose": f"find evidence about {entity}"})
        plan = self._normalize(ResearchPlan(
            original_question=question, subqueries=subqueries, entities=entities, date_constraints=dates
        ), question)
        self._trace(question, plan)
        return plan

    def _normalize(self, plan: Any, question: str) -> ResearchPlan:
        seen: set[str] = set()
        subqueries: list[dict] = []
        for item in plan.subqueries:
            query = str(item.get("query", "")).strip()
            key = query.casefold()
            if query and key not in seen:
                seen.add(key)
                subqueries.append({**item, "query": query})
            if len(subqueries) == self.max_subqueries:
                break
        if not subqueries:
            subqueries = [{"query": question, "purpose": "answer the original question"}]
        return ResearchPlan(
            original_question=question,
            subqueries=subqueries,
            entities=list(dict.fromkeys(str(e).strip() for e in plan.entities if str(e).strip())),
            date_constraints=list(dict.fromkeys(str(d).strip() for d in plan.date_constraints if str(d).strip())),
        )

    def _trace(self, question: str, plan: ResearchPlan) -> None:
        if self.trace_writer is not None and self.run_id is not None:
            self.trace_writer.append(RunEvent(run_id=self.run_id, timestamp=datetime.now(UTC), component="query_planner", event="query_expanded", payload={"original_query": question, "queries": [item["query"] for item in plan.subqueries], "cap": self.max_subqueries}, duration_ms=None, error=None))

    @staticmethod
    def _entities(question: str, memory: list[MemoryRecord]) -> list[str]:
        candidates: list[str] = []
        for record in memory:
            for phrase in re.findall(r"\b[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*", record.text):
                if phrase.casefold() in question.casefold() and phrase not in candidates:
                    candidates.append(phrase)
        return candidates
