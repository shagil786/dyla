# Task 5 Report: Web tools, normalization, chunking, and Azure AI Search

## Status

Implemented Task 5 from the brief. No real Azure credentials or live services were used.

## Tests and exact output

Focused TDD RED checks:

- `.venv/bin/pytest -q tests/unit/test_web.py tests/unit/test_chunking.py tests/unit/test_search.py tests/integration/test_azure_search.py`
  - Initial result: collection errors because `dyla.web`, `dyla.chunking`, and `dyla.search` did not yet exist.
- `.venv/bin/pytest -q tests/unit/test_ingest.py`
  - Initial result: collection error because `dyla.ingest` did not yet exist.
- `.venv/bin/pytest -q tests/unit/test_search.py::test_search_index_can_embed_chunks_when_vectors_are_not_supplied`
  - Initial result: 1 expected failure because `SearchIndex` did not yet accept an injected embedder.

Focused GREEN result after implementation:

```text
...........s                                                                                 [100%]
11 passed, 1 skipped in 0.09s
```

Full suite result:

```text
s......................................................                                      [100%]
54 passed, 1 skipped in 0.22s
```

The one skipped test is `tests/integration/test_azure_search.py`, gated by `DYLA_RUN_LIVE_TESTS=1`.

Diagnostics were also run on each changed production module. `search.py`, `chunking.py`, `ingest.py`, and `domain.py` have no diagnostics. The web import-order warning was fixed; the remaining project diagnostic is the pre-existing analyzer warning on `AuditVerdict.status` in `domain.py`.

## Files changed

- `src/dyla/web.py`
  - Added HTTPS-only external URL validation.
  - Rejects local, loopback, private, link-local, reserved, `.local`, and credential-bearing URLs.
  - Added `PageFetcher` with response size/content-type checks, redirect-target validation, HTML normalization, title extraction, boilerplate removal, and deterministic source IDs.
  - Added `WebSearcher` Bing-compatible adapter returning `SearchHit` contracts.
- `src/dyla/chunking.py`
  - Added deterministic heading/paragraph-aware chunking.
  - Supports bounded chunk sizes and overlap.
  - Preserves URL, title, source ID, section, position, entity IDs, publication date, content hash, and deterministic chunk ID.
- `src/dyla/search.py`
  - Added Azure AI Search REST adapter.
  - Creates a vector-enabled index schema using configured vector dimensions.
  - Supports batched merge-or-upload operations.
  - Supports injected embedding models for `upsert(chunks)` as well as explicitly supplied vectors.
  - Performs keyword plus vector hybrid search with entity/source/date OData filters.
- `src/dyla/ingest.py`
  - Added fetch-independent embedding ingestion orchestration: chunk, embed, validate vector count, and upsert.
- `src/dyla/domain.py`
  - Added optional `published_at` to `EvidenceChunk` to preserve citation/date metadata without breaking earlier constructors.
- `src/dyla/config.py`
  - Added `azure_search_vector_dimensions` with a backward-compatible default of `1536`.
- `tests/unit/test_web.py`
- `tests/unit/test_chunking.py`
- `tests/unit/test_search.py`
- `tests/unit/test_ingest.py`
- `tests/integration/test_azure_search.py`

## Decisions

1. Used Azure AI Search REST endpoints rather than adding the Azure Search SDK dependency; this keeps the package dependency-light and makes mocked transport tests deterministic.
2. Used the existing `AzureEmbeddingModel` through a small protocol/injection boundary rather than duplicating embedding HTTP or cache logic.
3. Made vector dimensions configuration-driven with a default of 1536 for compatibility with existing settings construction.
4. Kept `chunk_document` strict about invalid overlap limits, while ingestion clamps its convenience default when a caller intentionally chooses a small `max_chars`.
5. Used standard-library `HTMLParser` and conservative block filtering instead of adding BeautifulSoup or another parser dependency.
6. Kept the live Azure test explicitly opt-in and skipped by default so ordinary tests never require credentials or network access.

## Concerns and follow-up

- The live integration test is an explicit opt-in smoke-test gate but is intentionally not run in this environment because no real credentials are available. A deployment environment should add a credentialed live test body if live schema/retrieval verification is required.
- `PageFetcher` enforces the configured limit after the HTTP response has been received. This bounds retained/parsed content but is not a streaming network-level download cap; a future hardening pass could use streaming reads.
- Web search is implemented against the Bing Web Search v7-compatible response shape. If the deployment uses a different provider, its endpoint/field mapping should be configured or adapted.
- The analyzer still reports the existing `AuditVerdict.status` diagnostic; it is unrelated to Task 5 and does not affect the pytest suite.
