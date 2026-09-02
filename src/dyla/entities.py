"""Deterministic entity resolution over application-memory entities."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel

from .memory import MemoryStore, normalize_text


class ResolvedEntity(BaseModel):
    entity_id: str | None
    canonical_name: str | None
    confidence: float
    status: Literal["resolved", "ambiguous", "unknown"]
    candidates: list[str]


class EntityResolver:
    def __init__(
        self,
        store: MemoryStore,
        *,
        fuzzy_threshold: float = 0.55,
        ambiguity_margin: float = 0.08,
    ) -> None:
        if not 0.0 <= fuzzy_threshold <= 1.0:
            raise ValueError("fuzzy_threshold must be between 0 and 1")
        if not 0.0 <= ambiguity_margin <= 1.0:
            raise ValueError("ambiguity_margin must be between 0 and 1")
        self.store = store
        self.fuzzy_threshold = fuzzy_threshold
        self.ambiguity_margin = ambiguity_margin

    def resolve(self, mention: str, context: str) -> ResolvedEntity:
        del context  # Resolution is deliberately deterministic and context-independent.
        normalized = normalize_text(mention).strip(".,;:!?()[]{}\"'")
        if not normalized:
            return ResolvedEntity(
                entity_id=None, canonical_name=None, confidence=0.0,
                status="unknown", candidates=[]
            )

        exact = self.store.find_entities(normalized)
        if len(exact) == 1:
            row = exact[0]
            return ResolvedEntity(
                entity_id=row["id"], canonical_name=row["canonical_name"],
                confidence=1.0, status="resolved", candidates=[row["canonical_name"]]
            )
        if len(exact) > 1:
            names = sorted({row["canonical_name"] for row in exact}, key=str.casefold)
            return ResolvedEntity(
                entity_id=None, canonical_name=None, confidence=1.0,
                status="ambiguous", candidates=names
            )

        scores: dict[str, tuple[float, str, str]] = {}
        for row in self.store.entity_candidates():
            candidate = row["candidate"]
            score = SequenceMatcher(None, normalized, candidate).ratio() * row["candidate_confidence"]
            current = scores.get(row["id"])
            value = (score, row["canonical_name"], row["id"])
            if current is None or value[0] > current[0]:
                scores[row["id"]] = value

        ranked = sorted(scores.values(), key=lambda item: (-item[0], item[1].casefold(), item[2]))
        if not ranked or ranked[0][0] < self.fuzzy_threshold:
            return ResolvedEntity(
                entity_id=None, canonical_name=None,
                confidence=ranked[0][0] if ranked else 0.0,
                status="unknown", candidates=[]
            )
        top = ranked[0]
        close = [item[1] for item in ranked if top[0] - item[0] <= self.ambiguity_margin]
        if len(close) > 1:
            return ResolvedEntity(
                entity_id=None, canonical_name=None, confidence=top[0],
                status="ambiguous", candidates=close
            )
        return ResolvedEntity(
            entity_id=top[2], canonical_name=top[1], confidence=top[0],
            status="resolved", candidates=[top[1]]
        )
