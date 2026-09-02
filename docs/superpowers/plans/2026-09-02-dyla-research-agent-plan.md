# Dyla Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `dyla` CLI that researches live-web questions with provider-neutral core ports, You.com web retrieval, configurable model/embedding/vector adapters, then independently audits every claim and records measurable traces.

**Architecture:** A CLI invokes a run orchestrator. The orchestrator uses a deterministic reliability layer around an analyst agent and an auditor agent. Core agents depend on neutral model, search, and vector-store protocols; You.com is selected only for web search/page retrieval, while Azure AI Search remains a supported vector-store adapter. SQLite stores entities, aliases, claims, audit results, run metadata, and feedback.

**Tech Stack:** Python 3.11+, Typer, Pydantic, asyncio, httpx, Azure OpenAI/Foundry-compatible APIs, Azure AI Search REST adapter, SQLite/FTS5, pytest, pytest-asyncio, and python-dotenv.

**Spec:** `docs/superpowers/specs/2026-09-02-dyla-research-agent-design.md`

## Global Constraints

- `dyla ask` automatically runs analyst, auditor, memory update, trace persistence, and final reporting.
- Model, auditor, embedding, vector-store, and web-provider selections are read from `DYLA_*_PROVIDER` environment variables; endpoint/API-key/model credentials remain in the environment, no secrets are committed or written to logs, and adapter errors redact them.
- The core depends on neutral protocols and must not import Bing, You.com, Azure, OpenAI, or NVIDIA SDK details.
- `DYLA_WEB_PROVIDER=you` selects the You.com `SearchProvider`; You.com is not used for models, embeddings, or vector storage. Every role also accepts a `module:function` custom plugin.
- Azure AI Search remains a supported vector-store adapter and must support keyword plus vector retrieval; dependency-free local storage is available, with Qdrant/FAISS selected when their optional adapters are installed.
- Every factual claim must have citation metadata and an auditor verdict before an answer is marked complete.
- Query expansion is one bounded step, deduplicated, traced, and executed concurrently where independent.
- Entity resolution records aliases, confidence, and unresolved ambiguity instead of silently merging entities.
- Every run writes a complete trace under `logs/`; replayable artifacts may be stored under `runs/`.
- The implementation remains CLI-first; no frontend, authentication system, distributed workers, fine-tuning, or multiple search indexes.
- Tests must use fakes/mocks for Azure and web services; live integration tests are opt-in through an explicit environment flag.

---

### Task 1: Project foundation and secure configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/dyla/__init__.py`
- Create: `src/dyla/config.py`
- Create: `tests/unit/test_config.py`
- Create: `README.md`

**Interfaces:**
- Produces `Settings` with `azure_openai_endpoint`, `azure_openai_api_key`, `azure_openai_api_version`, `azure_openai_chat_deployment`, `azure_openai_embedding_deployment`, `azure_search_endpoint`, `azure_search_api_key`, and `azure_search_index`.
- Produces `load_settings() -> Settings`.
- Produces the console entry point `dyla = dyla.cli:app`.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_load_settings_reads_required_environment(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://openai.example")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "chat")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "embed")
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example")
    monkeypatch.setenv("AZURE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("AZURE_SEARCH_INDEX", "dyla-evidence")

    settings = load_settings()

    assert settings.azure_openai_chat_deployment == "chat"
    assert settings.azure_search_index == "dyla-evidence"


def test_load_settings_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
        load_settings()
```

- [ ] **Step 2: Run `pytest tests/unit/test_config.py -q` and verify it fails because configuration does not exist.**
- [ ] **Step 3: Implement `Settings` with Pydantic settings validation and `.env` loading.**
- [ ] **Step 4: Add `.env` to `.gitignore`, put only fake values in `.env.example`, and ensure README setup never asks users to commit secrets.**
- [ ] **Step 5: Run `pytest tests/unit/test_config.py -q` and verify it passes.**

### Task 2: Domain schemas and deterministic run tracing

**Files:**
- Create: `src/dyla/domain.py`
- Create: `src/dyla/tracing.py`
- Create: `tests/unit/test_domain.py`
- Create: `tests/unit/test_tracing.py`

**Interfaces:**
- `Citation(url: str, title: str | None, source_id: str, chunk_id: str | None)`.
- `Claim(id: str, text: str, citations: list[Citation], confidence: str)`.
- `AnalystAnswer(answer: str, claims: list[Claim], limitations: list[str])`.
- `AuditVerdict(claim_id: str, status: Literal["supported", "unsupported", "contradicted", "uncited"], explanation: str, citations_checked: list[Citation])`.
- `RunEvent(run_id: str, timestamp: datetime, component: str, event: str, payload: dict, duration_ms: int | None, error: str | None)`.
- `Document(source_id: str, url: str, title: str | None, text: str, published_at: datetime | None)`.
- `EvidenceChunk(chunk_id: str, source_id: str, url: str, title: str | None, section: str | None, text: str, position: int, entity_ids: list[str], content_hash: str)`.
- `Evidence(chunk_id: str, source_id: str, url: str, title: str | None, text: str, score: float, entity_ids: list[str])`.
- `SearchHit(url: str, title: str | None, snippet: str, published_at: datetime | None)`.
- `SearchFilters(entity_ids: list[str] | None = None, source_ids: list[str] | None = None, published_after: datetime | None = None, published_before: datetime | None = None)`.
- `MemoryRecord(id: str, kind: str, text: str, entity_ids: list[str], source_ids: list[str], verified: bool)`.
- `Budget(deadline_seconds: float, max_model_tokens: int, max_cost: float, max_web_requests: int)`.
- `AgentInput(question: str, context: dict)` and `AgentResult(data: BaseModel, metrics: dict)`.
- `ResearchPlan(original_question: str, subqueries: list[dict], entities: list[str], date_constraints: list[str])`.
- `Metrics(input_tokens: int, output_tokens: int, estimated_cost: float, duration_ms: int, searches: int, fetches: int, memory_hits: int, parallel_calls: int)`.
- `TraceWriter.append(event: RunEvent) -> None`.

- [ ] **Step 1: Write failing tests for schema validation and JSONL trace writing.**
- [ ] **Step 2: Run the focused tests and verify failure.**
- [ ] **Step 3: Implement Pydantic domain models and a trace writer that appends one JSON object per line under `logs/<run_id>.jsonl`.**
- [ ] **Step 4: Redact keys matching `api_key`, `authorization`, `token`, or `secret` before writing payloads.**
- [ ] **Step 5: Run the focused tests and verify they pass.**

### Task 3: SQLite application memory and entity resolution

**Files:**
- Create: `src/dyla/memory.py`
- Create: `src/dyla/entities.py`
- Create: `tests/unit/test_memory.py`
- Create: `tests/unit/test_entities.py`

**Interfaces:**
- `MemoryStore.initialize() -> None`.
- `MemoryStore.upsert_entity(canonical_name: str, entity_type: str) -> str`.
- `MemoryStore.add_alias(entity_id: str, alias: str, confidence: float) -> None`.
- `MemoryStore.search_memory(query: str, limit: int = 10) -> list[MemoryRecord]`.
- `MemoryStore.save_claim(claim: Claim, verdict: AuditVerdict | None) -> None`.
- `EntityResolver.resolve(mention: str, context: str) -> ResolvedEntity`.
- `ResolvedEntity(entity_id: str | None, canonical_name: str | None, confidence: float, status: Literal["resolved", "ambiguous", "unknown"], candidates: list[str])`.

- [ ] **Step 1: Write tests for schema creation, alias reuse, exact matching, fuzzy matching, and ambiguous matches.**
- [ ] **Step 2: Run `pytest tests/unit/test_memory.py tests/unit/test_entities.py -q` and verify failure.**
- [ ] **Step 3: Implement SQLite tables for entities, aliases, claims, audit verdicts, sources, and research warnings using parameterized SQL.**
- [ ] **Step 4: Implement deterministic normalization, exact alias lookup, fuzzy candidate lookup, and an explicit ambiguous result.**
- [ ] **Step 5: Run focused tests and verify they pass.**

### Task 4: Azure model and embedding adapters

**Files:**
- Create: `src/dyla/models.py`
- Create: `src/dyla/azure_models.py`
- Create: `tests/unit/test_azure_models.py`

**Interfaces:**
- `ModelRequest(messages: list[dict[str, str]], response_schema: type[BaseModel] | None, max_tokens: int, temperature: float)`.
- `ModelResponse(text: str, parsed: BaseModel | None, input_tokens: int, output_tokens: int, latency_ms: int)`.
- `ModelProvider.complete(request: ModelRequest) -> ModelResponse`.
- `EmbeddingProvider.embed(texts: list[str]) -> list[list[float]]`.

- [ ] **Step 1: Write tests using fake Azure HTTP responses for structured chat output, embedding batches, transient retry, and secret redaction.**
- [ ] **Step 2: Run the focused tests and verify failure.**
- [ ] **Step 3: Implement Azure adapters with `httpx`, bounded exponential backoff for 429/5xx, request timeouts, and response usage parsing.**
- [ ] **Step 4: Implement content-hash embedding caching in SQLite or a local cache table so unchanged chunks are not re-embedded.**
- [ ] **Step 5: Run focused tests and verify they pass.**

### Task 5: Web tools, normalization, chunking, and Azure AI Search index

**Files:**
- Create: `src/dyla/web.py`
- Create: `src/dyla/chunking.py`
- Create: `src/dyla/search.py`
- Create: `src/dyla/ingest.py`
- Create: `tests/unit/test_web.py`
- Create: `tests/unit/test_chunking.py`
- Create: `tests/unit/test_search.py`
- Create: `tests/integration/test_azure_search.py`

**Interfaces:**
- `WebSearcher.search(query: str, limit: int = 5) -> list[SearchHit]`.
- `PageFetcher.fetch(url: str) -> Document`.
- `chunk_document(document: Document, max_chars: int = 5000, overlap_chars: int = 500) -> list[EvidenceChunk]`.
- `SearchIndex.ensure_index() -> None`.
- `SearchIndex.upsert(chunks: list[EvidenceChunk]) -> None`.
- `SearchIndex.hybrid_search(query: str, vector: list[float], filters: SearchFilters, limit: int) -> list[Evidence]`.

- [ ] **Step 1: Write tests for URL validation, boilerplate removal, heading-aware chunking, overlap, content hashes, and citation metadata preservation.**
- [ ] **Step 2: Write mocked search tests asserting keyword/vector requests and metadata filters.**
- [ ] **Step 3: Run focused tests and verify failure.**
- [ ] **Step 4: Implement web search/fetch adapters with size limits, HTTPS-only external URL validation, and normalized documents.**
- [ ] **Step 5: Implement heading/paragraph chunking with URL, title, section, source ID, position, entity IDs, date, and content hash on every chunk.**
- [ ] **Step 6: Implement Azure AI Search index creation, vector field dimensions read from configuration, hybrid retrieval, and upsert batching.**
- [ ] **Step 7: Gate live integration tests behind `DYLA_RUN_LIVE_TESTS=1`, run unit tests, and verify they pass.**

### Task 6: Agent runtime, query expansion, and analyst

**Files:**
- Create: `src/dyla/agent_runtime.py`
- Create: `src/dyla/query_planner.py`
- Create: `src/dyla/analyst.py`
- Create: `tests/unit/test_agent_runtime.py`
- Create: `tests/unit/test_query_planner.py`
- Create: `tests/unit/test_analyst.py`

**Interfaces:**
- `ToolRegistry.register(name: str, handler: Callable[..., Awaitable[Any]]) -> None`.
- `AgentRuntime.run(agent: Agent, input: AgentInput, budget: Budget) -> AgentResult`.
- `QueryPlanner.expand(question: str, memory: list[MemoryRecord]) -> ResearchPlan`.
- `AnalystAgent.run(question: str, run_id: str) -> AnalystAnswer`.

- [ ] **Step 1: Write tests for schema validation, tool registration, budget rejection, bounded one-step query expansion, duplicate query removal, and concurrent independent searches.**
- [ ] **Step 2: Run focused tests and verify failure.**
- [ ] **Step 3: Implement the runtime with injected model, retriever, tools, memory, budget, and trace writer dependencies.**
- [ ] **Step 4: Implement planner output containing original question, subqueries, purposes, entities, and date constraints; cap expansion at a configured maximum.**
- [ ] **Step 5: Implement analyst retrieval: resolve entities, retrieve memory, expand queries, run searches concurrently, fetch/index pages, retrieve evidence, cross-check weak claims, and synthesize a structured answer.**
- [ ] **Step 6: Run focused tests and verify they pass.**

### Task 7: Auditor and reliability/quality gates

**Files:**
- Create: `src/dyla/auditor.py`
- Create: `src/dyla/reliability.py`
- Create: `tests/unit/test_auditor.py`
- Create: `tests/unit/test_reliability.py`

**Interfaces:**
- `AuditorAgent.run(answer: AnalystAnswer, run_id: str) -> list[AuditVerdict]`.
- `QualityGate.validate(answer: AnalystAnswer, verdicts: list[AuditVerdict], trace_path: Path) -> QualityResult`.
- `QualityResult(status: Literal["complete", "incomplete", "unaudited"], issues: list[str])`.

- [ ] **Step 1: Write tests for supported, unsupported, contradicted, and uncited claims; fetch failures; auditor failure; and quality-gate status decisions.**
- [ ] **Step 2: Run focused tests and verify failure.**
- [ ] **Step 3: Implement independent citation fetching and claim comparison without trusting analyst evidence summaries.**
- [ ] **Step 4: Implement bounded retries, per-stage timeouts, partial trace persistence, and explicit incomplete/unaudited states.**
- [ ] **Step 5: Implement evidence gates requiring citations, retrievable sources, a verdict for every claim, visible contradiction markers, and a saved trace.**
- [ ] **Step 6: Store auditor findings and research warnings in memory for later questions.**
- [ ] **Step 7: Run focused tests and verify they pass.**

### Task 8: Provider-neutral web boundary and You.com adapter

**Files:**
- Create: `src/dyla/ports.py`
- Create: `src/dyla/provider_factory.py`
- Modify: `src/dyla/web.py`
- Modify: `src/dyla/config.py`
- Modify: `src/dyla/analyst.py`
- Modify: `src/dyla/auditor.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-02-dyla-research-agent-design.md`
- Modify: `docs/superpowers/plans/2026-09-02-dyla-research-agent-plan.md`
- Create: `tests/unit/test_web.py`
- Create: `tests/unit/test_config.py`

**Interfaces:**
- `SearchProvider.search(query: str, limit: int = 5) -> list[SearchHit]`.
- `SearchProvider.fetch(url: str) -> Document`.
- `YouResearchProvider.search(query: str, limit: int = 5) -> list[SearchHit]`.
- `YouResearchProvider.fetch(url: str) -> Document`.
- `Settings.dyla_web_provider`, `Settings.you_api_key`, `Settings.you_search_endpoint`, and `Settings.you_contents_endpoint`.

- [x] **Step 1: Write mocked tests for You search normalization, contents normalization, malformed payloads, authentication failures, and provider-neutral protocol conformance.**
- [x] **Step 2: Write regression tests for HTTPS-only URLs, private DNS results, unsafe redirects, response byte limits, and unsupported content types.**
- [x] **Step 3: Write configuration tests for provider selection and required You.com settings, using fake values only.**
- [x] **Step 4: Run the focused tests and verify they fail for the missing adapter/configuration behavior.**
- [x] **Step 5: Implement `SearchProvider` and `YouResearchProvider` with `httpx`, API-key authentication, defensive response normalization, bounded contents handling, and clear non-secret errors.**
- [x] **Step 6: Preserve and reuse existing URL validation, redirect revalidation, DNS/public-IP checks, streaming byte limits, and text extraction for page fetching.**
- [x] **Step 7: Refactor core-facing annotations/names to neutral search-provider terminology without changing the Azure `SearchIndex` adapter.**
- [x] **Step 8: Add provider settings and fake `.env.example` entries; document the provider-neutral decision and offline test contract.**
- [x] **Step 9: Run the focused tests and then the full offline suite; append results to `.superpowers/sdd/2026-09-02-dyla-research-agent-plan/provider-adapter-report.md`.**
- [x] **Step 10: Commit the completed provider-adapter slice.**

Review follow-up: the provider registry/factory is the only composition boundary. Compatible model and embedding adapters normalize OpenAI-style endpoints, custom providers load through `module:function`, and all You API responses use the shared bounded request path. The vector-store boundary supports local/Azure and optional Qdrant/FAISS choices without exposing vendor details to the core.

### Task 9: Orchestrator and `dyla` CLI

**Files:**
- Create: `src/dyla/orchestrator.py`
- Create: `src/dyla/cli.py`
- Create: `tests/unit/test_orchestrator.py`
- Create: `tests/integration/test_cli.py`

**Interfaces:**
- `RunOrchestrator.ask(question: str) -> RunResult`.
- `RunResult(run_id: str, answer: AnalystAnswer, verdicts: list[AuditVerdict], quality: QualityResult, metrics: Metrics)`.
- Typer commands: `ask`, `analyst`, `audit`, `evaluate`, `memory list`, and `replay`.

- [ ] **Step 1: Write orchestrator tests asserting analyst → auditor → memory → trace → quality ordering and preservation of original analyst output.**
- [ ] **Step 2: Write CLI tests using fake dependencies for exit codes and output containing citations, verdict counts, status, and run path.**
- [ ] **Step 3: Run focused tests and verify failure.**
- [ ] **Step 4: Implement dependency composition from `Settings`, the orchestrator lifecycle, and metrics aggregation.**
- [ ] **Step 5: Implement human-readable CLI output plus JSON output option for automation.**
- [ ] **Step 6: Implement `replay` from saved trace/artifact data without new Azure or web calls.**
- [ ] **Step 7: Run focused tests and verify they pass.**

### Task 9: Eight-question evaluation harness and feedback loop

**Files:**
- Create: `evaluation/questions.yaml`
- Create: `src/dyla/evaluation.py`
- Create: `tests/unit/test_evaluation.py`
- Create: `reports/.gitkeep`
- Modify: `README.md`
- Create: `DECISIONS.md`

**Interfaces:**
- `EvaluationRunner.run(question_set: Path) -> EvaluationReport`.
- `EvaluationReport.rows: list[EvaluationRow]`.
- `dyla evaluate` writes `reports/evaluation.json` and `reports/evaluation.md`.

- [ ] **Step 1: Write tests for question ordering, entity reuse, metric aggregation, cost trend calculation, and feedback-warning reuse.**
- [ ] **Step 2: Run focused tests and verify failure.**
- [ ] **Step 3: Add eight increasing-difficulty questions, including at least two that reuse earlier entities and one conflicting/incomplete-evidence question.**
- [ ] **Step 4: Implement evaluation execution and report claim verdicts, citation coverage, latency, tokens, estimated Azure cost, searches, fetches, memory hits, and parallelism.**
- [ ] **Step 5: Implement the feedback loop that stores auditor findings as warnings and includes relevant warnings in later analyst context.**
- [ ] **Step 6: Write `DECISIONS.md` with rejected alternatives, trade-offs, test methodology, known breaks, and a two-week follow-up plan.**
- [ ] **Step 7: Update README with clean-checkout setup, Azure environment variables, Azure AI Search index setup, commands, test commands, and expected output.**
- [ ] **Step 8: Run `pytest -q` and verify all offline tests pass.**

### Task 10: Final verification and submission hygiene

**Files:**
- Modify: `README.md`
- Modify: `DECISIONS.md`
- Verify: `.env.example`, `.gitignore`, `logs/`, `reports/`, `runs/`

- [ ] **Step 1: Run a secret scan over tracked files and confirm no Azure key, token, or endpoint credential is present.**
- [ ] **Step 2: Run the CLI help command from a clean environment and verify setup errors identify missing variable names without printing values.**
- [ ] **Step 3: Run unit tests with live services disabled and verify they pass.**
- [ ] **Step 4: If Azure resources and credentials are available, run the opt-in integration smoke test for embedding, indexing, hybrid retrieval, and one end-to-end question.**
- [ ] **Step 5: Run the eight-question evaluation, inspect the generated report, and record honest limitations and failures in `DECISIONS.md`.**
- [ ] **Step 6: Confirm `/logs` contains the required AI coding-session exports separately from application run traces.**
- [ ] **Step 7: Perform the clean-checkout README walkthrough and record the elapsed setup time.**
