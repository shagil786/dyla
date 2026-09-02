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

## Review-fix report

### Findings addressed

- Extended `ModelResponse` with deployment/model pricing inputs, estimated cost, retry count, HTTP status, and error metadata. Added `ModelTelemetry` and `ModelCallError`; failed calls raise the latter with latency, retry count, status, pricing inputs, and a redacted error description attached as `exc.telemetry`.
- Namespaced embedding cache keys with endpoint, API version, deployment, model, and content hash, preventing vectors from different embedding deployments/models from being reused.
- Added fake-transport coverage for 429 retry success, retry exhaustion, exact bounded attempts, and configurable bounded delays.
- Added explicit idempotent `close()` methods and `with` support for both adapters. Closing the embedding adapter closes SQLite and HTTP resources.

### TDD red evidence

Before the implementation changes, the new review-fix tests failed with **5 failed, 4 passed**, including:

```text
TypeError: AzureChatModel.__init__() got an unexpected keyword argument 'input_cost_per_1k'
AttributeError: 'ModelResponse' object has no attribute 'retry_count'
AttributeError: 'RuntimeError' object has no attribute 'telemetry'
AttributeError: 'AzureEmbeddingModel' object has no attribute 'close'
TypeError: 'AzureEmbeddingModel' object does not support the context manager protocol
```

### Exact validation commands and output

Focused review-fix tests:

```text
$ .venv/bin/pytest -q tests/unit/test_azure_models.py
.........                                                                                    [100%]
9 passed in 0.11s
```

Full test suite:

```text
$ .venv/bin/pytest -q
....................................                                                         [100%]
36 passed in 0.17s
```

Diagnostics:

```text
$ diagnostics src/dyla/azure_models.py
File doesn't have errors or warnings!
```

## Review-fix concerns

- Failed calls expose zero token counts because Azure does not return usage on an HTTP failure; the attached telemetry still records latency, pricing inputs, retry count, status, and redacted error metadata.
- The cache namespace includes the configured endpoint/API version, deployment, and model. Existing databases created by the original content-only schema should be migrated or discarded before reuse; the revised adapter will not intentionally reuse those incompatible rows.
- The adapters remain synchronous to preserve the existing provider contracts.

## Second review-fix report

### Findings addressed

- Normalized outer JSON decoding, malformed chat payloads, and Pydantic response validation into `ModelCallError`. Each carries latency, retry count, HTTP status, deployment/model, pricing inputs, zero/known token counts, estimated cost, and redacted error metadata.
- Added `EmbeddingCacheCompatibilityError` and schema inspection during cache initialization. Databases with the old `content_hash` primary-key schema now fail clearly before any cache query; namespaced `cache_key` databases continue normally.
- Added fake-transport regression coverage for all three malformed chat response classes and a legacy SQLite schema.

### TDD red evidence

Before the implementation changes, the new regression tests failed with **4 failed, 9 passed**, including raw `JSONDecodeError`, `IndexError`, and Pydantic `ValidationError` failures, plus:

```text
Failed: DID NOT RAISE <class 'RuntimeError'>
```

### Exact validation commands and output

Focused re-review tests:

```text
$ .venv/bin/pytest -q tests/unit/test_azure_models.py
.............                                                                                [100%]
13 passed in 0.13s
```

Full test suite:

```text
$ .venv/bin/pytest -q
........................................                                                     [100%]
40 passed in 0.13s
```

Diagnostics:

```text
$ diagnostics src/dyla/azure_models.py
File doesn't have errors or warnings!

$ diagnostics src/dyla/models.py
File doesn't have errors or warnings!
```

Whitespace validation:

```text
$ git --no-pager diff --check
```

### Decisions and concerns

- Legacy content-only cache rows are not migrated because their embedding deployment/model namespace cannot be identified safely; initialization fails with an actionable compatibility error rather than risking incompatible vector reuse.
- Malformed successful HTTP responses use status `200`, preserve retry count, and report zero token/cost values because no trustworthy usage data exists.
- The adapter remains synchronous and retains the explicit `close()`/context-manager boundary from the prior fix.
