# Task 4 Report: Azure model and embedding adapters

## Files

- `src/dyla/models.py` — added `ModelRequest`, `ModelResponse`, `ModelProvider`, and `EmbeddingProvider` contracts.
- `src/dyla/azure_models.py` — added Azure chat and embedding adapters using `httpx`.
- `tests/unit/test_azure_models.py` — added fake-transport tests for structured output, usage parsing, batching/cache reuse, retries, and secret redaction.
- `pyproject.toml` — added the runtime dependency `httpx>=0.27,<1.0`.

## Exact validation commands and output

Focused adapter tests:

```text
$ .venv/bin/pytest -q tests/unit/test_azure_models.py
....                                                                                         [100%]
4 passed in 0.09s
```

Full test suite and whitespace validation:

```text
$ .venv/bin/pytest -q && git --no-pager diff --check
...............................                                                              [100%]
31 passed in 0.11s
```

Diagnostics:

```text
$ diagnostics src/dyla/models.py
File doesn't have errors or warnings!

$ diagnostics src/dyla/azure_models.py
File doesn't have errors or warnings!
```

## Decisions

- Used injectable `httpx` transports and sleepers so tests never use Azure credentials or the network.
- Used Azure OpenAI deployment URLs with the configured API version and `api-key` header.
- Structured responses request Azure JSON Schema output and validate the returned JSON with the supplied Pydantic model.
- Retries are limited to HTTP 429 and 5xx responses, with bounded exponential delays (`base * 2^attempt`); request timeouts are also retried within the same bound.
- Parsed both Azure's chat usage names (`prompt_tokens`, `completion_tokens`) and the equivalent input/output names.
- Cached embeddings by SHA-256 content hash in a local SQLite `embedding_cache` table, preserving input order and batching misses only.
- Error messages include status and response detail but replace the configured API key with `[REDACTED]`.

## Concerns

- The cache key is the text content hash only. A cache database should not be shared between incompatible embedding deployments or models; deployment-specific cache namespaces can be added if that becomes a requirement.
- The adapter currently exposes a synchronous interface, matching the requested provider contracts.
- No live Azure credential or endpoint validation was performed by design.
