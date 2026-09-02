# Dyla Research Agent Design

**Date:** 2026-09-02  
**Status:** Proposed and reviewed in conversation

## Goal

Build `dyla`, a CLI-first research system for Problem 3 of the take-home assignment. `dyla` answers live-web research questions with citations, then automatically runs an independent auditor that verifies every claim. The system records complete traces, maintains reusable entity/source memory, and reports cost, latency, and evidence quality.

The implementation is intentionally scoped to the 12–15 hour assignment window. It prioritizes a complete, explainable core over a frontend, distributed deployment, or a complex autonomous framework.

## User experience

The primary command is:

```bash
dyla ask "Which three Indian jewellery retailers opened the most new stores in the last two years?"
```

This command runs the analyst, auditor, memory update, trace persistence, and final reporting automatically.

Supporting commands:

```bash
dyla analyst "..."                  # analyst-only debugging
dyla audit runs/run-001.json           # audit a saved answer
dyla evaluate                          # run the eight-question suite
dyla memory list                       # inspect accumulated memory
dyla replay runs/run-001.json         # replay without new web/model calls
```

The final output preserves the original analyst answer and visibly reports audit findings. The auditor never silently rewrites the answer.

## Architecture

```text
CLI
  |
  v
Run Orchestrator
  |
  v
Reliability / Quality Layer
  |
  +--> Analyst Agent
  |      +--> Planner
  |      +--> Memory Retriever
  |      +--> Web Search Tool
  |      +--> Page Fetch Tool
  |      +--> Evidence Extractor
  |      +--> Answer Synthesizer
  |
  +--> Auditor Agent
  |      +--> Claim Extractor
  |      +--> Citation Verifier
  |      +--> Verdict Generator
  |
  +--> Agent Runtime
  +--> Query Expansion
  +--> Entity Resolution
  +--> Hybrid Retrieval
  |      +--> Embedding Provider
  |      +--> Azure AI Search
  |      +--> Citation-Preserving Chunks
  +--> Run Recorder
  +--> SQLite Application Memory
  +--> Cost and Latency Metrics
```

### CLI layer

Parses commands and options, loads configuration, prints human-readable output, and returns useful exit codes. It contains no agent logic.

### Run orchestrator

Coordinates one complete question lifecycle:

1. Create a run ID and budgets.
2. Retrieve relevant memory.
3. Run the analyst.
4. Run the auditor against the analyst output.
5. Persist trace, metrics, and memory updates.
6. Render the final answer and audit summary.

### Agent runtime

The analyst and auditor share a small agent runtime that owns system instructions, input/output schemas, tool registration, memory access, budgets, retries, and trace events. Agent-specific behavior remains separate from Azure SDK and CLI details.

```python
class Agent(Protocol):
    async def run(self, input: AgentInput) -> AgentResult:
        ...
```

The runtime validates structured output before passing it to another component and records every model and tool interaction.

### Analyst agent

The analyst follows an explicit research loop:

```text
Plan -> retrieve memory -> search in parallel -> fetch evidence
     -> cross-check weak claims -> synthesize cited answer
```

Its structured result contains the answer, claims, citations, confidence, and limitations. It must state when evidence cannot be found rather than inventing a plausible response.

### Auditor agent

The auditor independently extracts claims from the analyst result, opens cited URLs, compares source content with each claim, and emits one verdict per claim:

- `supported`
- `unsupported`
- `contradicted`
- `uncited`

The auditor receives the answer and citations but must perform its own source verification rather than trusting analyst evidence summaries.

### Query expansion and entity resolution

Before retrieval, the analyst produces a bounded structured search plan. It may expand one question into independent subqueries with explicit purposes, entities, and date constraints. Expansion is one step only, has a maximum query count, removes duplicates, and runs independent searches concurrently.

Entity resolution combines normalized names, stored aliases, exact matches, fuzzy matching, and a model fallback for ambiguous mentions. Low-confidence matches remain unresolved rather than being silently merged. Resolution decisions and aliases are stored in SQLite.

### Embedding and retrieval layer

Fetched pages are normalized and split into citation-preserving chunks. Every chunk stores its source URL, title, section, position, entity identifiers, publication date, and content hash.

An embedding provider batches and caches embeddings by content hash. The embeddings and chunk metadata are indexed in Azure AI Search. Retrieval uses hybrid keyword plus vector search, with metadata filters for entities, sources, and dates. Results retain citation metadata so both the analyst and auditor can trace evidence back to the original page.

The search interface is provider-independent:

```python
class Retriever(Protocol):
    async def search(self, query: str, *, filters: SearchFilters, limit: int) -> list[Evidence]:
        ...
```

Azure AI Search is the required production retrieval implementation. SQLite remains the application-memory store for entities, aliases, claims, audit findings, and run metadata.

### Azure model adapter

Agents depend on a provider interface rather than Azure SDK details:

```python
class ModelProvider(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        ...
```

The Azure implementation reads endpoint, deployment, and authentication from environment configuration. It records token usage, estimated cost, latency, retries, and model errors. The provider boundary allows the Azure deployment/model to change without changing agent logic.

### Web tools

The initial tool set is deliberately small:

- Web search
- Page fetching
- Optional text extraction/normalization

Tool calls are structured and recorded. Independent searches should run concurrently where useful.

### Application memory store

SQLite stores entities, aliases, facts, sources, verified claims, audit verdicts, timestamps, research warnings, and links between them. Azure AI Search stores searchable evidence chunks and vectors; SQLite stores durable application decisions and orchestration state. Memory accelerates later questions but does not replace verification of current facts. Auditor findings and research warnings may be stored for later related questions.

### Run recorder

Every meaningful event is persisted as a JSONL-style trace event containing timestamp, run ID, agent, event type, input/output metadata, duration, and error details. Traces support assignment logs, debugging, replay, parallelism evidence, and cost analysis.

## Reliability and quality layer

The reliability layer is deterministic and owns safeguards around probabilistic agent behavior.

### Input and budget controls

- Reject empty or malformed questions.
- Set wall-clock, token, model-cost, and web-request budgets.
- Detect and report incomplete runs when a budget is exhausted.

### Structured-output validation

- Validate model responses against schemas.
- Require valid claim and citation fields.
- Retry malformed output with a correction prompt when safe.
- Never pass invalid structured data silently between stages.

### Evidence gates

A successful answer requires:

- Every factual claim has at least one citation.
- Each citation contains a URL and retrievable content.
- Every claim has an auditor verdict.
- Contradicted and unsupported claims are visibly marked.
- The trace is saved.

If these conditions are not met, the system reports `incomplete` rather than claiming success.

### Operational resilience

- Bounded retries with backoff for transient Azure or web failures.
- Per-tool and per-question timeouts.
- Graceful continuation when one parallel branch fails.
- Partial trace persistence before fatal termination.
- Clear distinction between evidence failure, model failure, and infrastructure failure.

The auditor itself may fail. In that case, the analyst output is preserved but clearly labeled as unaudited.

## Conflict handling

When credible sources disagree, the system preserves both sources and asks the analyst to resolve the conflict using source date, authority, and methodology. The final answer explains the chosen interpretation. It must not hide disagreement or simply report conflicting numbers without analysis.

## Evaluation

Create eight questions with increasing difficulty:

1. One entity and one straightforward fact.
2. One entity with multiple attributes.
3. A two-source comparison.
4. Several entities ranked by a metric.
5. Time-sensitive current information.
6. A question requiring many sources.
7. A question reusing an entity from earlier runs.
8. A conflicting-source or incomplete-evidence question.

At least two questions reuse earlier entities to measure memory value.

Record per question:

- Claim count and supported/unsupported/contradicted counts
- Citation coverage
- Analyst, auditor, and total latency
- Input/output tokens and estimated Azure cost
- Search and fetch counts
- Memory hits
- Parallel versus sequential tool activity
- Whether the answer was complete

The evaluation report should show cost and quality trends across the eight questions. A feedback loop should store auditor findings as reusable warnings and make them available to later related analyst runs.

## Deliberate non-goals

To stay within the assignment time limit, the first version will not include:

- A web frontend
- User authentication
- A distributed worker system
- Fine-tuning or model training
- A general-purpose autonomous planning framework
- Silent answer correction by the auditor
- Multiple search indexes or a generic vector-database abstraction beyond Azure AI Search

## Acceptance criteria

The project is ready for submission when:

1. A clean checkout can be configured and run using the README in under five minutes.
2. `dyla ask` automatically produces a cited analyst answer and an audit report.
3. The analyst uses real web search and page-fetch tools.
4. Independent tool calls run in parallel where appropriate.
5. Memory is persisted and visibly reused by later questions.
6. Every run has a complete trace under `logs/` (with optional replayable artifacts under `runs/`).
7. The auditor classifies claims and flags missing, unsupported, and contradicted evidence.
8. The eight-question evaluation reports correctness, cost, latency, and memory metrics.
9. Failures and limitations are explicit in the README and `DECISIONS.md`.
10. Azure credentials are supplied through environment variables and no secrets are committed.
11. Azure AI Search stores citation-preserving chunks with embeddings and supports hybrid retrieval.
12. Query expansion is bounded, traced, deduplicated, and measured.
13. Entity resolution records aliases, confidence, and unresolved ambiguities rather than silently merging entities.
