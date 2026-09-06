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
from .policies import DEFAULT_POLICIES, Policies
from .ports import SearchProvider
from .query_planner import QueryPlanner
from .verification import corroborates, extract_numbers, extract_years, on_topic

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


def _restates_rejected_claim(text: str, rejected: list[str], threshold: float | None = None) -> bool:
    """True when `text` substantially restates a previously rejected claim.

    Substring matching was the earlier approach and is too weak: a reworded
    restatement of a rejected claim slips straight through. Comparing
    content-word fingerprints catches paraphrase, and the threshold
    (``Policies.rejected_claim_overlap``, 0.8) keeps a merely adjacent claim
    about the same entity from being suppressed.
    """
    if threshold is None:
        threshold = DEFAULT_POLICIES.rejected_claim_overlap
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
        max_subqueries: int | None = None, search_limit: int | None = None, evidence_limit: int | None = None,
        trace_writer: Any | None = None, reuse_enabled: bool | None = None,
        reuse_min_sources: int | None = None, reuse_min_score: float | None = None, min_evidence: int | None = None,
        policies: Policies | None = None,
        shadow_policies: Policies | None = None,
    ) -> None:
        # Behaviour thresholds live in Policies (ADR-0001 increment 1); the
        # per-knob keyword arguments predate it and still work — an explicitly
        # passed value overrides the policy for that one knob, so existing call
        # sites and tests are unchanged. Nothing here reads environment
        # variables: changing policy is a tested code change, not a flag.
        #
        # ``shadow_policies`` (ADR-0001 increment 2) runs a candidate policy
        # alongside the live one: decisions are traced under both, behaviour
        # follows only the live policy. It never mutates behaviour or metrics.
        policy = policies if policies is not None else DEFAULT_POLICIES
        self.model, self.resolver, self.memory = model, resolver, memory
        self.searcher, self.fetcher, self.index = searcher, fetcher, index
        self.policies = policy
        self.shadow_policies = shadow_policies
        self.planner = planner or QueryPlanner(
            max_subqueries=max_subqueries if max_subqueries is not None else policy.max_subqueries
        )
        self.trace_writer = trace_writer
        self.search_limit = search_limit if search_limit is not None else policy.search_limit
        self.evidence_limit = evidence_limit if evidence_limit is not None else policy.evidence_limit
        self.reuse_enabled = reuse_enabled if reuse_enabled is not None else policy.reuse_enabled
        self.reuse_min_sources = reuse_min_sources if reuse_min_sources is not None else policy.reuse_min_sources
        self.reuse_min_score = reuse_min_score if reuse_min_score is not None else policy.reuse_min_score
        self.min_evidence = min_evidence if min_evidence is not None else policy.min_evidence
        self.metrics = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "duration_ms": 0,
                        "searches": 0, "fetches": 0, "memory_hits": 0, "parallel_calls": 0,
                        "failed_searches": 0, "failed_fetches": 0, "failed_ingestions": 0,
                        "claims_blocked_by_audit_feedback": 0,
                        "corroboration_searches": 0, "corroboration_fetches": 0,
                        "searches_skipped": 0, "evidence_reused": 0, "reuse_corrections": 0,
                        "embedding_tokens": 0}
        self.embedder = _CountingEmbedder(embedder, self.metrics)

    async def run(self, question: str, run_id: str) -> AnalystAnswer:
        started = time.monotonic()
        if isinstance(self.planner, QueryPlanner):
            self.planner.run_id = run_id
            if self.trace_writer is not None:
                self.planner.trace_writer = self.trace_writer
        memories = await asyncio.to_thread(self.memory.search_memory, question, self.policies.memory_search_limit)
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
        # The plan is the first thing the brief asks to see in a run log, and it
        # was the one thing missing: the planner traced its own query expansion,
        # but nothing recorded the entities, what they resolved to, or the date
        # constraints the plan would be executed under.
        self._trace(run_id, "plan_created", {
            "subqueries": [item.get("query") for item in plan.subqueries],
            "entities": list(plan.entities),
            "resolved_entities": {name: entity_id for name, entity_id in resolved.items()},
            "unresolved_entities": [
                entity for entity in plan.entities if entity.casefold() not in resolved
            ],
            "date_constraints": list(plan.date_constraints),
            "reuse_enabled": self.reuse_enabled,
        })
        if entity_ids:
            entity_memory = []
            for entity in plan.entities:
                entity_memory.extend(await asyncio.to_thread(self.memory.search_memory, entity, self.policies.memory_search_limit))
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
        self._trace(run_id, "evidence_selected", {
            "count": len(evidence),
            "source_ids": list(dict.fromkeys(
                getattr(item, "source_id", None) for item in evidence
            )),
            "urls": list(dict.fromkeys(getattr(item, "url", None) for item in evidence)),
            "searches_skipped_by_reuse": len(reuse["skipped"]),
            "queries_run_against_web": len(reuse["to_run"]),
        })
        answer = await asyncio.to_thread(self._synthesize, question, memories, evidence, [*collection_limitations, *date_limitations], run_id)
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

        With ``shadow_policies`` set (ADR-0001 increment 2), the same probe
        results are re-classified under the shadow policy and the comparison is
        traced as ``reuse_shadow_evaluated`` — no extra retrievals and no
        behaviour change. The shadow decision is an honest estimate, not a
        simulation: it reuses probe results retrieved under the live
        ``evidence_limit``, so a shadow policy that changes that knob is
        approximated. The event is emitted even when the two agree, so a later
        live run can measure agreement rates, not just divergences.
        """
        subqueries = list(plan.subqueries)
        if not entity_ids or not self.reuse_enabled:
            return {"to_run": subqueries, "skipped": [], "covered": []}

        probes: dict[str, list] = {}
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
            probes[entity_id] = prior
            if self._is_covered(prior, self.reuse_min_sources, self.reuse_min_score):
                covered.append(entity_id)

        self._trace_shadow(run_id, entity_ids, probes, covered, plan, resolved, subqueries)

        if not covered:
            self._trace(run_id, "memory_reuse_evaluated", {"covered_entities": 0, "skipped_queries": 0})
            return {"to_run": subqueries, "skipped": [], "covered": []}

        covered_set = set(covered)
        to_run, skipped = self._classify_subqueries(subqueries, covered_set, entity_ids, plan, resolved)

        self.metrics["searches_skipped"] += len(skipped)
        self.metrics["evidence_reused"] += len(covered)
        self._trace(run_id, "memory_reuse_evaluated", {
            "covered_entities": len(covered),
            "skipped_queries": [item["query"] for item in skipped],
            "remaining_queries": [item["query"] for item in to_run],
        })
        return {"to_run": to_run, "skipped": skipped, "covered": covered}

    @staticmethod
    def _is_covered(prior: list, min_sources: int, min_score: float) -> bool:
        sources = {item.source_id for item in prior if item.score >= min_score}
        return len(sources) >= min_sources

    def _classify_subqueries(
        self, subqueries: list[dict], covered_set: set[str],
        entity_ids: list[str], plan: Any, resolved: dict[str, str],
    ) -> tuple[list[dict], list[dict]]:
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
        return to_run, skipped

    def _trace_shadow(
        self, run_id: str, entity_ids: list[str], probes: dict[str, list],
        live_covered: list[str], plan: Any, resolved: dict[str, str],
        subqueries: list[dict],
    ) -> None:
        shadow = self.shadow_policies
        if shadow is None:
            return
        if not shadow.reuse_enabled:
            # A candidate that disables reuse never skips anything; classifying
            # its probes under the thresholds would describe a policy it is not.
            shadow_covered: set[str] = set()
            shadow_skipped: list[dict] = []
        else:
            shadow_covered = {
                entity_id for entity_id, prior in probes.items()
                if self._is_covered(prior, shadow.reuse_min_sources, shadow.reuse_min_score)
            }
            _, shadow_skipped = self._classify_subqueries(
                subqueries, shadow_covered, entity_ids, plan, resolved,
            )
        _, live_skipped = self._classify_subqueries(
            subqueries, set(live_covered), entity_ids, plan, resolved,
        )
        self._trace(run_id, "reuse_shadow_evaluated", {
            "live": {
                "reuse_min_sources": self.reuse_min_sources,
                "reuse_min_score": self.reuse_min_score,
                "covered_entities": len(live_covered),
                "skipped_queries": [item["query"] for item in live_skipped],
            },
            "shadow": {
                "reuse_min_sources": shadow.reuse_min_sources,
                "reuse_min_score": shadow.reuse_min_score,
                "covered_entities": len(shadow_covered),
                "skipped_queries": [item["query"] for item in shadow_skipped],
            },
            "divergent": live_skipped != shadow_skipped,
        })

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
                if "budget exceeded" in str(batch):
                    # A budget stop is not a provider failure: recording it as
                    # one misattributed the breach as an ordinary search outage
                    # and hid it from the run report.
                    limitations.append(
                        f"Web search for query '{item['query']}' was skipped because "
                        "the run's web-request budget was exhausted."
                    )
                    continue
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
                if "budget exceeded" in str(document):
                    limitations.append(
                        f"Page fetch for {hit.url} was skipped because the run's "
                        "web-request budget was exhausted."
                    )
                    continue
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
            # The filter is a continuous range from the first constrained year
            # through the last, so sources from intermediate years are admitted
            # too. The limitation text must say the range, not imply a set of
            # individual years the filter does not enforce.
            through = f" and {years[-1]}" if len(years) > 1 else ""
            limitations.append(
                f"Date filter applied to sources published from {years[0]}{through}; "
                "sources without a published date were also considered."
            )
        return SearchFilters(entity_ids=entity_ids or None, published_after=after, published_before=before), limitations

    def _synthesize(self, question: str, memories: list[MemoryRecord], evidence: list[Evidence], date_limitations: list[str], run_id: str = "") -> AnalystAnswer:
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
        # Every rejection below is a course correction -- the analyst overruling
        # its own model -- and none of them used to appear in the trace. They
        # were folded into the answer's limitations text, where a reader has to
        # infer what happened from prose. Each now emits a machine-readable
        # event with a stable reason code, because "where it changed course
        # after something failed" is the part of the log the brief asks for by
        # name.
        for claim in answer.claims:
            if not claim.citations:
                limitations.append(f"Claim {claim.id} was rejected because it had no citations.")
                self._trace(run_id, "claim_rejected", {
                    "claim_id": claim.id, "reason": "no_citations",
                    "detail": "The model asserted a claim without citing anything.",
                    "claim_text": claim.text,
                })
                continue
            mapped = [citation for citation in claim.citations if self._citation_maps(citation, evidence_keys)]
            if len(mapped) != len(claim.citations):
                limitations.append(f"Claim {claim.id} was rejected because a citation did not map to retrieved evidence.")
                self._trace(run_id, "claim_rejected", {
                    "claim_id": claim.id, "reason": "citation_not_in_evidence",
                    "detail": "A cited source was never retrieved during this run, so the "
                              "citation cannot be trusted to support the claim.",
                    "claim_text": claim.text,
                    "unmapped_citations": [
                        citation.url for citation in claim.citations
                        if not self._citation_maps(citation, evidence_keys)
                    ],
                })
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
                self._trace(run_id, "claim_rejected", {
                    "claim_id": claim.id, "reason": "blocked_by_audit_feedback",
                    "detail": "An earlier audit found this same assertion unsupported by its "
                              "cited sources, and the model restated it anyway.",
                    "claim_text": claim.text,
                })
                continue
            if self._needs_corroboration(claim, memories):
                outcome = self._corroborate(claim, run_id)
                # The cross-check is a tool call like any other: accepted or
                # not, the trace records what was checked and what decided it.
                # Rejections were already visible via claim_rejected, but an
                # accepted cross-check used to leave no event at all -- 24
                # fetches per suite run with no record of what they confirmed.
                self._trace(run_id, "claim_corroborated", {
                    "claim_id": claim.id, "accepted": outcome["accepted"],
                    "source_url": outcome["source_url"],
                    "sources_checked": outcome["checked"],
                    "detail": outcome["detail"],
                })
                if not outcome["accepted"]:
                    limitations.append(
                        f"Claim {claim.id} was rejected for lacking independent evidence."
                    )
                    self._trace(run_id, "claim_rejected", {
                        "claim_id": claim.id, "reason": "insufficient_corroboration",
                        "detail": outcome["detail"],
                        "claim_text": claim.text,
                        "confidence": claim.confidence,
                        "distinct_sources": len({citation.source_id for citation in mapped}),
                        "corroboration_sources_checked": outcome["checked"],
                    })
                    continue
            valid_claims.append(claim)
        self._trace(run_id, "answer_synthesized", {
            "claims_proposed": len(answer.claims),
            "claims_kept": len(valid_claims),
            "claims_rejected": len(answer.claims) - len(valid_claims),
            "bailed_out": not answer.claims or not valid_claims,
        })
        if not answer.claims or not valid_claims:
            # Saying "not found" rather than guessing is a required behaviour,
            # so it is traced as a decision rather than inferred from an empty
            # claim list.
            self._trace(run_id, "answer_withheld", {
                "reason": "no_claim_survived_validation" if answer.claims else "model_proposed_no_claims",
                "detail": "Answering was declined rather than guessing.",
            })
            return AnalystAnswer(answer="Insufficient evidence.", claims=[], limitations=list(dict.fromkeys([*limitations, *date_limitations])))
        return AnalystAnswer(answer=answer.answer, claims=valid_claims, limitations=list(dict.fromkeys([*limitations, *date_limitations])))

    def _needs_corroboration(self, claim: Any, memories: list[MemoryRecord]) -> bool:
        """Decide whether a claim must be cross-checked against a second source.

        Deliberately **not** keyed on the model's self-reported confidence
        alone. A model that labels every claim "high" is exactly the failure
        mode a confidence-keyed cross-check cannot see, so the gates are
        properties the model does not control:

        * the claim rests on a single distinct cited source;
        * no previously *supported* claim in memory restates it (the auditor
          already verified that assertion against independently fetched
          sources, which is stronger evidence than a fresh cross-check);
        * and it carries a material fact — a figure or a year — or the model
          itself flagged low confidence.

        Confidence survives only as one trigger among equals, never as the
        whole decision.
        """
        distinct_sources = {citation.source_id for citation in claim.citations}
        if len(distinct_sources) != 1:
            return False
        if self._restated_by_supported_memory(claim.text, memories):
            return False
        if extract_numbers(claim.text) or extract_years(claim.text):
            return True
        return claim.confidence.casefold() in {"low", "medium", "weak"}

    def _restated_by_supported_memory(self, text: str, memories: list[MemoryRecord]) -> bool:
        """True when a prior run's *supported* claim covers this assertion.

        Both conditions must hold: the wording must restate the stored claim
        (fingerprint overlap), and the stored claim must state the same
        material facts. The fingerprint ignores numbers by construction, so
        wording alone must not bless a claim whose figure differs from the
        verified one — a stored "1,62,990 crore" claim does not cover a new
        "1,53,670 crore" claim even though every word matches.
        """
        prior = [
            record.text for record in memories
            if record.kind == "claim" and record.text
            and record.verified
            and (record.verdict_status or "") == "supported"
        ]
        return any(
            _restates_rejected_claim(text, [record_text]) and corroborates(text, record_text)
            for record_text in prior
        )

    def _corroborate(self, claim: Any, run_id: str = "") -> dict:
        """Cross-check the claim against a second, independently fetched source.

        Returns ``{"accepted": bool, "source_url": str | None, "detail": str,
        "checked": int}``.

        The corroborating page is evidence for *this* decision only. It is
        never attached to ``claim.citations`` and never returned as a
        ``Citation``: the auditor later re-fetches exactly the sources the
        claim cites, and making it verify against a paraphrased page it was
        never asked about manufactures false ``contradicted`` verdicts.

        Every non-cited candidate within ``search_limit`` is checked, not just
        the first two: a near-verbatim page that disagrees can outrank the
        agreeing one, and stopping early would reject claims that do have
        independent support.

        Failures fail open — a search outage or an unreadable page is not
        evidence against the claim, and the auditor still verifies the cited
        source — except for claims the model itself flagged low confidence:
        their own uncertainty plus no independent confirmation is the one case
        that rejects without on-topic counter-evidence.
        """
        cited_urls = {citation.url for citation in claim.citations}
        try:
            hits = self.searcher.search(claim.text, self.search_limit)
        except Exception:
            return {
                "accepted": True, "source_url": None,
                "detail": "The cross-check search failed; the claim is left to the auditor.",
                "checked": 0,
            }
        self.metrics["corroboration_searches"] += 1
        relevant_but_silent: list[str] = []
        for hit in hits:
            if hit.url in cited_urls:
                continue
            self.metrics["corroboration_fetches"] += 1
            try:
                document = self.fetcher.fetch(hit.url)
            except Exception:
                continue
            text = str(getattr(document, "text", "") or "")
            if not text:
                continue
            if not on_topic(claim.text, text):
                continue
            if corroborates(claim.text, text):
                return {
                    "accepted": True, "source_url": hit.url,
                    "detail": f"Cross-checked against {hit.url}, which independently "
                              "states the claim's facts.",
                    "checked": len(relevant_but_silent) + 1,
                }
            relevant_but_silent.append(hit.url)
        if relevant_but_silent:
            return {
                "accepted": False, "source_url": None,
                "detail": "Independent sources on this claim's subject were fetched "
                          "(" + ", ".join(relevant_but_silent) + ") but none states the "
                          "claim's figure; a single cited source is not enough for a "
                          "figure of this kind.",
                "checked": len(relevant_but_silent),
            }
        low_confidence = claim.confidence.casefold() in {"low", "medium", "weak"}
        if low_confidence:
            return {
                "accepted": False, "source_url": None,
                "detail": "No independent source on this claim's subject could be found, "
                          "and the model itself flagged the claim "
                          f"{claim.confidence!r} confidence.",
                "checked": 0,
            }
        return {
            "accepted": True, "source_url": None,
            "detail": "No independent source on this claim's subject was found; the claim "
                      "is left to the auditor.",
            "checked": 0,
        }

    @staticmethod
    def _citation_maps(citation: Citation, keys: set[tuple[str, str, str | None]]) -> bool:
        return (citation.url, citation.source_id, citation.chunk_id) in keys or any(
            url == citation.url and source == citation.source_id and chunk is None for url, source, chunk in keys
        )
